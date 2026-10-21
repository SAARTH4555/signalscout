from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from signalscout.accounts import Account, merge_accounts
from signalscout.fetch import FakeFetcher, FetchError
from signalscout.seeds import YC_URL, YcFilter, csv_accounts, fetch_yc, yc_accounts

FIXTURE = Path(__file__).parent / "fixtures" / "yc_sample.json"


def sample() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(FIXTURE.read_text())
    return data


def test_yc_filter_keeps_us_b2b_active_in_band_and_counts_drops() -> None:
    accounts, report = yc_accounts(sample())
    assert [a.company_key for a in accounts] == [
        "ledgerline.io",
        "orbitstack.dev",
        "harborview.com",
    ]
    assert report.loaded == 10 and report.kept == 3
    assert report.dropped == {
        "no website": 1,
        "not B2B": 1,
        "not US": 1,
        "not active": 2,
        "team size out of band": 1,
        "team size unknown": 1,
    }
    ledgerline = accounts[0]
    assert ledgerline.name == "Ledgerline"  # legal form stripped
    assert ledgerline.sources == ("yc",) and ledgerline.yc_slug == "ledgerline"
    assert ledgerline.team_size == 120 and ledgerline.yc_hiring is True
    # US detected from the location string when regions is empty
    assert accounts[2].location == "Remote; Miami, FL, USA"


def test_yc_filter_is_configurable() -> None:
    wide, _ = yc_accounts(sample(), YcFilter(min_team=10, max_team=5000, us_only=False))
    keys = {a.company_key for a in wide}
    assert {"tinytools.ai", "bergwerk.de"} <= keys
    assert "megacorp.com" not in keys  # still not Active


def test_fetch_yc_uses_the_fetcher() -> None:
    fake = FakeFetcher({YC_URL: FIXTURE.read_text()})
    assert len(fetch_yc(fake)) == 10
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch_yc(FakeFetcher())


def test_csv_seeds(tmp_path: Path) -> None:
    path = tmp_path / "seeds.csv"
    path.write_text(
        "name,domain,notes\n"
        "Ledgerline Inc,https://ledgerline.io/about,warm intro\n"
        "Fieldnote,fieldnote.app,\n"
        "Broken,,\n"
    )
    accounts = csv_accounts(path)
    assert [(a.company_key, a.name, a.sources) for a in accounts] == [
        ("ledgerline.io", "Ledgerline", ("seed",)),
        ("fieldnote.app", "Fieldnote", ("seed",)),
    ]


def test_merge_keeps_richer_fields_and_unions_sources() -> None:
    yc = Account("acme.io", "Acme", "acme.io", sources=("yc",), team_size=80, yc_slug="acme")
    seed = Account("acme.io", "ACME Corp", "acme.io", sources=("seed",), location="NYC")
    other = Account("beta.dev", "Beta", "beta.dev", sources=("seed",))
    merged = merge_accounts([seed, other, yc])
    assert [a.company_key for a in merged] == ["acme.io", "beta.dev"]
    acme = merged[0]
    assert acme.name == "ACME Corp"  # first seen wins
    assert acme.sources == ("seed", "yc")
    assert (acme.team_size, acme.yc_slug, acme.location) == (80, "acme", "NYC")
