"""Pure forecast evaluation metrics, statistical distributions, and risk buffer calculations."""
from __future__ import annotations

import math
from typing import Any, Iterable


def _quantile(values: list[float], q: float) -> float:
    """Deterministic linear quantile calculation without requiring heavy external dependencies."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return sorted_vals[low]
    weight = pos - low
    return sorted_vals[low] * (1.0 - weight) + sorted_vals[high] * weight


def calculate_metrics(pairs: Iterable[tuple[float, float]]) -> dict[str, float | int | None]:
    """Calculate MAE, RMSE, forecast bias, and normalized error for (forecast, actual) pairs."""
    valid = [(float(forecast), float(actual)) for forecast, actual in pairs]
    count = len(valid)
    if not count:
        return {"mae": None, "rmse": None, "bias": None, "valid_count": 0}

    errors = [forecast - actual for forecast, actual in valid]
    mae = sum(abs(error) for error in errors) / count
    rmse = math.sqrt(sum(error * error for error in errors) / count)
    bias = sum(errors) / count
    mean_actual = sum(actual for _, actual in valid) / count
    mean_forecast = sum(forecast for forecast, _ in valid) / count
    nmae = (mae / mean_actual * 100.0) if mean_actual > 0 else None

    return {
        "mae": mae,
        "rmse": rmse,
        "bias": bias,
        "valid_count": count,
        "mean_actual_mw": mean_actual,
        "mean_forecast_mw": mean_forecast,
        "nmae_percent": nmae,
    }


def calculate_risk_buffer(pairs: Iterable[tuple[float, float]]) -> dict[str, Any]:
    """Calculate error quantiles (P50, P90, P95) and recommended procurement reserve buffer in MW."""
    valid = [(float(forecast), float(actual)) for forecast, actual in pairs]
    if not valid:
        return {
            "p50_error_mw": None,
            "p90_error_mw": None,
            "p95_error_mw": None,
            "p90_shortfall_mw": None,
            "recommended_buffer_mw": None,
            "interpretation": "Insufficient matched observations to calculate risk buffer.",
        }

    errors = [forecast - actual for forecast, actual in valid]
    shortfalls = [max(0.0, forecast - actual) for forecast, actual in valid]

    p50 = _quantile(errors, 0.50)
    p90 = _quantile(errors, 0.90)
    p95 = _quantile(errors, 0.95)
    p90_shortfall = _quantile(shortfalls, 0.90)
    recommended_buffer = round(max(0.0, p90_shortfall), 1)

    interpretation = (
        f"To hedge 90% of wind generation shortfall risk, procurement teams should maintain "
        f"a flexible backup/reserve buffer of approximately {recommended_buffer:,.0f} MW."
    )

    return {
        "p50_error_mw": round(p50, 1),
        "p90_error_mw": round(p90, 1),
        "p95_error_mw": round(p95, 1),
        "p90_shortfall_mw": round(p90_shortfall, 1),
        "recommended_buffer_mw": recommended_buffer,
        "interpretation": interpretation,
    }


def calculate_wind_regimes(pairs: Iterable[tuple[float, float]]) -> list[dict[str, Any]]:
    """Segment forecast accuracy across Low (<5 GW), Medium (5-12 GW), and High (>12 GW) wind regimes."""
    valid = [(float(forecast), float(actual)) for forecast, actual in pairs]
    definitions = [
        ("Low (<5 GW)", "< 5,000 MW", lambda actual: actual < 5000.0),
        ("Medium (5-12 GW)", "5,000 - 12,000 MW", lambda actual: 5000.0 <= actual <= 12000.0),
        ("High (>12 GW)", "> 12,000 MW", lambda actual: actual > 12000.0),
    ]

    regimes: list[dict[str, Any]] = []
    for name, bounds, predicate in definitions:
        subset = [(f, a) for f, a in valid if predicate(a)]
        cnt = len(subset)
        if cnt > 0:
            errs = [f - a for f, a in subset]
            mae = sum(abs(e) for e in errs) / cnt
            bias = sum(e for e in errs) / cnt
            avg_act = sum(a for _, a in subset) / cnt
            nmae = (mae / avg_act * 100.0) if avg_act > 0 else None
            regimes.append({
                "regime": name,
                "range_mw": bounds,
                "count": cnt,
                "mae": round(mae, 1),
                "bias": round(bias, 1),
                "nmae_percent": round(nmae, 1) if nmae is not None else None,
            })
        else:
            regimes.append({
                "regime": name,
                "range_mw": bounds,
                "count": 0,
                "mae": None,
                "bias": None,
                "nmae_percent": None,
            })

    return regimes


def calculate_horizon_buckets(horizon_pairs: Iterable[tuple[float, float]]) -> list[dict[str, Any]]:
    """Analyze error progression across forecast lead time horizons (lead_hours, error_mw)."""
    valid = [(float(lead), float(err)) for lead, err in horizon_pairs if lead is not None and err is not None]
    definitions = [
        ("< 12h", lambda h: h < 12.0),
        ("12 - 24h", lambda h: 12.0 <= h < 24.0),
        ("24 - 36h", lambda h: 24.0 <= h < 36.0),
        ("36 - 48h", lambda h: 36.0 <= h < 48.0),
        ("> 48h", lambda h: h >= 48.0),
    ]

    buckets: list[dict[str, Any]] = []
    for label, predicate in definitions:
        subset_errors = [err for lead, err in valid if predicate(lead)]
        cnt = len(subset_errors)
        if cnt > 0:
            mae = sum(abs(e) for e in subset_errors) / cnt
            bias = sum(subset_errors) / cnt
            buckets.append({
                "horizon_range": label,
                "count": cnt,
                "mae": round(mae, 1),
                "bias": round(bias, 1),
            })
        else:
            buckets.append({
                "horizon_range": label,
                "count": 0,
                "mae": None,
                "bias": None,
            })
    return buckets
