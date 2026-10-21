from __future__ import annotations

from typer.testing import CliRunner

from signalscout import __version__
from signalscout.cli import app

runner = CliRunner()


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_no_args_shows_help() -> None:
    assert "public signals" in runner.invoke(app, []).output
