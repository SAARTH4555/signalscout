"""All outside requests: one Protocol, a polite cached HTTP implementation, and a fake."""

from __future__ import annotations

from signalscout.fetch.cache import DiskCache
from signalscout.fetch.client import (
    BLOCKED_BY_ROBOTS,
    ConfigError,
    FakeFetcher,
    Fetcher,
    FetchError,
    Response,
)
from signalscout.fetch.http import HttpFetcher

__all__ = [
    "BLOCKED_BY_ROBOTS",
    "ConfigError",
    "DiskCache",
    "FakeFetcher",
    "FetchError",
    "Fetcher",
    "HttpFetcher",
    "Response",
]
