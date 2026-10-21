"""Find a company's job board: from its careers page first, by educated guess second.

No ATS offers a reverse lookup from company to board slug. The reliable source is the company's
own careers page, which links to or embeds its board, so that is tried first (two pages, robots
respected). Failing that, a few slug candidates are probed on each ATS. A guessed board is only
accepted when it can be tied back to the company, because slugs collide: Greenhouse names the
board's company; for Ashby and Lever the company's name or domain must appear in a posting.

Cost per company: at most 2 page fetches plus 3 candidates x 3 ATS probes, all cached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from signalscout.accounts import Account
from signalscout.fetch import Fetcher, FetchError
from signalscout.jobs.ats import ATS_ORDER, Ats, Board, fetch_board
from signalscout.normalize import company_name_key, domain_label

CAREERS_PATHS = ("/careers", "/jobs")
LINK_PATTERNS: tuple[tuple[Ats, re.Pattern[str]], ...] = (
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9][\w.-]*)")),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9][\w-]*)")),
    (
        "greenhouse",
        re.compile(
            r"(?:job-)?boards\.greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9][\w-]*)"
        ),
    ),
    ("greenhouse", re.compile(r"(?:job-)?boards\.greenhouse\.io/(?!embed\b)([A-Za-z0-9][\w-]*)")),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9][\w.-]*)")),
)
NAME_MATCH = 85.0
MAX_CANDIDATES = 3

Via = Literal["careers_page", "guess"]


@dataclass(frozen=True)
class BoardMatch:
    board: Board
    via: Via
    verified: bool  # careers-page links are verified by definition


def links_on_page(text: str) -> list[tuple[Ats, str]]:
    """Every (ats, slug) linked or embedded on a page, in order, without repeats."""
    found: list[tuple[Ats, str]] = []
    for ats, pattern in LINK_PATTERNS:
        for match in pattern.finditer(text):
            slug = match.group(1).rstrip(".").lower()
            if (ats, slug) not in found:
                found.append((ats, slug))
    return found


def slug_candidates(account: Account) -> list[str]:
    raw = [account.yc_slug or "", domain_label(account.domain), company_name_key(account.name)]
    hyphenated = "-".join(re.findall(r"[a-z0-9]+", account.name.lower()))
    raw.append(hyphenated)
    out: list[str] = []
    for candidate in raw:
        if candidate and candidate not in out:
            out.append(candidate)
    return out[:MAX_CANDIDATES]


def belongs_to(board: Board, account: Account) -> bool:
    """Can this board be tied to this company, beyond its slug?"""
    if board.company_name:
        return fuzz.ratio(company_name_key(board.company_name), company_name_key(account.name)) >= (
            NAME_MATCH
        )
    # Descriptions only: a posting URL always contains the slug, which was guessed from the
    # company name, so matching it would "verify" every guess.
    needles = {company_name_key(account.name), domain_label(account.domain)}
    needles.discard("")
    for job in board.jobs:
        text = job.description.lower()
        squashed = re.sub(r"[^a-z0-9]", "", text)
        if account.domain in text:
            return True
        for needle in needles:
            short = len(needle) < 4  # "arc" inside "search" is not a match
            if (short and re.search(rf"\b{re.escape(needle)}\b", text)) or (
                not short and needle in squashed
            ):
                return True
    return False


def from_careers_page(fetcher: Fetcher, account: Account) -> BoardMatch | None:
    for path in CAREERS_PATHS:
        try:
            page = fetcher.get(f"https://{account.domain}{path}")
        except FetchError:
            continue
        if not page.ok:
            continue
        for ats, slug in links_on_page(page.text):
            board = fetch_board(fetcher, ats, slug)
            if board is not None:
                return BoardMatch(board, "careers_page", verified=True)
    return None


def by_guessing(fetcher: Fetcher, account: Account) -> BoardMatch | None:
    unverified: BoardMatch | None = None
    for slug in slug_candidates(account):
        for ats in ATS_ORDER:
            board = fetch_board(fetcher, ats, slug)
            if board is None:
                continue
            if belongs_to(board, account):
                return BoardMatch(board, "guess", verified=True)
            if unverified is None and not board.jobs:
                # An empty board cannot be checked; keep it only if nothing better turns up.
                unverified = BoardMatch(board, "guess", verified=False)
    return unverified


def find_board(fetcher: Fetcher, account: Account) -> BoardMatch | None:
    return from_careers_page(fetcher, account) or by_guessing(fetcher, account)
