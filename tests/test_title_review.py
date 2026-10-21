from __future__ import annotations

import csv
import json
import runpy
import time
from pathlib import Path

import pytest

from signalscout.fetch import DiskCache, Response
from signalscout.jobs.ats import board_url
from signalscout.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "title_review.py"
BOARD = json.dumps(
    {
        "jobs": [
            {"title": "Revenue Operations Manager", "isListed": True},
            {"title": "Sales Engineer", "isListed": True},
            {"title": "Software Engineer", "isListed": True},
        ]
    }
)


def test_sample_reads_the_cache_then_score_counts_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIGNALSCOUT_CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    url = board_url("ashby", "ledgerline-demo")
    DiskCache(tmp_path / "cache").put(Response(url, 200, BOARD), time.time())
    accounts = tmp_path / "accounts.csv"
    accounts.write_text("company_key,job_board\nledgerline.example,ashby:ledgerline-demo\nquiet.io,\n")

    module = runpy.run_path(str(SCRIPT))
    module["sample"](accounts, 30, 7)
    review = tmp_path / "data" / "out" / "title_review.csv"
    rows = list(csv.DictReader(review.open()))
    by_title = {r["title"]: r for r in rows}
    assert by_title["Revenue Operations Manager"]["sample"] == "accepted"
    assert by_title["Sales Engineer"]["sample"] == "near_miss"  # GTM-ish word, rejected
    assert "Software Engineer" not in by_title  # plainly not GTM: not worth a reviewer's time

    for r in rows:
        r["is_gtm_ops"] = "yes" if r["sample"] == "accepted" else "no"
    with review.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    out = tmp_path / "live_review.json"
    module["score"](out, "a tester")
    assert json.loads(out.read_text()) == {
        "accepted_checked": 1,
        "accepted_correct": 1,
        "near_miss_checked": 1,
        "near_miss_missed": 0,
        "labelled_by": "a tester",
    }
    get_settings.cache_clear()
