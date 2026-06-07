"""Application factory utilities."""

from __future__ import annotations

from functools import lru_cache

from .config import Settings
from .service import CiderAgentService


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings.from_env()
    settings.ensure_storage_parent()
    return settings


@lru_cache(maxsize=1)
def get_service() -> CiderAgentService:
    service = CiderAgentService(get_settings())
    service.start_background_session_worker()
    return service
