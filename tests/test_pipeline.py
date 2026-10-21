from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from signalscout.accounts import Account
from signalscout.export import (
    CLAY_FREE_ROWS,
    PIPELINEOS_COMPANY_FIELDS,
    PIPELINEOS_CONTACT_FIELDS,
    SIGNAL_FIELDS,
    write_outputs,
)
from signalscout.fetch import ConfigError, FakeFetcher, FetchError, Response
from signalscout.offline import load_offline
from signalscout.pipeline import CountingFetcher, RunOptions, collect, run
from signalscout.score import ScoredAccount, load_scoring
from signalscout.seeds import fetch_yc, yc_accounts

ROOT = Path(__file__).resolve().parents[1]
SCORING = load_scoring(ROOT / "config" / "scoring.yaml")


def offline_run() -> tuple[list[ScoredAccount], dict[str, object], date]:
    fetcher, as_of = load_offline(ROOT / "examples" / "offline")
    accounts, _ = yc_accounts(fetch_yc(fetcher))
    result = run(fetcher, accounts, SCORING, RunOptions(as_of=as_of), contact_email="x@y.z")
    return result.scored, result.summary(), as_of


def test_offline_world_end_to_end() -> None:
    scored, summary, _ = offline_run()
    assert [(s.signals.account.company_key, s.tier) for s in scored] == [
        ("ledgerline.example", "A"),
        ("harborview.example", "B"),
        ("orbitstack.example", "B"),
    ]
    assert summary["tiers"] == {"A": 1, "B": 2, "C": 0}
    assert summary["boards_by_ats"] == {"ashby": 1, "greenhouse": 1, "lever": 1}
    assert summary["boards_found_via"] == {"careers_page": 1, "guess": 2}
    assert summary["with_recent_funding"] == 1
    assert summary["crm_identified_by_confidence"] == {"high": 3}
    assert summary["accounts_with_errors"] == 0
    fetches = summary["fetches"]
    assert isinstance(fetches, dict) and fetches["requests"] > 0


def test_progress_callback_and_sorting() -> None:
    fetcher, as_of = load_offline(ROOT / "examples" / "offline")
    accounts, _ = yc_accounts(fetch_yc(fetcher))
    seen: list[tuple[int, int]] = []
    result = run(
        fetcher,
        accounts,
        SCORING,
        RunOptions(as_of=as_of, with_funding=False, with_crm=False),
        contact_email=None,
        progress=lambda i, n, s: seen.append((i, n)),
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]
    scores = [s.score for s in result.scored]
    assert scores == sorted(scores, reverse=True)
    assert all(s.signals.funding is None and s.signals.site is None for s in result.scored)


def test_funding_without_contact_email_is_refused_up_front() -> None:
    with pytest.raises(ConfigError, match="contact email"):
        run(
            FakeFetcher(),
            [Account("a.io", "A", "a.io")],
            SCORING,
            RunOptions(as_of=date(2026, 10, 1)),
            contact_email=None,
        )


def test_one_broken_source_costs_a_signal_not_the_account() -> None:
    class Broken(FakeFetcher):
        def get(self, url: str) -> Response:
            raise FetchError(f"boom {url[:20]}")

    signals = collect(Broken(), Account("a.io", "A", "a.io"), RunOptions(as_of=date(2026, 10, 1)))
    assert len(signals.errors) == 3
    assert {e.split(":")[0] for e in signals.errors} == {"job board", "funding", "website"}
    assert signals.crm is not None and signals.crm.crm is None


def test_counting_fetcher() -> None:
    class Mixed(FakeFetcher):
        def get(self, url: str) -> Response:
            if url.endswith("/fail"):
                raise FetchError("x")
            if url.endswith("/robots"):
                return Response(url, 0)
            return Response(url, 200, "", from_cache=url.endswith("/cached"))

    counting = CountingFetcher(Mixed())
    for url in ("https://a/ok", "https://a/cached", "https://a/robots"):
        counting.get(url)
    with pytest.raises(FetchError):
        counting.get("https://a/fail")
    assert counting.counts == {"requests": 3, "from_cache": 1, "blocked_by_robots": 1, "failed": 1}


def read(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def test_outputs(tmp_path: Path) -> None:
    scored, _, as_of = offline_run()
    written = write_outputs(scored, tmp_path, as_of, hubspot_tiers="AB")
    assert written == {
        "accounts.csv": 3,
        "tier_a.csv": 1,
        "pipelineos/companies.csv": 3,
        "pipelineos/contacts.csv": 0,
    }
    accounts = read(tmp_path / "accounts.csv")
    assert accounts[0]["best_role"] == "Revenue Operations Manager"
    assert accounts[0]["job_board"] == "ashby:ledgerline-demo" and accounts[0]["stage_guess"]
    clay = read(tmp_path / "tier_a.csv")
    assert clay[0]["why_now"].startswith("120 people")
    header = (tmp_path / "pipelineos" / "companies.csv").read_text().splitlines()[0].split(",")
    assert tuple(header) == PIPELINEOS_COMPANY_FIELDS + SIGNAL_FIELDS
    contacts = (tmp_path / "pipelineos" / "contacts.csv").read_text().strip().split(",")
    assert tuple(contacts) == PIPELINEOS_CONTACT_FIELDS
    handoff = read(tmp_path / "pipelineos" / "companies.csv")
    assert (
        handoff[0]["numberofemployees"] == "120"
        and handoff[0]["signal_checked_at"] == as_of.isoformat()
    )


def test_clay_file_is_capped_at_the_free_plan_table_size(tmp_path: Path) -> None:
    scored, _, as_of = offline_run()
    many = [scored[0]] * (CLAY_FREE_ROWS + 25)
    written = write_outputs(many, tmp_path, as_of)
    assert written["tier_a.csv"] == CLAY_FREE_ROWS
    assert written["accounts.csv"] == CLAY_FREE_ROWS + 25
