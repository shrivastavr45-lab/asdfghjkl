from datetime import date, datetime, time, timezone

from app.analysis.normalization import analyze_day, cutoff_datetime, parse_timestamp, record_start_time

DAY = date(2026, 1, 14)
RETRIEVED = datetime(2026, 1, 16, tzinfo=timezone.utc)


def mk(start, published, value, fuel="WIND"):
    return {"startTime": start, "publishTime": published, "generation": value, "fuelType": fuel}


def test_selects_latest_forecast_published_before_cutoff(base_actual_rows, base_forecast_rows, analyze):
    base_forecast_rows.extend([
        mk("2026-01-14T00:00:00Z", "2026-01-13T14:00:00Z", 900),
        mk("2026-01-14T00:00:00Z", "2026-01-13T15:59:00Z", 950),
    ])
    result = analyze(forecasts=base_forecast_rows)
    assert result["observations"][0]["forecast_mw"] == 950
    assert result["observations"][0]["forecast_publish_time"].startswith("2026-01-13T15:59")


def test_forecast_after_cutoff_is_excluded(base_actual_rows, analyze):
    forecasts = [mk("2026-01-14T00:00:00Z", "2026-01-13T16:01:00Z", 777)]
    result = analyze(forecasts=forecasts)
    assert result["observations"][0]["forecast_mw"] is None
    assert result["provenance"]["forecast_rows_after_cutoff_excluded"] == 1
    assert result["metrics"]["valid_count"] == 0


def test_matching_uses_delivery_timestamp_not_publication_timestamp(analyze):
    actuals = [mk("2026-01-14T00:00:00Z", "2026-01-16T09:00:00Z", 500)]
    forecasts = [mk("2026-01-14T00:00:00Z", "2026-01-13T12:00:00Z", 520)]
    result = analyze(actuals=actuals, forecasts=forecasts)
    first = result["observations"][0]
    assert first["actual_mw"] == 500
    assert first["forecast_mw"] == 520
    assert first["error_mw"] == 20


def test_forecast_error_positive_means_overforecast(analyze):
    actuals = [mk("2026-01-14T00:00:00Z", "2026-01-15T10:00:00Z", 100)]
    forecasts = [mk("2026-01-14T00:00:00Z", "2026-01-13T10:00:00Z", 140)]
    first = analyze(actuals=actuals, forecasts=forecasts)["observations"][0]
    assert first["error_mw"] == 40


def test_missing_forecast_and_missing_actual_remain_null(analyze):
    actuals = [mk("2026-01-14T00:00:00Z", "2026-01-15T10:00:00Z", 100)]
    forecasts = [mk("2026-01-14T00:30:00Z", "2026-01-13T10:00:00Z", None)]
    result = analyze(actuals=actuals, forecasts=forecasts)
    assert result["observations"][0]["forecast_mw"] is None
    assert result["observations"][0]["actual_mw"] == 100
    assert result["observations"][0]["status"] == "Missing eligible forecast"
    assert result["observations"][1]["actual_mw"] is None
    assert result["metrics"]["mae"] is None


def test_only_wind_fuel_type_is_used(analyze):
    actuals = [mk("2026-01-14T00:00:00Z", "2026-01-15T10:00:00Z", 100, "WIND"),
               mk("2026-01-14T00:00:00Z", "2026-01-15T10:00:00Z", 999, "GAS")]
    forecasts = [mk("2026-01-14T00:00:00Z", "2026-01-13T10:00:00Z", 110)]
    result = analyze(actuals=actuals, forecasts=forecasts)
    assert result["observations"][0]["actual_mw"] == 100


def test_duplicate_actuals_are_deterministic_and_warn(analyze):
    actuals = [mk("2026-01-14T00:00:00Z", "2026-01-15T10:00:00Z", 100),
               mk("2026-01-14T00:00:00Z", "2026-01-15T11:00:00Z", 101)]
    result = analyze(actuals=actuals, forecasts=[])
    assert result["observations"][0]["actual_mw"] == 101
    assert result["provenance"]["actual_duplicate_rows"] == 1
    assert any("duplicate actual" in warning for warning in result["provenance"]["warnings"])


def test_forecast_duplicates_latest_publish_selected(analyze):
    actuals = [mk("2026-01-14T00:00:00Z", "2026-01-15T11:00:00Z", 100)]
    forecasts = [mk("2026-01-14T00:00:00Z", "2026-01-13T12:00:00Z", 90),
                 mk("2026-01-14T00:00:00Z", "2026-01-13T15:00:00Z", 98)]
    result = analyze(actuals=actuals, forecasts=forecasts)
    assert result["observations"][0]["forecast_mw"] == 98
    assert result["provenance"]["forecast_duplicate_rows"] == 1


def test_timezone_normalization_and_cutoff_handling():
    dt = parse_timestamp("2026-01-13T16:00:00Z")
    assert dt == datetime(2026, 1, 13, 16, 0, tzinfo=timezone.utc)
    cutoff = cutoff_datetime(DAY, time(16, 0))
    assert cutoff == datetime(2026, 1, 13, 16, 0, tzinfo=timezone.utc)
    assert parse_timestamp("2026-01-13T16:00:00") == cutoff


def test_settlement_period_fallback():
    row = {"settlementDate": "2026-01-14", "settlementPeriod": 2}
    assert record_start_time(row) == datetime(2026, 1, 14, 0, 30, tzinfo=timezone.utc)


def test_returns_all_48_half_hour_intervals(analyze):
    result = analyze(actuals=[], forecasts=[])
    assert len(result["observations"]) == 48
    assert result["observations"][0]["delivery_time"] == "00:00"
    assert result["observations"][1]["delivery_time"] == "00:30"
    assert result["observations"][-1]["delivery_time"] == "23:30"
    assert result["metrics"]["valid_count"] == 0


def test_exact_timestamp_duplicates_with_missing_values_are_deterministic(analyze):
    actuals = [mk('2026-01-14T00:00:00Z', '2026-01-15T08:00:00Z', 100)]
    forecasts = [
        mk('2026-01-14T00:00:00Z', '2026-01-13T15:00:00Z', None),
        mk('2026-01-14T00:00:00Z', '2026-01-13T15:00:00Z', 120),
    ]
    result = analyze(actuals=actuals, forecasts=forecasts)
    assert result['observations'][0]['forecast_mw'] == 120
    assert result['observations'][0]['error_mw'] == 20
    assert result['provenance']['forecast_duplicate_rows'] == 1


def test_null_forecast_value_keeps_publication_but_is_not_a_valid_pair(analyze):
    actuals = [mk("2026-01-14T00:00:00Z", "2026-01-15T10:00:00Z", 100)]
    forecasts = [mk("2026-01-14T00:00:00Z", "2026-01-13T15:00:00Z", None)]
    result = analyze(actuals=actuals, forecasts=forecasts)
    first = result["observations"][0]
    assert first["forecast_publish_time"] is not None
    assert first["forecast_mw"] is None
    assert first["actual_mw"] == 100
    assert first["status"] == "Missing forecast value"
    assert result["coverage"]["eligible_forecast_intervals"] == 0
    assert result["metrics"]["valid_count"] == 0
