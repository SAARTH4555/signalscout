from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from signalscout.accounts import Account
from signalscout.fetch import FakeFetcher
from signalscout.funding import (
    Funding,
    Hit,
    latest_funding,
    matches,
    parse_form_d,
    parse_hits,
    search_url,
)

SEC = Path(__file__).parent / "fixtures" / "sec"
AS_OF = date(2026, 10, 15)
LEDGERLINE = Account("ledgerline.io", "Ledgerline", "ledgerline.io")
DOC_2026 = "https://www.sec.gov/Archives/edgar/data/1999999/000199999926000002/primary_doc.xml"
DOC_FUND = "https://www.sec.gov/Archives/edgar/data/1888888/000188888826000004/primary_doc.xml"


def test_search_url_strips_legal_form_and_sets_window() -> None:
    url = search_url("Ramp Business Corporation", AS_OF, 540)
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    assert query["entityName"] == ["Ramp Business"]
    assert query["forms"] == ["D,D/A"]
    assert (query["startdt"], query["enddt"]) == (["2025-04-23"], ["2026-10-15"])


def test_parse_hits_builds_raw_xml_urls() -> None:
    hits = parse_hits(json.loads((SEC / "search_ledgerline.json").read_text()))
    assert [h.cik for h in hits] == ["1999999", "1999999", "1888888"]
    assert hits[0].issuer == "Ledgerline, Inc." and hits[0].filed == date(2026, 8, 27)
    assert hits[0].document_url == DOC_2026
    assert hits[2].document_url == DOC_FUND  # rendering prefix dropped
    assert parse_hits({"hits": {"hits": [{"_id": "x", "_source": {}}]}}) == []
    assert parse_hits({}) == []


def test_name_matching() -> None:
    assert matches("Ledgerline, Inc.", LEDGERLINE)
    assert matches("LEDGERLINE INC", LEDGERLINE)
    assert not matches("Ledgerline Labs Holdings Group", LEDGERLINE)
    assert not matches("", LEDGERLINE)


def test_parse_form_d() -> None:
    hit = Hit("1999999", "Ledgerline, Inc.", "D", date(2026, 8, 27), DOC_2026)
    funding = parse_form_d((SEC / "form_d_ledgerline_2026.xml").read_text(), hit)
    assert funding == Funding(
        cik="1999999",
        issuer="Ledgerline, Inc.",
        form="D",
        filed=date(2026, 8, 27),
        first_sale=date(2026, 8, 14),
        amount_sold=30_500_000.0,
        offering_amount=32_000_000.0,
        industry_group="Other Technology",
        state="CA",
    )
    assert funding.round_date == date(2026, 8, 14)
    assert funding.stage_guess == "Series A/B (guess)"
    assert parse_form_d((SEC / "form_d_fund.xml").read_text(), hit) is None


def test_stage_guess_bands() -> None:
    def f(amount: float | None) -> str:
        return Funding("1", "x", "D", AS_OF, None, amount, None, "", "").stage_guess

    assert [f(a) for a in (1e6, 5e6, 20e6, 80e6, 400e6, None)] == [
        "Pre-seed/Seed (guess)",
        "Seed/Series A (guess)",
        "Series A/B (guess)",
        "Series B/C (guess)",
        "growth (guess)",
        "unknown",
    ]
    undated = Funding("1", "x", "D", AS_OF, None, None, None, "", "")
    assert undated.round_date == AS_OF


def test_latest_funding_end_to_end() -> None:
    fake = FakeFetcher(
        {
            search_url("Ledgerline", AS_OF, 540): (SEC / "search_ledgerline.json").read_text(),
            DOC_2026: (SEC / "form_d_ledgerline_2026.xml").read_text(),
            DOC_FUND: (SEC / "form_d_fund.xml").read_text(),
        }
    )
    funding = latest_funding(fake, LEDGERLINE, AS_OF)
    assert funding is not None and funding.first_sale == date(2026, 8, 14)
    assert DOC_FUND not in fake.calls  # fund-like issuer filtered before fetching


def test_no_match_ambiguous_and_broken_cases() -> None:
    assert latest_funding(FakeFetcher(), LEDGERLINE, AS_OF) is None  # search failed
    search = search_url("Ledgerline", AS_OF, 540)
    data = json.loads((SEC / "search_ledgerline.json").read_text())
    data["hits"]["hits"][1]["_source"]["ciks"] = ["0001777777"]  # a second "Ledgerline Inc"
    assert latest_funding(FakeFetcher({search: json.dumps(data)}), LEDGERLINE, AS_OF) is None
    broken = FakeFetcher(
        {search: (SEC / "search_ledgerline.json").read_text(), DOC_2026: "<not xml"}
    )
    assert latest_funding(broken, LEDGERLINE, AS_OF) is None  # 2025 doc missing (404) too
