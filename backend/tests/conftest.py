from datetime import date, datetime, time, timezone
from pathlib import Path
import sys

# Keep tests runnable both from the repository root and from backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

from app.analysis.normalization import analyze_day

DELIVERY_DATE = date(2026, 1, 14)


def iso(day: str, hh: int, mm: int = 0) -> str:
    return f"{day}T{hh:02d}:{mm:02d}:00Z"


@pytest.fixture

def base_actual_rows():
    rows = []
    for index in range(48):
        minute = 30 if index % 2 else 0
        hour = index // 2
        rows.append({
            "startTime": iso("2026-01-14", hour, minute),
            "publishTime": iso("2026-01-15", 8),
            "fuelType": "WIND",
            "generation": 1000 + index,
        })
    return rows


@pytest.fixture

def base_forecast_rows():
    rows = []
    for index in range(48):
        minute = 30 if index % 2 else 0
        hour = index // 2
        rows.append({
            "startTime": iso("2026-01-14", hour, minute),
            "publishTime": iso("2026-01-13", 15),
            "generation": 1000 + index + (10 if index % 2 == 0 else -10),
        })
    return rows


@pytest.fixture

def analyze(base_actual_rows, base_forecast_rows):
    def _analyze(actuals=None, forecasts=None, cutoff=time(16, 0)):
        return analyze_day(
            delivery_date=DELIVERY_DATE,
            cutoff_clock=cutoff,
            actual_rows=base_actual_rows if actuals is None else actuals,
            forecast_rows=base_forecast_rows if forecasts is None else forecasts,
            retrieved_at=datetime(2026, 1, 16, tzinfo=timezone.utc),
        )
    return _analyze
