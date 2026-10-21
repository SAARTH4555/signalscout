from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from signalscout.fetch import (
    ConfigError,
    DiskCache,
    FakeFetcher,
    FetchError,
    HttpFetcher,
    Response,
)
from signalscout.fetch.http import backoff_delay, parse_retry_after
from tests.support import FakeClock, RecordingSleeper

Handler = Callable[[httpx.Request], httpx.Response]


def make(
    handler: Handler,
    *,
    email: str | None = "ops@example.com",
    cache: DiskCache | None = None,
    ttl_s: float = 3600,
) -> tuple[HttpFetcher, FakeClock, RecordingSleeper, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def recording(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    clock = FakeClock()
    sleeper = RecordingSleeper(clock)
    fetcher = HttpFetcher(
        contact_email=email,
        cache=cache,
        ttl_s=ttl_s,
        http=httpx.Client(transport=httpx.MockTransport(recording)),
        clock=clock,
        sleeper=sleeper,
        rng=lambda: 1.0,
    )
    return fetcher, clock, sleeper, seen


ASHBY = "https://api.ashbyhq.com/posting-api/job-board/acme"


def test_fake_fetcher_serves_routes_and_404s_the_rest() -> None:
    fake = FakeFetcher({ASHBY: '{"jobs": []}', "https://x.io/a": (500, "boom")})
    fake.add("https://x.io/b", Response("https://x.io/b", 200, "hi"))
    assert fake.get(ASHBY).json() == {"jobs": []}
    assert fake.get("https://x.io/a").status == 500
    assert fake.get("https://x.io/b").text == "hi"
    missing = fake.get("https://nowhere.io/")
    assert missing.status == 404 and not missing.ok
    assert fake.calls[-1] == "https://nowhere.io/"


def test_user_agent_names_the_tool_and_contact() -> None:
    fetcher, _, _, seen = make(lambda req: httpx.Response(200, json={"jobs": []}))
    assert fetcher.get(ASHBY).ok
    agent = seen[0].headers["User-Agent"]
    assert agent.startswith("SignalScout/") and "ops@example.com" in agent


def test_sec_refuses_to_run_without_a_contact_email() -> None:
    fetcher, _, _, seen = make(lambda req: httpx.Response(200), email=None)
    with pytest.raises(ConfigError, match="contact email"):
        fetcher.get("https://data.sec.gov/submissions/CIK0000000001.json")
    assert seen == []
    assert fetcher.get(ASHBY).ok  # other hosts are fine without one


def test_404_is_an_answer_not_an_error() -> None:
    fetcher, _, _, _ = make(lambda req: httpx.Response(404, text="Not Found"))
    response = fetcher.get(ASHBY)
    assert response.status == 404 and response.text == "Not Found"


def test_same_host_is_paced_other_hosts_are_not() -> None:
    fetcher, _, sleeper, _ = make(lambda req: httpx.Response(200, text="{}"))
    fetcher.get(ASHBY)
    fetcher.get(ASHBY + "?x=1")
    assert sleeper.sleeps == [1.0]
    fetcher.get("https://efts.sec.gov/LATEST/search-index?q=a")
    fetcher.get("https://efts.sec.gov/LATEST/search-index?q=b")
    assert sleeper.sleeps == [1.0, 0.2]


def test_retries_transient_errors_with_backoff_and_retry_after() -> None:
    replies = iter(
        [
            httpx.Response(503),
            httpx.Response(429, headers={"Retry-After": "5"}),
            httpx.Response(200, text="ok"),
        ]
    )
    fetcher, _, sleeper, seen = make(lambda req: next(replies))
    assert fetcher.get(ASHBY).text == "ok"
    assert len(seen) == 3 and fetcher.requests == 3
    assert 1.0 in sleeper.sleeps and 5.0 in sleeper.sleeps


def test_gives_up_after_retries() -> None:
    fetcher, _, _, seen = make(lambda req: httpx.Response(502))
    with pytest.raises(FetchError, match="502"):
        fetcher.get(ASHBY)
    assert len(seen) == 4

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    fetcher, _, _, _ = make(down)
    with pytest.raises(FetchError, match="refused"):
        fetcher.get(ASHBY)


def test_fresh_cache_skips_the_network(tmp_path: Path) -> None:
    fetcher, clock, _, seen = make(
        lambda req: httpx.Response(200, text='{"jobs": [1]}'), cache=DiskCache(tmp_path)
    )
    first = fetcher.get(ASHBY)
    clock.now += 60
    second = fetcher.get(ASHBY)
    assert len(seen) == 1 and not first.from_cache and second.from_cache
    assert second.json() == {"jobs": [1]}


def test_stale_cache_revalidates_with_validators(tmp_path: Path) -> None:
    replies = iter(
        [
            httpx.Response(
                200, text="v1", headers={"ETag": '"abc"', "Last-Modified": "Mon, 1 Jan"}
            ),
            httpx.Response(304),
        ]
    )
    fetcher, clock, _, seen = make(lambda req: next(replies), cache=DiskCache(tmp_path), ttl_s=10)
    fetcher.get(ASHBY)
    clock.now += 11
    again = fetcher.get(ASHBY)
    assert again.text == "v1" and again.from_cache and again.status == 200
    assert seen[1].headers["If-None-Match"] == '"abc"'
    assert seen[1].headers["If-Modified-Since"] == "Mon, 1 Jan"


def test_404s_are_cached_but_server_errors_are_not(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    fetcher, _, _, seen = make(lambda req: httpx.Response(404), cache=cache)
    fetcher.get(ASHBY)
    assert fetcher.get(ASHBY).from_cache and len(seen) == 1
    other = "https://api.lever.co/v0/postings/acme?mode=json"
    replies = iter([httpx.Response(500)] * 4)
    flaky, _, _, _ = make(lambda req: next(replies), cache=cache)
    with pytest.raises(FetchError):
        flaky.get(other)
    assert cache.get(other) is None


def _site(robots: httpx.Response) -> Handler:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return robots
        return httpx.Response(200, text="<html>page</html>")

    return handler


def test_robots_txt_is_honoured_for_company_websites() -> None:
    rules = httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
    fetcher, _, _, seen = make(_site(rules))
    assert fetcher.get("https://acme.io/").ok
    blocked = fetcher.get("https://acme.io/private/page")
    assert blocked.blocked and blocked.status == 0
    assert [r.url.path for r in seen].count("/robots.txt") == 1  # parsed once per host


@pytest.mark.parametrize(
    ("robots", "allowed"),
    [
        (httpx.Response(404), True),
        (httpx.Response(403), False),
        (httpx.Response(500), False),
    ],
)
def test_robots_txt_edge_cases(robots: httpx.Response, allowed: bool) -> None:
    fetcher, _, _, _ = make(_site(robots))
    assert fetcher.get("https://acme.io/").ok is allowed


def test_api_hosts_skip_robots() -> None:
    fetcher, _, _, seen = make(lambda req: httpx.Response(200, text="{}"))
    fetcher.get(ASHBY)
    assert all(r.url.path != "/robots.txt" for r in seen)


def test_backoff_and_retry_after_helpers() -> None:
    assert [backoff_delay(a, rng=lambda: 1.0, cap=4.0) for a in range(4)] == [1.0, 2.0, 4.0, 4.0]
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after("soon") is None
    assert parse_retry_after("600") is None
    assert parse_retry_after(None) is None


def test_settings_read_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from signalscout.settings import Settings

    monkeypatch.setenv("SIGNALSCOUT_CONTACT_EMAIL", "ops@example.com")
    monkeypatch.setenv("SIGNALSCOUT_CACHE_TTL_HOURS", "2")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.contact_email == "ops@example.com" and settings.cache_ttl_hours == 2.0
