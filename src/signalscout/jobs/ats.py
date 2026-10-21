"""Public job-board APIs (Ashby, Greenhouse, Lever) parsed into one ``Job`` shape.

All three vendors document these endpoints as public, for companies building their own careers
pages; none needs a key. They answer 404 when no board exists under a slug, so ``fetch_board``
returns ``None`` for "no board" and a ``Board`` (possibly with zero jobs) when one exists.

The three disagree on what a posting date means, so each ``Job`` keeps the source field name:
Ashby's ``publishedAt`` resets when a job is republished, Greenhouse's ``first_published`` is the
true first date, Lever's ``createdAt`` (epoch milliseconds) is when the posting was created.
SmartRecruiters is left out on purpose: it answers 200 with zero jobs for any made-up slug, so
"no board" and "not hiring" cannot be told apart.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from signalscout.fetch import Fetcher, Response

Ats = Literal["ashby", "greenhouse", "lever"]
ATS_ORDER: tuple[Ats, ...] = ("ashby", "greenhouse", "lever")


@dataclass(frozen=True)
class Job:
    ats: Ats
    board: str
    title: str
    url: str
    posted_at: datetime | None
    posted_field: str
    location: str
    remote: bool | None
    department: str
    description: str


@dataclass(frozen=True)
class Board:
    ats: Ats
    slug: str
    company_name: str | None  # only Greenhouse says whose board it is
    jobs: tuple[Job, ...]


def board_url(ats: Ats, slug: str) -> str:
    if ats == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    if ats == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    return f"https://api.lever.co/v0/postings/{slug}?mode=json"


_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(raw: str) -> str:
    """Greenhouse escapes its HTML (``&lt;p&gt;``), so unescape twice around the tag strip."""
    text = html.unescape(raw)
    text = _TAG_RE.sub(" ", text)
    return " ".join(html.unescape(text).split())


def _iso(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def parse_ashby(data: dict[str, Any], slug: str) -> Board:
    jobs = tuple(
        Job(
            ats="ashby",
            board=slug,
            title=" ".join(str(j.get("title", "")).split()),
            url=str(j.get("jobUrl", "")),
            posted_at=_iso(j.get("publishedAt")),
            posted_field="publishedAt",
            location=str(j.get("location", "")),
            remote=bool(j.get("isRemote")) or j.get("workplaceType") == "Remote",
            department=str(j.get("department", "")),
            description=" ".join(str(j.get("descriptionPlain", "")).split()),
        )
        for j in data.get("jobs", [])
        if j.get("isListed", True)  # unlisted postings are not public openings
    )
    return Board("ashby", slug, None, jobs)


def parse_greenhouse(data: dict[str, Any], slug: str) -> Board:
    jobs: list[Job] = []
    company: str | None = None
    for j in data.get("jobs", []):
        company = company or j.get("company_name")
        first = j.get("first_published")
        workplace = next(
            (m.get("value") for m in j.get("metadata") or [] if m.get("name") == "Workplace Type"),
            None,
        )
        departments = j.get("departments") or []
        jobs.append(
            Job(
                ats="greenhouse",
                board=slug,
                title=" ".join(str(j.get("title", "")).split()),
                url=str(j.get("absolute_url", "")),
                posted_at=_iso(first or j.get("updated_at")),
                posted_field="first_published" if first else "updated_at",
                location=str((j.get("location") or {}).get("name", "")),
                remote=None if workplace is None else str(workplace).lower() == "remote",
                department=str(departments[0].get("name", "")) if departments else "",
                description=html_to_text(str(j.get("content", ""))),
            )
        )
    return Board("greenhouse", slug, company, tuple(jobs))


def parse_lever(data: list[dict[str, Any]], slug: str) -> Board:
    jobs: list[Job] = []
    for j in data:
        categories = j.get("categories") or {}
        parts = [j.get("descriptionPlain", ""), j.get("additionalPlain", "")]
        parts += [
            f"{x.get('text', '')} {html_to_text(str(x.get('content', '')))}"
            for x in j.get("lists") or []
        ]
        created = j.get("createdAt")
        jobs.append(
            Job(
                ats="lever",
                board=slug,
                title=" ".join(str(j.get("text", "")).split()),
                url=str(j.get("hostedUrl", "")),
                posted_at=datetime.fromtimestamp(created / 1000, UTC) if created else None,
                posted_field="createdAt",
                location=str(categories.get("location", "")),
                remote=str(j.get("workplaceType", "")).lower() == "remote",
                department=str(categories.get("department") or categories.get("team") or ""),
                description=" ".join(" ".join(str(p) for p in parts if p).split()),
            )
        )
    return Board("lever", slug, None, tuple(jobs))


def parse_board(ats: Ats, slug: str, response: Response) -> Board:
    data = response.json()
    if ats == "ashby":
        return parse_ashby(data, slug)
    if ats == "greenhouse":
        return parse_greenhouse(data, slug)
    return parse_lever(data, slug)


def fetch_board(fetcher: Fetcher, ats: Ats, slug: str) -> Board | None:
    """``None`` when there is no board under this slug; a ``Board`` (maybe empty) otherwise."""
    response = fetcher.get(board_url(ats, slug))
    if response.status == 404 or not response.ok:
        return None
    try:
        return parse_board(ats, slug, response)
    except (ValueError, AttributeError, TypeError):
        return None  # not the JSON we expect: treat as no usable board
