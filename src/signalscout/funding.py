"""Recent funding from SEC Form D filings: free, public, and filed within 15 days of a raise.

US startups raising under Regulation D file a Form D, which states the amount sold and the date
of first sale. Two requests per company:

1. EDGAR full-text search for Form D filings by entity name in the look-back window. Legal forms
   are stripped first, because EDGAR's conformed names use "Corp" where people write
   "Corporation" and an exact-name query then finds nothing.
2. The latest matching filing's ``primary_doc.xml`` (the raw XML, not the rendered page).

What Form D cannot tell us, said plainly where it is used:
- **No round letter.** "Series A/B/C" is a guess from the amount sold, labelled as a guess.
- **Most filers are funds and SPVs.** Pooled investment funds and fund-like names are dropped.
- **Name collisions.** A filing is accepted only if its issuer name matches the company's name
  closely after normalisation; ambiguous matches are reported as no funding rather than guessed.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from rapidfuzz import fuzz

from signalscout.accounts import Account
from signalscout.fetch import Fetcher
from signalscout.normalize import company_name_key, strip_legal_form

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
NAME_MATCH = 90.0
FUND_NAME = re.compile(
    r"\b(fund|funds|partners|l\.?p\.?|spv|capital|ventures|investors|opportunit(y|ies)|"
    r"series [a-z0-9]+ of)\b",
    re.IGNORECASE,
)
# Rough round sizes for US venture rounds; a label to read, not a fact.
STAGE_BANDS: tuple[tuple[float, str], ...] = (
    (150e6, "growth (guess)"),
    (50e6, "Series B/C (guess)"),
    (15e6, "Series A/B (guess)"),
    (3e6, "Seed/Series A (guess)"),
    (0.0, "Pre-seed/Seed (guess)"),
)


@dataclass(frozen=True)
class Funding:
    cik: str
    issuer: str
    form: str  # "D" or "D/A"
    filed: date
    first_sale: date | None
    amount_sold: float | None
    offering_amount: float | None
    industry_group: str
    state: str

    @property
    def round_date(self) -> date:
        return self.first_sale or self.filed

    @property
    def stage_guess(self) -> str:
        if self.amount_sold is None:
            return "unknown"
        return next(label for floor, label in STAGE_BANDS if self.amount_sold >= floor)


def search_url(name: str, as_of: date, lookback_days: int) -> str:
    params = {
        "q": "",
        "forms": "D,D/A",
        "entityName": strip_legal_form(name),
        "dateRange": "custom",
        "startdt": (as_of - timedelta(days=lookback_days)).isoformat(),
        "enddt": as_of.isoformat(),
    }
    return f"{SEARCH_URL}?{urlencode(params)}"


def _display_name(raw: str) -> str:
    """``Prompt.io Inc.  (CIK 0001618436)`` -> ``Prompt.io Inc.``; tickers dropped too."""
    return re.sub(r"\s*\((CIK \d+|[A-Z.]{1,6})\)", "", raw).strip()


@dataclass(frozen=True)
class Hit:
    cik: str
    issuer: str
    form: str
    filed: date
    document_url: str


def parse_hits(data: dict[str, Any]) -> list[Hit]:
    hits: list[Hit] = []
    for raw in (data.get("hits") or {}).get("hits", []):
        source = raw.get("_source") or {}
        ciks, names = source.get("ciks") or [], source.get("display_names") or []
        adsh, _, filename = str(raw.get("_id", "")).partition(":")
        if not ciks or not names or not adsh or not filename:
            continue
        cik = str(int(ciks[0]))
        hits.append(
            Hit(
                cik=cik,
                issuer=_display_name(names[0]),
                form=str(source.get("form", "D")),
                filed=date.fromisoformat(source["file_date"]),
                document_url=(
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/"
                    f"{filename.split('/')[-1]}"  # drop the xslFormDX01/ rendering prefix
                ),
            )
        )
    return hits


def matches(issuer: str, account: Account) -> bool:
    a = company_name_key(strip_legal_form(issuer))
    b = company_name_key(strip_legal_form(account.name))
    return bool(a) and bool(b) and fuzz.ratio(a, b) >= NAME_MATCH


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(root: ET.Element, *path: str) -> str | None:
    """Find by local tag names, so the XML namespace (present or not) does not matter."""
    nodes = [root]
    for name in path:
        nodes = [child for node in nodes for child in node if _local(child.tag) == name]
        if not nodes:
            return None
    value = (nodes[0].text or "").strip()
    return value or None


def _amount(raw: str | None) -> float | None:
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None  # "Indefinite"


def parse_form_d(xml_text: str, hit: Hit) -> Funding | None:
    """``None`` for pooled investment funds; otherwise the offering's amounts and dates."""
    root = ET.fromstring(xml_text)
    pooled = _text(root, "offeringData", "typesOfSecuritiesOffered", "isPooledInvestmentFundType")
    industry = _text(root, "offeringData", "industryGroup", "industryGroupType") or ""
    if (pooled or "").lower() == "true" or "pooled investment fund" in industry.lower():
        return None
    first_sale = _text(root, "offeringData", "typeOfFiling", "dateOfFirstSale", "value")
    return Funding(
        cik=hit.cik,
        issuer=_text(root, "primaryIssuer", "entityName") or hit.issuer,
        form=hit.form,
        filed=hit.filed,
        first_sale=date.fromisoformat(first_sale) if first_sale else None,
        amount_sold=_amount(_text(root, "offeringData", "offeringSalesAmounts", "totalAmountSold")),
        offering_amount=_amount(
            _text(root, "offeringData", "offeringSalesAmounts", "totalOfferingAmount")
        ),
        industry_group=industry,
        state=_text(root, "primaryIssuer", "issuerAddress", "stateOrCountry") or "",
    )


def latest_funding(
    fetcher: Fetcher, account: Account, as_of: date, lookback_days: int = 540
) -> Funding | None:
    """The company's most recent non-fund Form D in the window, or ``None``."""
    response = fetcher.get(search_url(account.name, as_of, lookback_days))
    if not response.ok:
        return None
    candidates = [
        h
        for h in parse_hits(response.json())
        if matches(h.issuer, account) and not FUND_NAME.search(h.issuer)
    ]
    if len({h.cik for h in candidates}) > 1:
        return None  # two different issuers match the name: do not guess
    for hit in sorted(candidates, key=lambda h: h.filed, reverse=True):
        doc = fetcher.get(hit.document_url)
        if not doc.ok:
            continue
        try:
            funding = parse_form_d(doc.text, hit)
        except ET.ParseError:
            continue
        if funding is not None:
            return funding
    return None
