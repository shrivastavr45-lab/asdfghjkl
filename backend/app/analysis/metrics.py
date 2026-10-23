"""Pure forecast evaluation metrics; no I/O or fabricated fallback values."""
from __future__ import annotations

import math
from typing import Iterable


def calculate_metrics(pairs: Iterable[tuple[float, float]]) -> dict[str, float | int | None]:
    """Calculate MAE, RMSE and forecast bias for (forecast, actual) pairs."""
    valid = [(float(forecast), float(actual)) for forecast, actual in pairs]
    count = len(valid)
    if not count:
        return {"mae": None, "rmse": None, "bias": None, "valid_count": 0}

    errors = [forecast - actual for forecast, actual in valid]
    mae = sum(abs(error) for error in errors) / count
    rmse = math.sqrt(sum(error * error for error in errors) / count)
    bias = sum(errors) / count
    return {"mae": mae, "rmse": rmse, "bias": bias, "valid_count": count}
