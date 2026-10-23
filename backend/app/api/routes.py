"""Validated application API routes with Pydantic response models."""
from __future__ import annotations

import os
import re
from datetime import date, time

from fastapi import APIRouter, HTTPException, Query

from app.schemas.analysis import DayAnalysisResponse, MonthAnalysisResponse
from app.services.analysis_service import get_analysis, get_month_analysis
from app.services.elexon_client import ElexonAPIError

router = APIRouter(prefix="/api")
DATE_PATTERN = re.compile(r"^2026-01-(0[1-9]|[12][0-9]|3[01])$")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DEFAULT_CUTOFF_TIME = os.getenv("DEFAULT_CUTOFF_TIME", "12:00")


@router.get("/health", summary="Service Health and Configuration")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "wind-forecast-intelligence",
        "data_mode": "live-elexon-only",
        "default_cutoff_time": DEFAULT_CUTOFF_TIME,
    }


@router.get("/dates", summary="Valid delivery dates in January 2026")
def dates() -> dict[str, list[str]]:
    return {"dates": [date(2026, 1, day).isoformat() for day in range(1, 32)]}


@router.get(
    "/analysis",
    response_model=DayAnalysisResponse,
    summary="Daily Wind Forecast Accuracy & Risk Analysis",
    description="Evaluates half-hourly WINDFOR forecast values published prior to the cutoff against FUELHH actuals for the selected delivery date.",
)
def analysis(
    delivery_date: str = Query(alias="date", description="Delivery date within January 2026 (YYYY-MM-DD)"),
    cutoff_time: str = Query(default=DEFAULT_CUTOFF_TIME, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$", description="Day-ahead decision cutoff clock (HH:MM, Europe/London)"),
    refresh: bool = Query(default=False, description="Bypass cache and pull fresh data directly from Elexon"),
) -> DayAnalysisResponse:
    if not DATE_PATTERN.fullmatch(delivery_date):
        raise HTTPException(status_code=422, detail="The delivery date must be between 2026-01-01 and 2026-01-31.")
    if not TIME_PATTERN.fullmatch(cutoff_time):
        raise HTTPException(status_code=422, detail="cutoff_time must use 24-hour HH:MM format, for example 12:00 or 16:00.")
    try:
        data = get_analysis(date.fromisoformat(delivery_date), time.fromisoformat(cutoff_time), refresh=refresh)
        return DayAnalysisResponse(**data)
    except ElexonAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Unexpected daily analysis failure")
        raise HTTPException(status_code=500, detail="Unexpected analysis error. Check the server logs and retry.") from exc


@router.get(
    "/analysis/month",
    response_model=MonthAnalysisResponse,
    summary="Month-Aggregate Wind Forecast Accuracy & Risk Analysis",
    description="Aggregates accuracy, bias, diurnal error profiles, and shortfall risk across all 31 days of January 2026.",
)
def month_analysis(
    cutoff_time: str = Query(default=DEFAULT_CUTOFF_TIME, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$", description="Day-ahead decision cutoff clock (HH:MM, Europe/London)"),
    refresh: bool = Query(default=False, description="Bypass cache and pull fresh data from Elexon"),
) -> MonthAnalysisResponse:
    if not TIME_PATTERN.fullmatch(cutoff_time):
        raise HTTPException(status_code=422, detail="cutoff_time must use 24-hour HH:MM format, for example 12:00 or 16:00.")
    try:
        data = get_month_analysis(time.fromisoformat(cutoff_time), refresh=refresh)
        return MonthAnalysisResponse(**data)
    except ElexonAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Unexpected month analysis failure")
        raise HTTPException(status_code=500, detail="Unexpected month analysis error. Check the server logs and retry.") from exc
