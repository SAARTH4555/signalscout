"""The account: one company, identified by its registrable domain, plus what we know up front.

Every seed source produces ``Account`` rows; ``merge_accounts`` folds rows for the same
``company_key`` together, so a company that is both in the YC directory and in a hand-written
seed list is looked at once, with the richer YC fields kept.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Account:
    company_key: str  # registrable domain, lowercase: the join key everywhere, including HubSpot
    name: str
    domain: str
    sources: tuple[str, ...] = ()
    team_size: int | None = None
    location: str = ""
    industries: tuple[str, ...] = ()
    yc_slug: str | None = None
    yc_batch: str | None = None
    yc_hiring: bool | None = None
    extra: dict[str, str] = field(default_factory=dict, compare=False)


def merge_accounts(rows: Iterable[Account]) -> list[Account]:
    """One account per company_key; first-seen values win, gaps are filled from later rows."""
    merged: dict[str, Account] = {}
    for row in rows:
        current = merged.get(row.company_key)
        if current is None:
            merged[row.company_key] = row
            continue
        merged[row.company_key] = replace(
            current,
            sources=tuple(dict.fromkeys(current.sources + row.sources)),
            team_size=current.team_size if current.team_size is not None else row.team_size,
            location=current.location or row.location,
            industries=current.industries or row.industries,
            yc_slug=current.yc_slug or row.yc_slug,
            yc_batch=current.yc_batch or row.yc_batch,
            yc_hiring=current.yc_hiring if current.yc_hiring is not None else row.yc_hiring,
        )
    return sorted(merged.values(), key=lambda a: a.company_key)
