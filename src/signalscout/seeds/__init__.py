"""Seed sources: which companies to look at.

* ``yc``: the YC company directory as published by yc-oss (a public mirror of YC's own directory),
  filtered to active, US, B2B companies in a team-size band.
* ``csv``: a hand-written list (``name,domain``), for accounts no public directory covers.

Seeds decide what gets looked at, never what gets scored: a company that fails a fit rule still
appears in the output with the reason it scored low.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from signalscout.accounts import Account
from signalscout.fetch import Fetcher, FetchError
from signalscout.normalize import clean_company_name, registrable_domain

YC_URL = "https://yc-oss.github.io/api/companies/all.json"
US = "United States of America"


@dataclass(frozen=True)
class YcFilter:
    min_team: int = 50
    max_team: int = 500
    industry: str = "B2B"
    us_only: bool = True


@dataclass(frozen=True)
class SeedReport:
    loaded: int
    kept: int
    dropped: dict[str, int]


def _is_us(company: dict[str, Any]) -> bool:
    regions = company.get("regions") or []
    locations = str(company.get("all_locations") or "")
    return US in regions or locations.endswith(", USA") or ", USA;" in locations


DEFAULT_YC_FILTER = YcFilter()


def yc_accounts(
    companies: list[dict[str, Any]], rules: YcFilter = DEFAULT_YC_FILTER
) -> tuple[list[Account], SeedReport]:
    """Filter the directory; count every drop reason so the README can say what was excluded."""
    kept: list[Account] = []
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for company in companies:
        if company.get("status") != "Active":
            drop("not active")
            continue
        if rules.industry not in (company.get("industries") or []):
            drop(f"not {rules.industry}")
            continue
        if rules.us_only and not _is_us(company):
            drop("not US")
            continue
        size = company.get("team_size")
        if not isinstance(size, int):
            drop("team size unknown")
            continue
        if not rules.min_team <= size <= rules.max_team:
            drop("team size out of band")
            continue
        domain = registrable_domain(str(company.get("website") or ""))
        if domain is None:
            drop("no website")
            continue
        kept.append(
            Account(
                company_key=domain,
                name=clean_company_name(str(company.get("name", ""))) or domain,
                domain=domain,
                sources=("yc",),
                team_size=size,
                location=str(company.get("all_locations") or ""),
                industries=tuple(company.get("industries") or ()),
                yc_slug=company.get("slug"),
                yc_batch=company.get("batch"),
                yc_hiring=company.get("isHiring"),
            )
        )
    return kept, SeedReport(len(companies), len(kept), dict(sorted(dropped.items())))


def fetch_yc(fetcher: Fetcher) -> list[dict[str, Any]]:
    response = fetcher.get(YC_URL)
    if not response.ok:
        raise FetchError(f"YC directory: HTTP {response.status}")
    data: list[dict[str, Any]] = response.json()
    return data


def csv_accounts(path: Path) -> list[Account]:
    """``name,domain`` rows (extra columns ignored); rows without a usable domain are skipped."""
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    accounts: list[Account] = []
    for row in rows:
        domain = registrable_domain(row.get("domain", "") or row.get("website", ""))
        if domain is None:
            continue
        name = clean_company_name(row.get("name", "")) or domain
        accounts.append(Account(company_key=domain, name=name, domain=domain, sources=("seed",)))
    return accounts
