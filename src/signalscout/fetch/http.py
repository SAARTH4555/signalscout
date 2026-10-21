"""``Fetcher`` over the network, with the manners these sources expect.

- **Pace per host.** The job-board APIs publish no limits and Lever's robots.txt asks for one
  second between requests, so every host gets a minimum gap: 1 s by default, 0.2 s for SEC
  (5 requests/s, half its published 10/s cap).
- **Identify.** SEC refuses anonymous clients (403 without a User-Agent) and asks for a contact
  email in it, so SEC requests are refused locally until one is configured.
- **robots.txt for company websites.** The job-board and SEC endpoints are documented public
  APIs; company websites are not, so their robots.txt is checked before fetching a page.
- **Cache, then revalidate.** Fresh cache entries are served without a request; stale ones are
  revalidated with If-None-Match / If-Modified-Since.
- **Retry what is transient.** 429, 5xx and transport errors back off with full jitter, honouring
  a sensible Retry-After. 404 and other 4xx are answers and come back as values.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from signalscout import __version__
from signalscout.fetch.cache import DiskCache
from signalscout.fetch.client import BLOCKED_BY_ROBOTS, ConfigError, FetchError, Response

Clock = Callable[[], float]
Sleeper = Callable[[float], None]
Rng = Callable[[], float]

# Seconds between requests to one host. Anything not listed is a company website: 1 s and robots.
MIN_INTERVAL_S: dict[str, float] = {
    "api.ashbyhq.com": 1.0,
    "boards-api.greenhouse.io": 1.0,
    "api.lever.co": 1.0,
    "efts.sec.gov": 0.2,
    "data.sec.gov": 0.2,
    "www.sec.gov": 0.2,
    "yc-oss.github.io": 0.5,
}
API_HOSTS = frozenset(MIN_INTERVAL_S)
DEFAULT_INTERVAL_S = 1.0
RETRYABLE = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_S = 60.0


def is_sec(host: str) -> bool:
    return host == "sec.gov" or host.endswith(".sec.gov")


def backoff_delay(attempt: int, *, rng: Rng, base: float = 1.0, cap: float = 30.0) -> float:
    """Full jitter: uniform in [0, min(cap, base * 2**attempt)]."""
    return min(cap, base * (2.0**attempt)) * rng()


def parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if 0 <= seconds <= MAX_RETRY_AFTER_S else None


class HostLimiter:
    """Enforces a minimum gap between consecutive requests to the same host."""

    def __init__(self, *, clock: Clock, sleeper: Sleeper) -> None:
        self._clock = clock
        self._sleep = sleeper
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        gap = MIN_INTERVAL_S.get(host, DEFAULT_INTERVAL_S)
        last = self._last.get(host)
        if last is not None:
            remaining = gap - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last[host] = self._clock()


class HttpFetcher:
    def __init__(
        self,
        *,
        contact_email: str | None,
        cache: DiskCache | None = None,
        ttl_s: float = 24 * 3600,
        http: httpx.Client | None = None,
        clock: Clock = time.time,
        sleeper: Sleeper = time.sleep,
        rng: Rng = random.random,
        max_retries: int = 3,
    ) -> None:
        self._email = contact_email
        agent = f"SignalScout/{__version__} (account research"
        agent += f"; {contact_email})" if contact_email else ")"
        self._headers = {"User-Agent": agent}
        self._http = http or httpx.Client(timeout=20.0, follow_redirects=True)
        self._cache = cache
        self._ttl_s = ttl_s
        self._clock = clock
        self._sleep = sleeper
        self._rng = rng
        self._max_retries = max_retries
        self._limiter = HostLimiter(clock=clock, sleeper=sleeper)
        self._robots: dict[str, RobotFileParser] = {}
        self.requests = 0  # network requests actually sent, for the run report

    def get(self, url: str) -> Response:
        host = urlsplit(url).hostname or ""
        if is_sec(host) and not self._email:
            raise ConfigError("SEC requires a contact email: set SIGNALSCOUT_CONTACT_EMAIL")
        if host not in API_HOSTS and not self._allowed(url, host):
            return Response(url, BLOCKED_BY_ROBOTS, "blocked by robots.txt")
        return self._cached_get(url, host)

    def _cached_get(self, url: str, host: str) -> Response:
        entry = self._cache.get(url) if self._cache else None
        now = self._clock()
        if entry is not None and entry.fresh(now, self._ttl_s):
            r = entry.response
            return Response(r.url, r.status, r.text, r.headers, from_cache=True)
        conditional: dict[str, str] = {}
        if entry is not None:
            if "etag" in entry.response.headers:
                conditional["If-None-Match"] = entry.response.headers["etag"]
            if "last-modified" in entry.response.headers:
                conditional["If-Modified-Since"] = entry.response.headers["last-modified"]
        response = self._send(url, host, conditional)
        if response.status == 304 and entry is not None:
            response = Response(
                url,
                entry.response.status,
                entry.response.text,
                entry.response.headers,
                from_cache=True,
            )
        if self._cache is not None and response.status < 500 and response.status != 429:
            self._cache.put(response, self._clock())
        return response

    def _send(self, url: str, host: str, extra: dict[str, str]) -> Response:
        headers = {**self._headers, **extra}
        for attempt in range(self._max_retries + 1):
            last = attempt == self._max_retries
            self._limiter.wait(host)
            self.requests += 1
            try:
                raw = self._http.get(url, headers=headers)
            except httpx.TransportError as exc:
                if last:
                    raise FetchError(f"{url}: {exc}") from exc
                self._sleep(backoff_delay(attempt, rng=self._rng))
                continue
            if raw.status_code in RETRYABLE:
                if last:
                    raise FetchError(f"{url}: HTTP {raw.status_code} after retries")
                delay = parse_retry_after(raw.headers.get("retry-after"))
                self._sleep(delay if delay is not None else backoff_delay(attempt, rng=self._rng))
                continue
            return Response(
                url, raw.status_code, raw.text, {k.lower(): v for k, v in raw.headers.items()}
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def _allowed(self, url: str, host: str) -> bool:
        parser = self._robots.get(host)
        if parser is None:
            parts = urlsplit(url)
            robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
            parser = RobotFileParser()
            try:
                robots = self._cached_get(robots_url, host)
            except FetchError:
                # RFC 9309: if robots.txt is unreachable because of server errors, assume
                # everything is disallowed.
                robots = Response(robots_url, 503)
            if robots.status in (401, 403) or robots.status >= 500:
                parser.parse(["User-agent: *", "Disallow: /"])
            elif robots.ok:
                parser.parse(robots.text.splitlines())
            else:
                parser.parse([])  # no robots.txt: nothing is disallowed
            self._robots[host] = parser
        return parser.can_fetch(self._headers["User-Agent"], url)
