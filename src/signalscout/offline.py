"""Recorded responses for ``signalscout run --offline``: the README demo and the CI smoke run.

A manifest maps each URL the pipeline will request to a file next to it. Anything not listed is a
404, exactly like a company with no job board, so the demo also exercises the "nothing found"
paths. The recording fixes ``as_of``, because SEC search URLs embed the date window.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from signalscout.fetch import FakeFetcher

DEFAULT_DIR = Path("examples/offline")


def load_offline(directory: Path = DEFAULT_DIR) -> tuple[FakeFetcher, date]:
    manifest = json.loads((directory / "manifest.json").read_text())
    fetcher = FakeFetcher(
        {url: (directory / name).read_text() for url, name in manifest["routes"].items()}
    )
    return fetcher, date.fromisoformat(manifest["as_of"])
