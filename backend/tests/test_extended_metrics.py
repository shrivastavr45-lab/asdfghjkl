"""Tests for risk buffers, wind regimes, horizon buckets, and SQLite caching."""
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from app.analysis.metrics import (
    calculate_horizon_buckets,
    calculate_metrics,
    calculate_risk_buffer,
    calculate_wind_regimes,
)
from app.services.persistent_cache import (
    clear_persistent_cache,
    get_cached_day_rows,
    init_cache_db,
    store_cached_day_rows,
)


def test_calculate_metrics_with_nmae():
    # pairs of (forecast, actual)
    pairs = [(1000.0, 800.0), (1200.0, 1000.0)]
    # errors: 200, 200 -> mae = 200, mean actual = 900 -> nmae = 200/900 * 100 = 22.22%
    m = calculate_metrics(pairs)
    assert m["valid_count"] == 2
    assert m["mae"] == 200.0
    assert m["mean_actual_mw"] == 900.0
    assert m["mean_forecast_mw"] == 1100.0
    assert round(m["nmae_percent"], 2) == 22.22


def test_calculate_risk_buffer():
    # 10 intervals with various over/under forecasts
    pairs = [
        (1000.0, 800.0),  # error +200, shortfall 200
        (900.0, 950.0),   # error -50, shortfall 0
        (1200.0, 700.0),  # error +500, shortfall 500
        (800.0, 800.0),   # error 0, shortfall 0
        (1500.0, 1000.0), # error +500, shortfall 500
    ]
    rb = calculate_risk_buffer(pairs)
    assert rb["p50_error_mw"] is not None
    assert rb["p90_error_mw"] is not None
    assert rb["recommended_buffer_mw"] > 0
    assert "reserve buffer" in rb["interpretation"]


def test_calculate_wind_regimes():
    pairs = [
        (4200.0, 4000.0),   # Low (<5 GW)
        (7500.0, 7000.0),   # Medium (5-12 GW)
        (14000.0, 13000.0), # High (>12 GW)
    ]
    regimes = calculate_wind_regimes(pairs)
    assert len(regimes) == 3
    low = next(r for r in regimes if "Low" in r["regime"])
    med = next(r for r in regimes if "Medium" in r["regime"])
    high = next(r for r in regimes if "High" in r["regime"])

    assert low["count"] == 1
    assert low["mae"] == 200.0
    assert med["count"] == 1
    assert med["mae"] == 500.0
    assert high["count"] == 1
    assert high["mae"] == 1000.0


def test_calculate_horizon_buckets():
    horizon_pairs = [
        (6.0, 50.0),   # < 12h
        (18.0, 120.0), # 12-24h
        (30.0, 200.0), # 24-36h
    ]
    buckets = calculate_horizon_buckets(horizon_pairs)
    assert len(buckets) == 5
    b1 = next(b for b in buckets if b["horizon_range"] == "< 12h")
    assert b1["count"] == 1
    assert b1["mae"] == 50.0


def test_sqlite_persistent_cache_cycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.db"
        init_cache_db(db_path)

        d = date(2026, 1, 14)
        actuals = [{"startTime": "2026-01-14T00:00:00Z", "generation": 100, "fuelType": "WIND"}]
        forecasts = [{"startTime": "2026-01-14T00:00:00Z", "generation": 110, "publishTime": "2026-01-13T10:00:00Z"}]
        now = datetime.now(timezone.utc)

        # Before caching
        assert get_cached_day_rows(d, db_path=db_path) is None

        # Store
        store_cached_day_rows(d, actuals, forecasts, now, db_path=db_path)

        # Retrieve
        cached = get_cached_day_rows(d, db_path=db_path)
        assert cached is not None
        cached_actuals, cached_forecasts, cached_retrieved = cached
        assert len(cached_actuals) == 1
        assert cached_actuals[0]["generation"] == 100
        assert len(cached_forecasts) == 1
        assert cached_forecasts[0]["generation"] == 110

        # Clear
        clear_persistent_cache(db_path=db_path)
        assert get_cached_day_rows(d, db_path=db_path) is None
