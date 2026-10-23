"""Validated application API routes."""
from __future__ import annotations

import re
from datetime import date, time

from fastapi import APIRouter, HTTPException, Query

from app.services.analysis_service import get_analysis
from app.services.elexon_client import ElexonAPIError

router = APIRouter(prefix="/api")
DATE_PATTERN = re.compile(r"^2026-01-(0[1-9]|[12][0-9]|3[01])$")
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "wind-forecast-intelligence", "data_mode": "live-elexon-only"}


@router.get("/dates")
def dates() -> dict[str, list[str]]:
    return {"dates": [date(2026, 1, day).isoformat() for day in range(1, 32)]}


@router.get("/analysis")
def analysis(
    delivery_date: str = Query(alias="date", description="Delivery date within January 2026"),
    cutoff_time: str = Query(default="16:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"),
    refresh: bool = Query(default=False),
) -> dict:
    if not DATE_PATTERN.fullmatch(delivery_date):
        raise HTTPException(status_code=422, detail="The delivery date must be between 2026-01-01 and 2026-01-31.")
    if not TIME_PATTERN.fullmatch(cutoff_time):
        raise HTTPException(status_code=422, detail="cutoff_time must use 24-hour HH:MM format, for example 16:00.")
    try:
        return get_analysis(date.fromisoformat(delivery_date), time.fromisoformat(cutoff_time), refresh=refresh)
    except ElexonAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # API boundary: return a useful message while logs retain details.
        import logging
        logging.getLogger(__name__).exception("Unexpected analysis failure")
        raise HTTPException(status_code=500, detail="Unexpected analysis error. Check the server logs and retry.") from exc
