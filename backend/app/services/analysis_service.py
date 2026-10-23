"""Orchestration, multi-tier caching (memory + SQLite persistent), and month-level analytics."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from threading import RLock
from typing import Any
from zoneinfo import ZoneInfo

from app.analysis.metrics import (
    calculate_metrics,
    calculate_risk_buffer,
    calculate_wind_regimes,
)
from app.analysis.normalization import analyze_day
from app.services.elexon_client import fetch_day_actuals, fetch_day_forecasts
from app.services.persistent_cache import (
    clear_persistent_cache,
    get_cached_day_rows,
    store_cached_day_rows,
)

logger = logging.getLogger(__name__)
UK = ZoneInfo("Europe/London")
CACHE_TTL_SECONDS = 300
_mem_cache: dict[str, tuple[float, Any, str]] = {}
_cache_lock = RLock()


def _mem_cache_get(key: str) -> tuple[Any, str] | None:
    import time as clock
    with _cache_lock:
        found = _mem_cache.get(key)
        if not found:
            return None
        expires_at, value, cache_tier = found
        if clock.monotonic() >= expires_at:
            _mem_cache.pop(key, None)
            return None
        return value, cache_tier


def _mem_cache_set(key: str, value: Any, tier: str = "memory") -> None:
    import time as clock
    with _cache_lock:
        _mem_cache[key] = (clock.monotonic() + CACHE_TTL_SECONDS, value, tier)


def _rows_for_date(
    delivery_date: date, refresh: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime, str]:
    """Retrieve actual and forecast rows through two-tier cache (RAM -> SQLite -> Live Elexon)."""
    key = f"raw:{delivery_date.isoformat()}"

    # Tier 1: In-memory cache
    if not refresh:
        mem_cached = _mem_cache_get(key)
        if mem_cached is not None:
            data, tier = mem_cached
            actuals, forecasts, retrieved_at = data
            return actuals, forecasts, retrieved_at, "memory"

    # Tier 2: Persistent SQLite cache
    if not refresh:
        sqlite_cached = get_cached_day_rows(delivery_date)
        if sqlite_cached is not None:
            actuals, forecasts, retrieved_at = sqlite_cached
            _mem_cache_set(key, (actuals, forecasts, retrieved_at), tier="sqlite_persistent")
            return actuals, forecasts, retrieved_at, "sqlite_persistent"

    # Tier 3: Live Elexon fetch
    logger.info("Fetching live Elexon data for %s (refresh=%s)", delivery_date, refresh)
    actuals = fetch_day_actuals(delivery_date)
    forecasts = fetch_day_forecasts(delivery_date)
    retrieved_at = datetime.now(timezone.utc)

    # Save to SQLite and in-memory caches
    store_cached_day_rows(delivery_date, actuals, forecasts, retrieved_at)
    _mem_cache_set(key, (actuals, forecasts, retrieved_at), tier="live")
    return actuals, forecasts, retrieved_at, "live"


def get_analysis(delivery_date: date, cutoff_clock: time, refresh: bool = False) -> dict[str, Any]:
    """Perform single-day forecast evaluation with full diagnostic and risk metrics."""
    actual_rows, forecast_rows, retrieved_at, cache_status = _rows_for_date(delivery_date, refresh=refresh)
    result = analyze_day(
        delivery_date=delivery_date,
        cutoff_clock=cutoff_clock,
        actual_rows=actual_rows,
        forecast_rows=forecast_rows,
        retrieved_at=retrieved_at,
    )
    result["provenance"]["cache_status"] = cache_status
    result["provenance"]["cache_ttl_seconds"] = CACHE_TTL_SECONDS
    result["provenance"]["cache_bypassed"] = bool(refresh)
    return result


def get_month_analysis(cutoff_clock: time, refresh: bool = False) -> dict[str, Any]:
    """Aggregate forecast accuracy and risk statistics across all 31 days of January 2026."""
    all_matched_pairs: list[tuple[float, float]] = []
    daily_summaries: list[dict[str, Any]] = []
    diurnal_buckets: dict[int, list[float]] = {p: [] for p in range(1, 49)}
    diurnal_biases: dict[int, list[float]] = {p: [] for p in range(1, 49)}

    for day_num in range(1, 32):
        delivery_date = date(2026, 1, day_num)
        try:
            day_result = get_analysis(delivery_date, cutoff_clock, refresh=refresh)
            metrics = day_result["metrics"]
            valid_cnt = metrics["valid_count"]

            daily_summaries.append({
                "date": delivery_date.isoformat(),
                "mae": metrics["mae"],
                "rmse": metrics["rmse"],
                "bias": metrics["bias"],
                "nmae_percent": metrics.get("nmae_percent"),
                "mean_actual_mw": metrics.get("mean_actual_mw"),
                "mean_forecast_mw": metrics.get("mean_forecast_mw"),
                "valid_count": valid_cnt,
                "coverage_percent": round(valid_cnt / 48.0 * 100.0, 1),
            })

            # Accumulate observations for month-aggregate calculations
            for obs in day_result["observations"]:
                if obs["forecast_mw"] is not None and obs["actual_mw"] is not None:
                    all_matched_pairs.append((obs["forecast_mw"], obs["actual_mw"]))
                    period = obs["settlement_period"]
                    err = obs["error_mw"]
                    if period in diurnal_buckets and err is not None:
                        diurnal_buckets[period].append(abs(err))
                        diurnal_biases[period].append(err)
        except Exception as exc:
            logger.warning("Could not evaluate %s for month summary: %s", delivery_date, exc)
            daily_summaries.append({
                "date": delivery_date.isoformat(),
                "mae": None,
                "rmse": None,
                "bias": None,
                "nmae_percent": None,
                "mean_actual_mw": None,
                "mean_forecast_mw": None,
                "valid_count": 0,
                "coverage_percent": 0.0,
            })

    month_metrics = calculate_metrics(all_matched_pairs)
    month_risk_buffer = calculate_risk_buffer(all_matched_pairs)
    month_wind_regimes = calculate_wind_regimes(all_matched_pairs)

    # Compute 48-period diurnal profile across the month
    diurnal_profile: list[dict[str, Any]] = []
    for p in range(1, 49):
        hour = (p - 1) // 2
        minute = ((p - 1) % 2) * 30
        time_str = f"{hour:02d}:{minute:02d}"
        errs = diurnal_buckets[p]
        biases = diurnal_biases[p]
        cnt = len(errs)
        diurnal_profile.append({
            "period": p,
            "delivery_time": time_str,
            "mae": round(sum(errs) / cnt, 1) if cnt > 0 else None,
            "bias": round(sum(biases) / cnt, 1) if cnt > 0 else None,
            "valid_count": cnt,
        })

    days_with_data = [d for d in daily_summaries if d["valid_count"] > 0 and d["mae"] is not None]
    best_day = min(days_with_data, key=lambda d: d["mae"]) if days_with_data else None
    worst_day = max(days_with_data, key=lambda d: d["mae"]) if days_with_data else None

    return {
        "month": "2026-01",
        "cutoff_time": cutoff_clock.strftime("%H:%M"),
        "total_days": 31,
        "days_with_data": len(days_with_data),
        "metrics": month_metrics,
        "best_day": best_day,
        "worst_day": worst_day,
        "daily_summaries": daily_summaries,
        "diurnal_profile": diurnal_profile,
        "wind_regimes": month_wind_regimes,
        "risk_buffer": month_risk_buffer,
        "provenance": {
            "sources": ["Elexon FUELHH (wind actual generation)", "Elexon WINDFOR (wind generation forecasts)"],
            "total_matched_intervals": len(all_matched_pairs),
            "expected_total_intervals": 31 * 48,
        },
    }


def clear_cache() -> None:
    """Clear both memory and persistent SQLite caches."""
    with _cache_lock:
        _mem_cache.clear()
    clear_persistent_cache()
