"""Small, defensive client for the two approved Elexon dataset streams.

Both dataset stream endpoints filter on publication timestamps. Delivery dates
and fuel types are filtered locally after retrieving the bounded stream window.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
TIMEOUT_SECONDS = 25
USER_AGENT = "WindForecastIntelligence/1.0 (educational analytics dashboard)"
FORECAST_LOOKBACK_DAYS = 14
ACTUAL_REVISION_WINDOW_DAYS = 14
logger = logging.getLogger(__name__)


class ElexonAPIError(RuntimeError):
    """Raised when the Elexon API cannot provide a usable dataset response."""


def iso_utc(value: datetime) -> str:
    """Return an ISO-8601 timestamp with an explicit UTC Z suffix."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _unwrap_rows(payload: Any, dataset: str) -> list[dict[str, Any]]:
    """Accept the stream array and common JSON envelope variants defensively."""
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("data")
        if rows is None:
            rows = payload.get("results")
        if rows is None:
            raise ElexonAPIError(
                f"Elexon returned a JSON object without a 'data' or 'results' list for {dataset}."
            )
    else:
        raise ElexonAPIError(f"Elexon returned an unexpected JSON format for {dataset}.")

    if not isinstance(rows, list):
        raise ElexonAPIError(f"Elexon returned a non-list data field for {dataset}.")
    if any(not isinstance(row, dict) for row in rows):
        raise ElexonAPIError(f"Elexon returned a malformed row in {dataset}.")
    return rows


def _dataset_params(dataset: str, from_time: datetime, to_time: datetime) -> dict[str, str]:
    """Build documented publication-time filters for the approved datasets.

    The Elexon dataset-stream API filters these streams by publication time.
    Delivery-period filtering and FUELHH fuel-type filtering are therefore done
    locally after the response is validated.
    """
    if dataset in {"FUELHH", "WINDFOR"}:
        return {
            "publishDateTimeFrom": iso_utc(from_time),
            "publishDateTimeTo": iso_utc(to_time),
        }
    raise ValueError("Only FUELHH and WINDFOR are permitted data sources.")


def fetch_stream(dataset: str, from_time: datetime, to_time: datetime) -> list[dict[str, Any]]:
    """Fetch a bounded range from an official, documented Elexon stream."""
    params = _dataset_params(dataset, from_time, to_time)
    url = f"{BASE_URL}/datasets/{dataset}/stream"
    try:
        response = requests.get(
            url,
            params=params,
            timeout=TIMEOUT_SECONDS,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        if response.status_code == 429:
            raise ElexonAPIError(
                f"Elexon rate-limited the {dataset} request (HTTP 429). Wait briefly, then refresh."
            )
        response.raise_for_status()
    except ElexonAPIError:
        raise
    except requests.Timeout as exc:
        raise ElexonAPIError(
            f"The Elexon {dataset} request timed out after {TIMEOUT_SECONDS} seconds."
        ) from exc
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        suffix = f" (HTTP {status})" if status else ""
        logger.warning("Elexon %s request failed%s: %s", dataset, suffix, type(exc).__name__)
        raise ElexonAPIError(
            f"Could not retrieve Elexon dataset {dataset}{suffix}. Check network/API availability and retry."
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ElexonAPIError(f"Elexon returned invalid JSON for {dataset}.") from exc
    return _unwrap_rows(payload, dataset)


def fetch_day_actuals(delivery_date: date) -> list[dict[str, Any]]:
    """Retrieve FUELHH revisions over a bounded publication-time window.

    FUELHH is filtered by publication time, not settlement date. Start at the
    delivery day's midnight and allow a 14-day revision window after delivery;
    normalization later filters to the selected delivery date and fuelType=WIND.
    The bounded window is an explicit MVP assumption to avoid downloading an
    unbounded history of published revisions for a single delivery day.
    """
    start = datetime(delivery_date.year, delivery_date.month, delivery_date.day, tzinfo=timezone.utc)
    return fetch_stream(
        "FUELHH",
        start,
        start + timedelta(days=ACTUAL_REVISION_WINDOW_DAYS + 1),
    )


def fetch_day_forecasts(delivery_date: date) -> list[dict[str, Any]]:
    """Retrieve forecast vintages published over a bounded lookback horizon.

    WINDFOR filters by publication time, not delivery time. Fetch publications
    from 14 days before delivery through the end of the delivery date, then
    locally retain only rows whose startTime belongs to the selected delivery
    date. Fourteen days is the forecast-lookback assumption for this MVP; it is
    explicit here and in the README rather than being silently inferred from a
    delivery-time filter. The selected decision cutoff is applied downstream.
    """
    start = datetime(delivery_date.year, delivery_date.month, delivery_date.day, tzinfo=timezone.utc)
    return fetch_stream(
        "WINDFOR",
        start - timedelta(days=FORECAST_LOOKBACK_DAYS),
        start + timedelta(days=1),
    )
