"""Rewrite the README's results section from results/*.json and the Clay spec, or check it.

Usage: uv run python scripts/render_readme.py [--check]

Nothing between the RESULTS markers is typed by hand. CI runs --check, so a README number can
only change by re-running the commands in scripts/reproduce.sh and committing their output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from signalscout.clay import budget, load_clay_spec

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
README = ROOT / "README.md"
START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def load(name: str) -> Any:
    path = RESULTS / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else None


def pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _counts(d: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in d.items()) or "none"


def run_section(title: str, run: dict[str, Any], note: str) -> list[str]:
    n = run["accounts"]
    tiers = run["tiers"]
    fetches = run["fetches"]
    lines = [
        f"### {title}",
        "",
        note,
        "",
        "| | |",
        "|---|---|",
        f"| Accounts looked at | {n:,} (as of {run['as_of']}) |",
        f"| Tiers | A {tiers['A']}, B {tiers['B']}, C {tiers['C']} |",
        f"| Job board found | {run['with_board']:,} of {n:,} ({_counts(run['boards_by_ats'])}; "
        f"via {_counts(run['boards_found_via'])}) |",
        f"| Open jobs read | {run['open_jobs_read']:,} |",
        f"| With a GTM-ops opening | {run['with_gtm_ops_opening']:,} "
        f"({_counts(run['gtm_ops_openings_by_kind'])}) |",
        f"| With a raise in the last year | {run['with_recent_funding']:,} |",
        f"| CRM identified | {sum(run['crm_identified_by_confidence'].values()):,} "
        f"({_counts(run['crm_identified_by_confidence'])} confidence) |",
        f"| Accounts with a failed source | {run['accounts_with_errors']:,} |",
        f"| Requests | {fetches.get('requests', 0):,}, of which {fetches.get('from_cache', 0):,} "
        f"from cache, {fetches.get('blocked_by_robots', 0):,} blocked by robots.txt, "
        f"{fetches.get('failed', 0):,} failed |",
        "",
    ]
    review = load("live_review") if title.startswith("Live") else None
    if review:
        lines += [
            f"Hand check of {review['accepted_checked']} accepted and "
            f"{review['rejected_checked']} rejected real job titles: precision "
            f"{pct(review['precision'])}, recall {pct(review['recall'])}.",
            "",
        ]
    return lines


def roles_section() -> list[str]:
    roles = load("roles")
    rows = [
        f"| {name} ({r['titles']} titles) | {pct(r['precision'])} | {pct(r['recall'])} | "
        f"{pct(r['kind_accuracy'])} | {pct(r['seniority_accuracy'])} |"
        for name, r in roles.items()
    ]
    return [
        "### GTM-ops title classifier",
        "",
        "Hand-labelled titles. The dev set was used to tune the rules; the holdout was written "
        "after tuning and never used to change a rule. Both were written by the rule author, so "
        "the holdout is not blind: read these as a floor check, and the live run's hand check "
        "(once run) as the real number.",
        "",
        "| Set | Precision | Recall | Role kind | Seniority |",
        "|---|---|---|---|---|",
        *rows,
        "",
    ]


def clay_section() -> list[str]:
    spec = load_clay_spec(ROOT / "clay" / "table_spec.yaml")
    b = budget(spec)
    return [
        "### Clay credit budget",
        "",
        f"Worst case from [`clay/table_spec.yaml`](clay/table_spec.yaml) on Clay {spec.plan.name} "
        f"({spec.plan.data_credits_per_month} credits, {spec.plan.actions_per_month} actions, "
        f"{spec.plan.rows_per_table} rows a month): every email provider tried, none found.",
        "",
        "| Per Tier-A account | Per month on this plan |",
        "|---|---|",
        f"| {b['credits_per_account']:g} credits, {b['actions_per_account']:g} actions | "
        f"{b['accounts_per_month']:g} accounts, {b['people_per_month']:g} people |",
        "",
    ]


def render() -> str:
    lines = [START, ""]
    live = load("live")
    if live:
        lines += run_section(
            "Live run",
            live,
            "Real public data: YC directory seeds, live job boards, SEC EDGAR and company sites. "
            "Account-level counts only; the account list itself is not committed.",
        )
    else:
        lines += ["### Live run", "", "Not run yet: see `docs/runbook.md`.", ""]
    lines += run_section(
        "Offline demo world",
        load("run_offline"),
        "`signalscout run --offline`: recorded synthetic responses for three fictional "
        "companies, built so every signal path runs. It shows the pipeline works end to end, "
        "not how common each signal is.",
    )
    lines += roles_section()
    lines += clay_section()
    lines.append(END)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = README.read_text()
    head, _, rest = text.partition(START)
    _, _, tail = rest.partition(END)
    updated = head + render() + tail
    if args.check:
        if updated != text:
            print("README results are stale: run scripts/render_readme.py", file=sys.stderr)
            sys.exit(1)
        print("README results are current")
        return
    README.write_text(updated)
    print("README results updated")


if __name__ == "__main__":
    main()
