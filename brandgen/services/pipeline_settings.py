"""Load pipeline toggles from the database (admin-configurable)."""

from __future__ import annotations

from django.core.cache import cache

from brandgen.models import PipelineSettings

_CACHE_KEY = "brandgen_pipeline_settings"
_CACHE_TTL = 60


def get_pipeline_settings() -> PipelineSettings:
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    settings = PipelineSettings.load()
    cache.set(_CACHE_KEY, settings, _CACHE_TTL)
    return settings


def is_ocr_enabled() -> bool:
    return get_pipeline_settings().ocr_enabled


def clear_pipeline_settings_cache() -> None:
    cache.delete(_CACHE_KEY)
