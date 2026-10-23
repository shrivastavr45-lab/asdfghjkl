"""Orchestration, lightweight in-process caching, and API metadata."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from threading import RLock
from typing import Any

from zoneinfo import ZoneInfo

from app.analysis.normalization import analyze_day
from app.services.elexon_client import fetch_day_actuals, fetch_day_forecasts

UK = ZoneInfo("Europe/London")
CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = RLock()


def _cache_get(key: str) -> Any | None:
    import time as clock
    with _cache_lock:
        found = _cache.get(key)
        if not found:
            return None
        expires_at, value = found
        if clock.monotonic() >= expires_at:
            _cache.pop(key, None)
            return None
        return value


def _cache_set(key: str, value: Any) -> None:
    import time as clock
    with _cache_lock:
        _cache[key] = (clock.monotonic() + CACHE_TTL_SECONDS, value)


def _rows_for_date(
    delivery_date: date, refresh: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime]:
    key = f"raw:{delivery_date.isoformat()}"
    if not refresh:
        cached = _cache_get(key)
        if cached is not None:
            return cached
    actuals = fetch_day_actuals(delivery_date)
    forecasts = fetch_day_forecasts(delivery_date)
    retrieved_at = datetime.now(timezone.utc)
    result = (actuals, forecasts, retrieved_at)
    _cache_set(key, result)
    return result


def get_analysis(delivery_date: date, cutoff_clock: time, refresh: bool = False) -> dict[str, Any]:
    actual_rows, forecast_rows, retrieved_at = _rows_for_date(delivery_date, refresh=refresh)
    result = analyze_day(
        delivery_date=delivery_date,
        cutoff_clock=cutoff_clock,
        actual_rows=actual_rows,
        forecast_rows=forecast_rows,
        retrieved_at=retrieved_at,
    )
    result["provenance"]["cache_ttl_seconds"] = CACHE_TTL_SECONDS
    result["provenance"]["cache_bypassed"] = bool(refresh)
    return result


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
