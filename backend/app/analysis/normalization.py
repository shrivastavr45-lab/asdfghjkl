"""Timestamp normalization, deterministic selection of forecast vintages, and analysis orchestration."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.analysis.metrics import (
    calculate_horizon_buckets,
    calculate_metrics,
    calculate_risk_buffer,
    calculate_wind_regimes,
)

UK = ZoneInfo("Europe/London")
UTC = timezone.utc


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = pd.Timestamp(value).to_pydatetime()
    except (ValueError, TypeError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def record_start_time(row: dict[str, Any]) -> datetime | None:
    parsed = parse_timestamp(row.get("startTime"))
    if parsed is not None:
        return parsed
    # Safe fallback for records that contain settlement date/period but omit startTime.
    settlement_date = row.get("settlementDate")
    settlement_period = row.get("settlementPeriod")
    if settlement_date is None or settlement_period is None:
        return None
    try:
        day = date.fromisoformat(str(settlement_date)[:10])
        period = int(settlement_period)
        if period < 1 or period > 50:
            return None
        local_midnight = datetime.combine(day, time.min, tzinfo=UK)
        return (local_midnight + timedelta(minutes=30 * (period - 1))).astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        return None


def parse_generation(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if pd.isna(result) or result in (float("inf"), float("-inf")):
        return None
    return result


def cutoff_datetime(delivery_date: date, cutoff_time: time) -> datetime:
    """Cutoff is the chosen clock time on the day before delivery, UK local."""
    prior_day = delivery_date - timedelta(days=1)
    return datetime.combine(prior_day, cutoff_time, tzinfo=UK).astimezone(UTC)


def _normalize_actual_rows(
    rows: list[dict[str, Any]], delivery_date: date
) -> tuple[dict[datetime, float], list[str], int]:
    warnings: list[str] = []
    normalized: list[tuple[datetime, datetime, float | None, int]] = []
    malformed = 0
    for index, row in enumerate(rows):
        fuel_type = str(row.get("fuelType", "")).strip().upper()
        if fuel_type != "WIND":
            continue
        start = record_start_time(row)
        if start is None:
            malformed += 1
            continue
        if start.astimezone(UK).date() != delivery_date:
            continue
        publish = parse_timestamp(row.get("publishTime")) or datetime.min.replace(tzinfo=UTC)
        normalized.append((start, publish, parse_generation(row.get("generation")), index))

    if malformed:
        warnings.append(f"{malformed} actual records were ignored because their delivery timestamps were invalid.")
    by_start: dict[datetime, list[tuple[datetime, float | None, int]]] = {}
    for start, published, value, index in normalized:
        by_start.setdefault(start, []).append((published, value, index))

    actuals: dict[datetime, float] = {}
    duplicate_count = 0
    for start, records in by_start.items():
        if len(records) > 1:
            duplicate_count += len(records) - 1
        # Most recently published revision wins. Prefer records with valid generation outturns,
        # and break identical publication timestamps deterministically using original row order.
        valid_records = [r for r in records if r[1] is not None]
        chosen_pool = valid_records if valid_records else records
        chosen_pool.sort(key=lambda item: (item[0], item[1] is not None, item[2]))
        chosen = chosen_pool[-1]
        if chosen[1] is not None:
            actuals[start] = chosen[1]

    if duplicate_count:
        warnings.append(
            f"{duplicate_count} duplicate actual record(s) were found; the latest published record was retained per interval."
        )
    return actuals, warnings, duplicate_count


def _normalize_forecast_rows(
    rows: list[dict[str, Any]], delivery_date: date, cutoff: datetime
) -> tuple[dict[datetime, dict[str, Any]], list[str], int, int]:
    warnings: list[str] = []
    eligible: list[tuple[datetime, datetime, float | None, int]] = []
    malformed = 0
    after_cutoff = 0
    for index, row in enumerate(rows):
        start = record_start_time(row)
        if start is None:
            malformed += 1
            continue
        if start.astimezone(UK).date() != delivery_date:
            continue
        publish = parse_timestamp(row.get("publishTime"))
        if publish is None:
            malformed += 1
            continue
        if publish > cutoff:
            after_cutoff += 1
            continue
        eligible.append((start, publish, parse_generation(row.get("generation")), index))

    if malformed:
        warnings.append(f"{malformed} forecast record(s) had invalid or missing timestamps and were ignored.")
    if after_cutoff:
        warnings.append(f"{after_cutoff} forecast publication(s) after the selected cutoff were excluded.")

    by_start: dict[datetime, list[tuple[datetime, float | None, int]]] = {}
    for start, published, value, index in eligible:
        by_start.setdefault(start, []).append((published, value, index))

    forecasts: dict[datetime, dict[str, Any]] = {}
    duplicate_count = 0
    for start, records in by_start.items():
        if len(records) > 1:
            duplicate_count += len(records) - 1
        # Latest publication wins. For equal publish times, prefer a non-missing value,
        # then use source order as a deterministic tie-break.
        records.sort(key=lambda item: (item[0], item[1] is not None, item[2]))
        chosen = records[-1]
        forecasts[start] = {"publish_time": chosen[0], "generation": chosen[1]}
    if duplicate_count:
        warnings.append(
            f"{duplicate_count} duplicate eligible forecast record(s) were found; the latest eligible publication was retained per interval."
        )
    return forecasts, warnings, duplicate_count, after_cutoff


def analyze_day(
    delivery_date: date,
    cutoff_clock: time,
    actual_rows: list[dict[str, Any]],
    forecast_rows: list[dict[str, Any]],
    retrieved_at: datetime,
) -> dict[str, Any]:
    cutoff = cutoff_datetime(delivery_date, cutoff_clock)
    actuals, actual_warnings, actual_duplicates = _normalize_actual_rows(actual_rows, delivery_date)
    forecasts, forecast_warnings, forecast_duplicates, after_cutoff = _normalize_forecast_rows(
        forecast_rows, delivery_date, cutoff
    )

    local_midnight = datetime.combine(delivery_date, time.min, tzinfo=UK)
    intervals = [
        (local_midnight + timedelta(minutes=30 * index)).astimezone(UTC)
        for index in range(48)
    ]
    observations: list[dict[str, Any]] = []
    matched_pairs: list[tuple[float, float]] = []
    horizon_pairs: list[tuple[float, float]] = []
    missing_actual = 0
    missing_forecast = 0

    for index, start in enumerate(intervals):
        settlement_period = index + 1
        actual = actuals.get(start)
        forecast_record = forecasts.get(start)
        forecast = forecast_record["generation"] if forecast_record else None
        publish_time = forecast_record["publish_time"] if forecast_record else None
        error = forecast - actual if forecast is not None and actual is not None else None
        lead_time_hours = (
            round((start - publish_time).total_seconds() / 3600.0, 1)
            if publish_time is not None
            else None
        )

        if forecast is not None and actual is not None:
            matched_pairs.append((forecast, actual))
            if lead_time_hours is not None:
                horizon_pairs.append((lead_time_hours, error))
            status = "Matched"
        elif forecast is None and actual is None:
            if forecast_record is not None:
                status = "Forecast value and actual missing"
            else:
                status = "Missing forecast and actual"
            missing_actual += 1
            missing_forecast += 1
        elif forecast is None:
            status = "Missing forecast value" if forecast_record is not None else "Missing eligible forecast"
            missing_forecast += 1
        else:
            status = "Missing actual"
            missing_actual += 1

        observations.append({
            "start_time": start.astimezone(UK).isoformat(),
            "delivery_time": start.astimezone(UK).strftime("%H:%M"),
            "settlement_period": settlement_period,
            "forecast_publish_time": publish_time.astimezone(UK).isoformat() if publish_time else None,
            "forecast_publish_time_display": publish_time.astimezone(UK).strftime("%d %b %H:%M") if publish_time else None,
            "forecast_mw": forecast,
            "actual_mw": actual,
            "error_mw": round(error, 1) if error is not None else None,
            "lead_time_hours": lead_time_hours,
            "status": status,
        })

    metrics = calculate_metrics(matched_pairs)
    risk_buffer = calculate_risk_buffer(matched_pairs)
    wind_regimes = calculate_wind_regimes(matched_pairs)
    horizon_analysis = calculate_horizon_buckets(horizon_pairs)

    diurnal_profile = [
        {
            "period": obs["settlement_period"],
            "delivery_time": obs["delivery_time"],
            "mae": abs(obs["error_mw"]) if obs["error_mw"] is not None else None,
            "bias": obs["error_mw"],
            "valid_count": 1 if obs["error_mw"] is not None else 0,
        }
        for obs in observations
    ]

    warnings = actual_warnings + forecast_warnings
    valid_actual_intervals = len(actuals)
    eligible_forecast_values = sum(record["generation"] is not None for record in forecasts.values())
    if valid_actual_intervals < 48:
        warnings.append(f"Actual wind generation values are available for {valid_actual_intervals} of 48 intervals.")
    if eligible_forecast_values < 48:
        warnings.append(f"Eligible forecast generation values are available for {eligible_forecast_values} of 48 intervals at this cutoff.")
    if len(matched_pairs) == 0:
        warnings.append("No valid forecast/actual pairs were available; accuracy metrics are unavailable.")

    # Generate executive summary and actionable purchasing guidance
    if metrics["valid_count"] > 0:
        bias_val = metrics["bias"] or 0.0
        direction = "over-predicted" if bias_val >= 0 else "under-predicted"
        abs_bias = abs(bias_val)
        mae_val = metrics["mae"] or 0.0
        nmae_text = f" ({metrics['nmae_percent']}% of actual)" if metrics.get("nmae_percent") is not None else ""
        executive_summary = (
            f"On {delivery_date.strftime('%d %b %Y')}, the forecast {direction} actual generation "
            f"by {abs_bias:,.1f} MW on average (MAE: {mae_val:,.1f} MW{nmae_text})."
        )
        buffer_mw = risk_buffer.get("recommended_buffer_mw") or 0.0
        purchasing_guidance = (
            f"At the {cutoff_clock.strftime('%H:%M')} gate closure, power buyers should maintain a reserve buffer "
            f"of ~{buffer_mw:,.0f} MW to hedge against 90% of forecast shortfall risk."
        )
    else:
        executive_summary = f"No matched observations available for {delivery_date.isoformat()} at the {cutoff_clock.strftime('%H:%M')} cutoff."
        purchasing_guidance = "Insufficient matched observations to formulate a procurement recommendation."

    return {
        "delivery_date": delivery_date.isoformat(),
        "timezone": "Europe/London",
        "cutoff_time": cutoff_clock.strftime("%H:%M"),
        "cutoff_datetime": cutoff.astimezone(UK).isoformat(),
        "expected_intervals": 48,
        "executive_summary": executive_summary,
        "purchasing_guidance": purchasing_guidance,
        "observations": observations,
        "metrics": metrics,
        "coverage": {
            "matched_intervals": len(matched_pairs),
            "expected_intervals": 48,
            "missing_actual_intervals": missing_actual,
            "missing_forecast_intervals": missing_forecast,
            "actual_intervals_available": len(actuals),
            "eligible_forecast_intervals": eligible_forecast_values,
        },
        "risk_buffer": risk_buffer,
        "diurnal_profile": diurnal_profile,
        "wind_regimes": wind_regimes,
        "horizon_analysis": horizon_analysis,
        "provenance": {
            "sources": ["Elexon FUELHH (wind actual generation)", "Elexon WINDFOR (wind generation forecasts)"],
            "retrieved_at": retrieved_at.astimezone(UK).isoformat(),
            "actual_records_retrieved": len(actual_rows),
            "forecast_records_retrieved": len(forecast_rows),
            "actual_wind_intervals": len(actuals),
            "eligible_forecast_intervals": eligible_forecast_values,
            "matched_intervals": len(matched_pairs),
            "actual_duplicate_rows": actual_duplicates,
            "forecast_duplicate_rows": forecast_duplicates,
            "forecast_rows_after_cutoff_excluded": after_cutoff,
            "warnings": warnings,
            "cache_status": "live",
        },
    }
