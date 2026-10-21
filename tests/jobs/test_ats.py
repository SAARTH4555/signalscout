from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from signalscout.fetch import FakeFetcher, Response
from signalscout.jobs.ats import board_url, fetch_board, html_to_text, parse_board

BOARDS = Path(__file__).resolve().parents[1] / "fixtures" / "boards"


def load(name: str) -> str:
    return (BOARDS / name).read_text()


def test_board_urls() -> None:
    assert board_url("ashby", "acme").endswith("/job-board/acme?includeCompensation=true")
    assert board_url("greenhouse", "acme") == (
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    )
    assert board_url("lever", "acme") == "https://api.lever.co/v0/postings/acme?mode=json"


def test_ashby_skips_unlisted_and_trims_titles() -> None:
    url = board_url("ashby", "ledgerline")
    board = parse_board("ashby", "ledgerline", Response(url, 200, load("ashby_ledgerline.json")))
    assert [j.title for j in board.jobs] == [
        "Revenue Operations Manager",
        "Senior Account Executive",
    ]
    first = board.jobs[0]
    assert first.posted_at == datetime(2026, 10, 2, 15, 0, tzinfo=UTC)
    assert first.posted_field == "publishedAt" and first.remote is False
    assert "Salesforce CPQ" in first.description
    assert board.jobs[1].remote is True and board.company_name is None


def test_greenhouse_unescapes_html_and_falls_back_to_updated_at() -> None:
    url = board_url("greenhouse", "orbitstack")
    board = parse_board(
        "greenhouse", "orbitstack", Response(url, 200, load("greenhouse_orbitstack.json"))
    )
    assert board.company_name == "Orbitstack"
    admin, engineer = board.jobs
    assert (
        admin.description
        == "Orbitstack runs on HubSpot . You will own lifecycle stages, lead scoring & workflows."
    )
    assert admin.posted_field == "first_published" and admin.remote is True
    assert admin.posted_at == datetime(2026, 9, 20, 13, 0, tzinfo=UTC)
    assert admin.department == "Marketing"
    assert engineer.posted_field == "updated_at" and engineer.remote is None
    assert engineer.department == ""


def test_lever_epoch_millis_and_list_text() -> None:
    url = board_url("lever", "harborview")
    board = parse_board("lever", "harborview", Response(url, 200, load("lever_harborview.json")))
    (job,) = board.jobs
    assert job.title == "GTM Engineer" and job.remote is True
    assert job.posted_at == datetime.fromtimestamp(1790000000, UTC)
    assert "Build enrichment in Clay" in job.description and "HubSpot" in job.description
    assert job.department == "Revenue"


def test_fetch_board_semantics() -> None:
    url = board_url("lever", "quiet")
    fake = FakeFetcher(
        {url: "[]", board_url("ashby", "weird"): "not json", board_url("ashby", "down"): (503, "")}
    )
    empty = fetch_board(fake, "lever", "quiet")
    assert empty is not None and empty.jobs == ()  # board exists, not hiring
    assert fetch_board(fake, "greenhouse", "nobody") is None  # 404: no board
    assert fetch_board(fake, "ashby", "weird") is None
    assert fetch_board(fake, "ashby", "down") is None


def test_html_to_text() -> None:
    assert html_to_text("&lt;p&gt;A &amp;amp; B&lt;/p&gt;") == "A & B"
    assert html_to_text("<li>x</li><li>y</li>") == "x y"
    assert json.loads(load("lever_harborview.json"))[0]["text"] == "GTM Engineer"
