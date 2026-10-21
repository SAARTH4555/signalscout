"""One run: seeds -> per-account signals -> scores, with a count of everything that happened.

Each account is collected independently, so one company's broken careers page or an SEC hiccup
costs that account a signal, never the run: the failure is recorded on the account
(``errors``) and in the run report, and scoring uses what was collected. The one failure that
stops a run before it starts is configuration: SEC lookups without a contact email.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from signalscout.accounts import Account
from signalscout.crm import CrmGuess, guess_crm, scan_site
from signalscout.fetch import ConfigError, Fetcher, FetchError, Response
from signalscout.funding import Funding, latest_funding
from signalscout.jobs.discover import BoardMatch, find_board
from signalscout.roles import RoleMatch, classify_title, stack_from_jobs
from signalscout.score import AccountSignals, ScoredAccount, ScoringConfig, score_account


class CountingFetcher:
    """Wraps any fetcher to count network requests, cache hits, robots blocks and failures."""

    def __init__(self, inner: Fetcher) -> None:
        self.inner = inner
        self.counts: Counter[str] = Counter()

    def get(self, url: str) -> Response:
        try:
            response = self.inner.get(url)
        except FetchError:
            self.counts["failed"] += 1
            raise
        self.counts["requests"] += 1
        if response.from_cache:
            self.counts["from_cache"] += 1
        if response.blocked:
            self.counts["blocked_by_robots"] += 1
        return response


@dataclass(frozen=True)
class RunOptions:
    as_of: date
    with_funding: bool = True
    with_crm: bool = True
    funding_lookback_days: int = 540


def collect(fetcher: Fetcher, account: Account, options: RunOptions) -> AccountSignals:
    errors: list[str] = []
    board: BoardMatch | None = None
    try:
        board = find_board(fetcher, account)
    except FetchError as exc:
        errors.append(f"job board: {exc}")
    jobs = board.board.jobs if board else ()
    roles: list[tuple[RoleMatch, Any]] = []
    for job in jobs:
        match = classify_title(job.title)
        if match is not None:
            roles.append((match, job))
    stack = stack_from_jobs(j.description for j in jobs)

    funding: Funding | None = None
    if options.with_funding:
        try:
            funding = latest_funding(fetcher, account, options.as_of, options.funding_lookback_days)
        except FetchError as exc:
            errors.append(f"funding: {exc}")

    site = None
    if options.with_crm:
        site = scan_site(fetcher, account.domain)  # page failures are counted, not raised
        if site.failed and not site.pages:
            errors.append(f"website: none of {site.failed} pages could be fetched")
    crm: CrmGuess = guess_crm(stack, site)
    return AccountSignals(
        account=account,
        gtm_roles=tuple(roles),
        open_jobs=len(jobs),
        has_board=board is not None,
        funding=funding,
        crm=crm,
        board=board,
        site=site,
        errors=tuple(errors),
    )


@dataclass
class RunResult:
    scored: list[ScoredAccount]
    fetches: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict[str, object]:
        tiers = Counter(s.tier for s in self.scored)
        signals = [s.signals for s in self.scored]
        boards = Counter(s.board.board.ats for s in signals if s.board)
        via = Counter(s.board.via for s in signals if s.board)
        crm = Counter(s.crm.confidence for s in signals if s.crm and s.crm.crm)
        role_kinds = Counter(m.kind for s in signals for m, _ in s.gtm_roles)
        return {
            "accounts": len(self.scored),
            "tiers": {t: tiers.get(t, 0) for t in ("A", "B", "C")},
            "with_board": sum(boards.values()),
            "boards_by_ats": dict(sorted(boards.items())),
            "boards_found_via": dict(sorted(via.items())),
            "with_gtm_ops_opening": sum(1 for s in signals if s.gtm_roles),
            "gtm_ops_openings_by_kind": dict(sorted(role_kinds.items())),
            "open_jobs_read": sum(s.open_jobs for s in signals),
            "with_recent_funding": sum(1 for s in signals if s.funding),
            "crm_identified_by_confidence": dict(sorted(crm.items())),
            "accounts_with_errors": sum(1 for s in signals if s.errors),
            "fetches": dict(sorted(self.fetches.items())),
        }


def run(
    fetcher: Fetcher,
    accounts: list[Account],
    scoring: ScoringConfig,
    options: RunOptions,
    *,
    contact_email: str | None,
    progress: Callable[[int, int, ScoredAccount], None] | None = None,
) -> RunResult:
    if options.with_funding and not contact_email:
        raise ConfigError(
            "SEC lookups need a contact email: set SIGNALSCOUT_CONTACT_EMAIL or pass --no-funding"
        )
    counting = CountingFetcher(fetcher)
    scored: list[ScoredAccount] = []
    for i, account in enumerate(accounts, start=1):
        result = score_account(collect(counting, account, options), scoring, options.as_of)
        scored.append(result)
        if progress is not None:
            progress(i, len(accounts), result)
    scored.sort(key=lambda s: (-s.score, s.signals.account.company_key))
    return RunResult(scored, dict(counting.counts))
