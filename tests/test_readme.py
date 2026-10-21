from __future__ import annotations

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_readme.py"


def test_committed_readme_is_current(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["render_readme", "--check"])
    runpy.run_path(str(SCRIPT), run_name="__main__")


def test_stale_readme_fails_and_live_results_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = tmp_path / "results"
    shutil.copytree(ROOT / "results", results)
    live = json.loads((results / "run_offline.json").read_text())
    live["as_of"] = "2026-11-01"
    live["sources"] = {"job_boards": True, "sec_funding": True, "websites": True}
    (results / "live.json").write_text(json.dumps(live))
    (results / "live_review.json").write_text(
        json.dumps(
            {
                "accepted_checked": 30,
                "accepted_correct": 28,
                "near_miss_checked": 30,
                "near_miss_missed": 2,
                "labelled_by": "a reviewer",
            }
        )
    )
    readme = tmp_path / "README.md"
    readme.write_text("# x\n<!-- RESULTS:START -->\nstale\n<!-- RESULTS:END -->\n")

    module = runpy.run_path(str(SCRIPT))
    globals_ = module["main"].__globals__
    monkeypatch.setitem(globals_, "README", readme)
    monkeypatch.setitem(globals_, "RESULTS", results)
    monkeypatch.setattr(sys, "argv", ["render_readme", "--check"])
    with pytest.raises(SystemExit) as info:
        module["main"]()
    assert info.value.code == 1

    monkeypatch.setattr(sys, "argv", ["render_readme"])
    module["main"]()
    text = readme.read_text()
    assert "### Live run" in text and "(as of 2026-11-01)" in text
    assert "28 of 30 titles the classifier accepted are GTM-ops roles (precision 93%)" in text
    assert "and 2 of 30 near-miss titles" in text and "labelled by a reviewer:" in text
    assert "| With a raise in the last year | 1 |" in text
    assert "Not run yet" not in text
