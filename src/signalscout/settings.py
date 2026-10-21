"""Runtime settings, read from ``SIGNALSCOUT_*`` environment variables (or a local ``.env``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGNALSCOUT_", env_file=".env", extra="ignore")

    # SEC's fair-access policy requires every client to identify itself with a contact email.
    contact_email: str | None = None
    cache_dir: Path = Path(".cache/http")
    cache_ttl_hours: float = 24.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
