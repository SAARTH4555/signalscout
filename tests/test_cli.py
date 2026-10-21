from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from signalscout import __version__
from signalscout.cli import app
from signalscout.fetch import FetchError
from signalscout.seeds import US
from signalscout.settings import get_settings

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_no_args_shows_help() -> None:
    assert "public signals" in runner.invoke(app, []).output


def test_run_offline_writes_outputs_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    report = tmp_path / "run.json"
    result = runner.invoke(
        app, ["run", "--offline", "--out", str(tmp_path / "out"), "--report", str(report)]
    )
    assert result.exit_code == 0, result.output
    assert "Tier A 1, Tier B 2, Tier C 0" in result.stdout
    assert "Ledgerline (ledgerline.example): Tier A" in result.stdout
    assert (tmp_path / "out" / "tier_a.csv").exists()
    assert '"mode": "offline"' in report.read_text()


def test_run_offline_with_seed_csv_and_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    seeds = tmp_path / "seeds.csv"
    seeds.write_text("name,domain\nNew Co,newco.example\n")
    result = runner.invoke(
        app,
        [
            "run",
            "--offline",
            "--no-yc",
            "--seed-csv",
            str(seeds),
            "--no-funding",
            "--no-crm",
            "--as-of",
            "2026-10-15",
            "--out",
            str(tmp_path / "out"),
            "--limit",
            "5",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "newco.example" in result.stdout and "Tier C" in result.stdout


def test_run_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    none = runner.invoke(
        app,
        ["run", "--offline", "--min-team", "9000", "--max-team", "9999", "--out", str(tmp_path)],
    )
    assert none.exit_code == 1 and "no accounts" in none.output

    monkeypatch.delenv("SIGNALSCOUT_CONTACT_EMAIL", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(
        "signalscout.cli.fetch_yc",
        lambda fetcher: [
            {
                "name": "A",
                "website": "a.io",
                "status": "Active",
                "industries": ["B2B"],
                "regions": [US],
                "team_size": 100,
            }
        ],
    )
    monkeypatch.chdir(tmp_path)  # no .env here
    live = runner.invoke(
        app,
        ["run", "--scoring", str(ROOT / "config" / "scoring.yaml"), "--out", str(tmp_path / "o")],
    )
    assert live.exit_code == 1 and "contact email" in live.output
    get_settings.cache_clear()


def test_run_live_yc_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(fetcher: object) -> list[dict[str, object]]:
        raise FetchError("YC directory: HTTP 503")

    monkeypatch.setattr("signalscout.cli.fetch_yc", boom)
    result = runner.invoke(app, ["run", "--out", str(tmp_path)])
    assert result.exit_code == 1 and "HTTP 503" in result.output


def test_clay_spec_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    ok = runner.invoke(app, ["clay-spec", "--check"])
    assert ok.exit_code == 0, ok.output
    assert "5 accounts / month on Clay Free" in ok.stdout
    out = tmp_path / "guide.md"
    assert runner.invoke(app, ["clay-spec", "--out", str(out)]).exit_code == 0
    out.write_text(out.read_text() + "drift\n")
    stale = runner.invoke(app, ["clay-spec", "--out", str(out), "--check"])
    assert stale.exit_code == 1 and "stale" in stale.output
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 2\n")
    broken = runner.invoke(app, ["clay-spec", "--spec", str(bad), "--out", str(out)])
    assert broken.exit_code == 1 and "error" in broken.output
