"""Write a run's results for the three places they go.

* ``accounts.csv``: every account with its tier, score, signals and reasons, for review.
* ``tier_a.csv``: the Clay import. Tier A only, capped at Clay's free-plan table size, with the
  columns the Clay table spec (``clay/table_spec.yaml``) expects.
* ``pipelineos/companies.csv`` + ``pipelineos/contacts.csv``: PipelineOS's load format.
  ``companies.csv`` starts with PipelineOS's golden columns in their exact order, then
  ``signal_*`` columns its GTM-consultancy spec declares. ``contacts.csv`` is header-only:
  ``pipelineos load`` reads both files, and SignalScout never collects people.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from signalscout.score import ScoredAccount

CLAY_FREE_ROWS = 200

# PipelineOS's GOLDEN_COMPANY_FIELDS / GOLDEN_CONTACT_FIELDS, in order (pipelineos/data/clean.py).
PIPELINEOS_COMPANY_FIELDS = (
    "company_key",
    "name",
    "domain",
    "numberofemployees",
    "industry",
    "merged_rows",
)
PIPELINEOS_CONTACT_FIELDS = (
    "contact_id",
    "email",
    "firstname",
    "lastname",
    "phone",
    "jobtitle",
    "company_key",
    "company_name",
    "signup_source",
    "created_at",
    "other_emails",
    "merged_rows",
)
SIGNAL_FIELDS = (
    "signal_tier",
    "signal_score",
    "signal_reasons",
    "signal_best_role",
    "signal_crm",
    "signal_funding_date",
    "signal_funding_amount",
    "signal_checked_at",
)

ACCOUNT_FIELDS = (
    "company_key",
    "name",
    "domain",
    "tier",
    "score",
    "fit",
    "intent",
    "team_size",
    "location",
    "sources",
    "job_board",
    "board_found_via",
    "open_jobs",
    "gtm_ops_openings",
    "best_role",
    "best_role_url",
    "crm",
    "crm_confidence",
    "funding_amount",
    "funding_date",
    "stage_guess",
    "site_tools",
    "reasons",
    "errors",
)
CLAY_FIELDS = (
    "company_name",
    "domain",
    "tier",
    "score",
    "why_now",
    "best_role",
    "best_role_url",
    "crm",
    "funding_amount",
    "funding_date",
    "team_size",
)


def _best_role(s: ScoredAccount) -> tuple[str, str]:
    if not s.signals.gtm_roles:
        return "", ""
    # the role the score used: the one named in the "Hiring:" reason
    hiring = next((r for r in s.reasons if r.startswith("Hiring: ")), "")
    for _, job in s.signals.gtm_roles:
        if hiring.startswith(f"Hiring: {job.title} ("):
            return job.title, job.url
    _, job = s.signals.gtm_roles[0]
    return job.title, job.url


def account_row(s: ScoredAccount) -> dict[str, str]:
    sig, account = s.signals, s.signals.account
    best, url = _best_role(s)
    funding = sig.funding
    return {
        "company_key": account.company_key,
        "name": account.name,
        "domain": account.domain,
        "tier": s.tier,
        "score": str(s.score),
        "fit": str(s.fit),
        "intent": str(s.intent),
        "team_size": "" if account.team_size is None else str(account.team_size),
        "location": account.location,
        "sources": ";".join(account.sources),
        "job_board": f"{sig.board.board.ats}:{sig.board.board.slug}" if sig.board else "",
        "board_found_via": sig.board.via if sig.board else "",
        "open_jobs": str(sig.open_jobs),
        "gtm_ops_openings": "; ".join(job.title for _, job in sig.gtm_roles),
        "best_role": best,
        "best_role_url": url,
        "crm": (sig.crm.crm or "") if sig.crm else "",
        "crm_confidence": sig.crm.confidence if sig.crm else "none",
        "funding_amount": ""
        if not funding or funding.amount_sold is None
        else str(int(funding.amount_sold)),
        "funding_date": funding.round_date.isoformat() if funding else "",
        "stage_guess": funding.stage_guess if funding else "",
        "site_tools": ";".join(sig.site.tools) if sig.site else "",
        "reasons": "; ".join(s.reasons),
        "errors": "; ".join(sig.errors),
    }


def _write(path: Path, fields: tuple[str, ...], rows: Iterable[dict[str, str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def write_outputs(
    scored: list[ScoredAccount], out_dir: Path, as_of: date, hubspot_tiers: str = "A"
) -> dict[str, int]:
    rows = [account_row(s) for s in scored]
    written = {"accounts.csv": _write(out_dir / "accounts.csv", ACCOUNT_FIELDS, rows)}

    tier_a = [r for r in rows if r["tier"] == "A"][:CLAY_FREE_ROWS]
    written["tier_a.csv"] = _write(
        out_dir / "tier_a.csv",
        CLAY_FIELDS,
        (
            {
                "company_name": r["name"],
                "domain": r["domain"],
                "tier": r["tier"],
                "score": r["score"],
                "why_now": r["reasons"],
                "best_role": r["best_role"],
                "best_role_url": r["best_role_url"],
                "crm": r["crm"],
                "funding_amount": r["funding_amount"],
                "funding_date": r["funding_date"],
                "team_size": r["team_size"],
            }
            for r in tier_a
        ),
    )

    handoff = [r for r in rows if r["tier"] in hubspot_tiers]
    written["pipelineos/companies.csv"] = _write(
        out_dir / "pipelineos" / "companies.csv",
        PIPELINEOS_COMPANY_FIELDS + SIGNAL_FIELDS,
        (
            {
                "company_key": r["company_key"],
                "name": r["name"],
                "domain": r["domain"],
                "numberofemployees": r["team_size"],
                "industry": "",
                "merged_rows": "",
                "signal_tier": r["tier"],
                "signal_score": r["score"],
                "signal_reasons": r["reasons"],
                "signal_best_role": r["best_role"],
                "signal_crm": r["crm"],
                "signal_funding_date": r["funding_date"],
                "signal_funding_amount": r["funding_amount"],
                "signal_checked_at": as_of.isoformat(),
            }
            for r in handoff
        ),
    )
    written["pipelineos/contacts.csv"] = _write(
        out_dir / "pipelineos" / "contacts.csv", PIPELINEOS_CONTACT_FIELDS, []
    )
    return written
