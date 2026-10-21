"""Hand check of the GTM-ops title classifier on a live run's real job titles.

Usage:
  uv run python scripts/title_review.py sample [--accounts data/out/accounts.csv]
      -> data/out/title_review.csv: accepted titles and near-miss rejected titles, unlabelled
  (label the `is_gtm_ops` column yes/no by hand)
  uv run python scripts/title_review.py score [--out results/live_review.json]

Random rejected titles would be almost all engineers and tell us nothing, so the rejected sample
is "near misses": titles with words like sales, revenue, ops, CRM or marketing that the classifier
turned down. That is where a miss would hide. Boards are re-read from the HTTP cache, so no new
requests are made after the run. The review file holds public job titles only and stays in data/.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from pathlib import Path

from signalscout.fetch import DiskCache, HttpFetcher
from signalscout.jobs.ats import fetch_board
from signalscout.roles import classify_title
from signalscout.settings import get_settings

NEAR_MISS = re.compile(
    r"\b(sales|revenue|ops|operations|crm|salesforce|hubspot|marketing|growth|business|gtm|"
    r"go-to-market|customer success|enablement|systems)\b",
    re.IGNORECASE,
)
REVIEW = Path("data/out/title_review.csv")
FIELDS = ("company_key", "title", "classifier", "sample", "is_gtm_ops")


def sample(accounts_path: Path, per_side: int, seed: int) -> None:
    settings = get_settings()
    fetcher = HttpFetcher(
        contact_email=settings.contact_email,
        cache=DiskCache(settings.cache_dir),
        ttl_s=365 * 24 * 3600,  # read what the run cached; do not go back to the network
    )
    accepted: list[dict[str, str]] = []
    near_miss: list[dict[str, str]] = []
    with accounts_path.open() as handle:
        for row in csv.DictReader(handle):
            if not row["job_board"]:
                continue
            ats, slug = row["job_board"].split(":", 1)
            board = fetch_board(fetcher, ats, slug)  # type: ignore[arg-type]
            for job in board.jobs if board else ():
                match = classify_title(job.title)
                item = {
                    "company_key": row["company_key"],
                    "title": job.title,
                    "classifier": match.kind if match else "",
                    "is_gtm_ops": "",
                }
                if match:
                    accepted.append({**item, "sample": "accepted"})
                elif NEAR_MISS.search(job.title):
                    near_miss.append({**item, "sample": "near_miss"})
    rng = random.Random(seed)
    picked = rng.sample(accepted, min(per_side, len(accepted)))
    picked += rng.sample(near_miss, min(per_side, len(near_miss)))
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(picked)
    print(
        f"wrote {REVIEW}: {min(per_side, len(accepted))} of {len(accepted)} accepted, "
        f"{min(per_side, len(near_miss))} of {len(near_miss)} near-miss titles"
    )


def score(out: Path, labelled_by: str) -> None:
    with REVIEW.open() as handle:
        rows = [r for r in csv.DictReader(handle) if r["is_gtm_ops"].strip()]
    yes = {"yes", "y", "true", "1"}
    accepted = [r for r in rows if r["sample"] == "accepted"]
    near = [r for r in rows if r["sample"] == "near_miss"]
    result = {
        "accepted_checked": len(accepted),
        "accepted_correct": sum(r["is_gtm_ops"].strip().lower() in yes for r in accepted),
        "near_miss_checked": len(near),
        "near_miss_missed": sum(r["is_gtm_ops"].strip().lower() in yes for r in near),
        "labelled_by": labelled_by,
    }
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--accounts", type=Path, default=Path("data/out/accounts.csv"))
    s.add_argument("--per-side", type=int, default=30)
    s.add_argument("--seed", type=int, default=7)
    c = sub.add_parser("score")
    c.add_argument("--out", type=Path, default=Path("results/live_review.json"))
    c.add_argument("--labelled-by", required=True)
    args = parser.parse_args()
    if args.cmd == "sample":
        sample(args.accounts, args.per_side, args.seed)
    else:
        score(args.out, args.labelled_by)


if __name__ == "__main__":
    main()
