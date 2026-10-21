"""Score the GTM-ops title classifier on the hand-labelled title sets in evals/.

Usage: uv run python scripts/eval_roles.py [--out results/roles.json]

``dev`` (titles_dev.jsonl) was used to tune the rules. ``holdout`` (titles_holdout.jsonl) was
written after tuning and never used to change a rule, so its numbers are the ones to quote.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from signalscout.roles import classify_title

EVALS = Path(__file__).resolve().parents[1] / "evals"
SETS = {"dev": EVALS / "titles_dev.jsonl", "holdout": EVALS / "titles_holdout.jsonl"}


def evaluate(rows: list[dict[str, str | None]]) -> dict[str, object]:
    tp = fp = fn = tn = kind_ok = seniority_ok = 0
    misses: list[dict[str, object]] = []
    for row in rows:
        match = classify_title(str(row["title"]))
        expected = row["kind"] is not None
        got = match is not None
        if expected and got:
            tp += 1
            assert match is not None
            kind_ok += match.kind == row["kind"]
            seniority_ok += match.seniority == row["seniority"]
            if match.kind != row["kind"] or match.seniority != row["seniority"]:
                misses.append(
                    {
                        "title": row["title"],
                        "expected": [row["kind"], row["seniority"]],
                        "got": [match.kind, match.seniority],
                    }
                )
        elif got:
            fp += 1
            assert match is not None
            misses.append({"title": row["title"], "expected": None, "got": [match.kind]})
        elif expected:
            fn += 1
            misses.append({"title": row["title"], "expected": [row["kind"]], "got": None})
        else:
            tn += 1
    return {
        "titles": len(rows),
        "gtm_ops_roles": tp + fn,
        "precision": round(tp / (tp + fp), 3) if tp + fp else 1.0,
        "recall": round(tp / (tp + fn), 3) if tp + fn else 1.0,
        "kind_accuracy": round(kind_ok / tp, 3) if tp else 1.0,
        "seniority_accuracy": round(seniority_ok / tp, 3) if tp else 1.0,
        "misses": misses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    results = {}
    for name, path in SETS.items():
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        results[name] = evaluate(rows)
    for name, r in results.items():
        print(
            f"{name:8} precision {r['precision']}  recall {r['recall']}  "
            f"kind {r['kind_accuracy']}  seniority {r['seniority_accuracy']}  "
            f"({r['titles']} titles)"
        )
        for miss in r["misses"]:  # type: ignore[attr-defined]
            print(f"   miss: {miss}")
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
