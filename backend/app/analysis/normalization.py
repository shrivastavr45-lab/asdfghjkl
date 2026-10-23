"""Timestamp normalization and deterministic selection of forecast vintages."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.analysis.metrics import calculate_metrics

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
        # Most recently published revision wins; later source order breaks exact timestamp ties.
        records.sort(key=lambda item: (item[0], item[2]))
        chosen = records[-1]
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
        # then use source order as a deterministic tie-break (never compare None with float).
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
    missing_actual = 0
    missing_forecast = 0

    for start in intervals:
        actual = actuals.get(start)
        forecast_record = forecasts.get(start)
        forecast = forecast_record["generation"] if forecast_record else None
        publish_time = forecast_record["publish_time"] if forecast_record else None
        error = forecast - actual if forecast is not None and actual is not None else None
        if forecast is not None and actual is not None:
            matched_pairs.append((forecast, actual))
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
            "forecast_publish_time": publish_time.astimezone(UK).isoformat() if publish_time else None,
            "forecast_publish_time_display": publish_time.astimezone(UK).strftime("%d %b %H:%M") if publish_time else None,
            "forecast_mw": forecast,
            "actual_mw": actual,
            "error_mw": error,
            "status": status,
        })

    metrics = calculate_metrics(matched_pairs)
    warnings = actual_warnings + forecast_warnings
    valid_actual_intervals = len(actuals)
    eligible_forecast_values = sum(record["generation"] is not None for record in forecasts.values())
    if valid_actual_intervals < 48:
        warnings.append(f"Actual wind generation values are available for {valid_actual_intervals} of 48 intervals.")
    if eligible_forecast_values < 48:
        warnings.append(f"Eligible forecast generation values are available for {eligible_forecast_values} of 48 intervals at this cutoff.")
    if len(matched_pairs) == 0:
        warnings.append("No valid forecast/actual pairs were available; accuracy metrics are unavailable.")

    return {
        "delivery_date": delivery_date.isoformat(),
        "timezone": "Europe/London",
        "cutoff_time": cutoff_clock.strftime("%H:%M"),
        "cutoff_datetime": cutoff.astimezone(UK).isoformat(),
        "expected_intervals": 48,
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
        },
    }
