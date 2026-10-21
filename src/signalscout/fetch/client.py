"""The one interface every outside request goes through.

``Fetcher`` has two implementations: ``HttpFetcher`` (real network, polite) and ``FakeFetcher``
(recorded responses, used by every test and by ``--offline``). Collectors only ever call
``get(url)`` and look at ``status``: a 404 from a job board means "no board under that slug", which
is an answer, not an error, so it comes back as a value. Only failures that leave no answer
(retries exhausted, network down) raise ``FetchError``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


class FetchError(Exception):
    """No usable answer: transport failure or server errors after every retry."""


class ConfigError(Exception):
    """A request that must not be sent as configured (e.g. SEC without a contact email)."""


# Returned instead of fetching when robots.txt disallows the path.
BLOCKED_BY_ROBOTS = 0


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    text: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def blocked(self) -> bool:
        return self.status == BLOCKED_BY_ROBOTS

    def json(self) -> Any:
        return json.loads(self.text)


class Fetcher(Protocol):
    def get(self, url: str) -> Response: ...


class FakeFetcher:
    """Serves recorded responses by exact URL; anything unknown is a 404, like a missing board."""

    def __init__(
        self, routes: Mapping[str, Response | str | tuple[int, str]] | None = None
    ) -> None:
        self.routes: dict[str, Response] = {}
        self.calls: list[str] = []
        for url, value in (routes or {}).items():
            self.add(url, value)

    def add(self, url: str, value: Response | str | tuple[int, str]) -> None:
        if isinstance(value, Response):
            self.routes[url] = value
        elif isinstance(value, str):
            self.routes[url] = Response(url, 200, value)
        else:
            status, text = value
            self.routes[url] = Response(url, status, text)

    def get(self, url: str) -> Response:
        self.calls.append(url)
        return self.routes.get(url, Response(url, 404, "Not Found"))
