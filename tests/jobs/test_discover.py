from __future__ import annotations

from pathlib import Path

from signalscout.accounts import Account
from signalscout.fetch import FakeFetcher, FetchError, Response
from signalscout.jobs.ats import Board, Job, board_url
from signalscout.jobs.discover import (
    belongs_to,
    by_guessing,
    find_board,
    links_on_page,
    slug_candidates,
)

BOARDS = Path(__file__).resolve().parents[1] / "fixtures" / "boards"


def load(name: str) -> str:
    return (BOARDS / name).read_text()


LEDGERLINE = Account(
    "ledgerline.example", "Ledgerline", "ledgerline.example", yc_slug="ledgerline-demo"
)
ORBITSTACK = Account(
    "orbitstack.example", "Orbitstack", "orbitstack.example", yc_slug="orbitstack-demo"
)


def test_links_on_page_finds_every_vendor_once() -> None:
    page = """
      <a href="https://jobs.ashbyhq.com/Acme">jobs</a>
      <script src="https://jobs.ashbyhq.com/acme/embed?version=2"></script>
      <iframe src="https://boards.greenhouse.io/embed/job_board?for=acme-inc"></iframe>
      <a href="https://job-boards.greenhouse.io/acmeco/jobs/1">x</a>
      <a href="https://boards-api.greenhouse.io/v1/boards/acmeapi/jobs">api</a>
      <a href="https://jobs.lever.co/acme-labs/123">lever</a>
      <a href="https://jobs.eu.lever.co/acme-eu">eu</a>
    """
    assert links_on_page(page) == [
        ("ashby", "acme"),
        ("greenhouse", "acmeapi"),
        ("greenhouse", "acme-inc"),
        ("greenhouse", "acmeco"),
        ("lever", "acme-labs"),
        ("lever", "acme-eu"),
    ]
    assert links_on_page(load("careers_none.html")) == []


def test_slug_candidates() -> None:
    account = Account("getmeridian.com", "Meridian Health", "getmeridian.com", yc_slug="meridian")
    assert slug_candidates(account) == ["meridian", "getmeridian", "meridianhealth"]
    assert slug_candidates(Account("acme.io", "Acme", "acme.io")) == ["acme"]


def test_careers_page_link_wins() -> None:
    fake = FakeFetcher(
        {
            "https://ledgerline.example/careers": load("careers_ledgerline.html"),
            board_url("ashby", "ledgerline-demo"): load("ashby_ledgerline.json"),
        }
    )
    match = find_board(fake, LEDGERLINE)
    assert match is not None and match.via == "careers_page" and match.verified
    assert match.board.ats == "ashby" and len(match.board.jobs) == 2


def test_careers_page_errors_fall_through_to_guessing() -> None:
    class Flaky(FakeFetcher):
        def get(self, url: str) -> Response:
            if "/careers" in url:
                raise FetchError("down")
            return super().get(url)

    fake = Flaky({board_url("greenhouse", "orbitstack-demo"): load("greenhouse_orbitstack.json")})
    match = find_board(fake, ORBITSTACK)
    assert match is not None and match.via == "guess" and match.verified
    assert match.board.company_name == "Orbitstack"


def test_guess_on_someone_elses_board_is_rejected() -> None:
    impostor = Account(
        "orbitstack.ai", "Orbit Stack AI Robotics", "orbitstack.ai", yc_slug="orbitstack-demo"
    )
    fake = FakeFetcher(
        {board_url("greenhouse", "orbitstack-demo"): load("greenhouse_orbitstack.json")}
    )
    assert find_board(fake, impostor) is None


def test_empty_board_is_kept_only_as_unverified() -> None:
    fake = FakeFetcher({board_url("lever", "ledgerline-demo"): "[]"})
    match = by_guessing(fake, LEDGERLINE)
    assert match is not None and not match.verified and match.board.jobs == ()


def _board(description: str, url: str = "https://jobs.lever.co/arc/1") -> Board:
    job = Job("lever", "arc", "Role", url, None, "createdAt", "", None, "", description)
    return Board("lever", "arc", None, (job,))


def test_belongs_to_uses_descriptions_not_urls() -> None:
    arc = Account("arc.dev", "Arc", "arc.dev")
    assert not belongs_to(_board("We build search for research teams."), arc)  # no "arc" word
    assert belongs_to(_board("At Arc we ship fast."), arc)
    assert belongs_to(_board("Visit arc.dev for more."), arc)
    harbor = Account("harborview.example", "Harborview", "harborview.example")
    assert belongs_to(_board("Harbor View is hiring"), harbor)  # squashed match
    assert not belongs_to(
        _board("nothing here", url="https://jobs.lever.co/harborview-demo/1"), harbor
    )
