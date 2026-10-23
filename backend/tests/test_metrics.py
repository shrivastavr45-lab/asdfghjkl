import math

from app.analysis.metrics import calculate_metrics


def test_metrics_calculation():
    result = calculate_metrics([(110, 100), (80, 100), (103, 100)])
    assert result["valid_count"] == 3
    assert result["mae"] == 11
    assert math.isclose(result["rmse"], math.sqrt((100 + 400 + 9) / 3))
    assert math.isclose(result["bias"], -7 / 3)


def test_metrics_empty_pairs_are_unavailable_not_zero():
    assert calculate_metrics([]) == {"mae": None, "rmse": None, "bias": None, "valid_count": 0}


def test_forecast_error_sign_convention():
    assert calculate_metrics([(125, 100)])["bias"] == 25
    assert calculate_metrics([(75, 100)])["bias"] == -25
