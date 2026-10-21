"""On-disk HTTP cache: one JSON file per URL, with the validators needed for conditional requests.

A run over a few hundred companies makes over a thousand requests. Caching them means a re-run
after changing a scoring rule costs nothing, and the sources are not hit again for data that has
not changed. Expired entries are not thrown away: their ETag / Last-Modified make the next request
conditional, so an unchanged board answers 304 with no body.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from signalscout.fetch.client import Response

KEPT_HEADERS = ("etag", "last-modified", "content-type")


@dataclass(frozen=True)
class Entry:
    response: Response
    fetched_at: float

    def fresh(self, now: float, ttl_s: float) -> bool:
        return now - self.fetched_at < ttl_s


class DiskCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()
        return self.root / digest[:2] / f"{digest}.json"

    def get(self, url: str) -> Entry | None:
        path = self._path(url)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        response = Response(
            url=data["url"], status=data["status"], text=data["text"], headers=data["headers"]
        )
        return Entry(response, float(data["fetched_at"]))

    def put(self, response: Response, fetched_at: float) -> None:
        path = self._path(response.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        headers = {k: v for k, v in response.headers.items() if k in KEPT_HEADERS}
        payload = {
            "url": response.url,
            "status": response.status,
            "text": response.text,
            "headers": headers,
            "fetched_at": fetched_at,
        }
        path.write_text(json.dumps(payload))
