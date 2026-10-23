"""Hardened, defensive client for the two approved Elexon dataset streams.

Both dataset stream endpoints filter on publication timestamps. Delivery dates
and fuel types are filtered locally after retrieving the bounded stream window.
Includes exponential backoff retries for 429 / 5xx, structured logging, and timeout safety.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
TIMEOUT_SECONDS = 30
USER_AGENT = "WindForecastIntelligence/1.1 (educational analytics dashboard; retry-hardened)"
FORECAST_LOOKBACK_DAYS = 14
ACTUAL_REVISION_WINDOW_DAYS = 14
MAX_RETRIES = 3
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
    """Build documented publication-time filters for the approved datasets."""
    if dataset in {"FUELHH", "WINDFOR"}:
        return {
            "publishDateTimeFrom": iso_utc(from_time),
            "publishDateTimeTo": iso_utc(to_time),
        }
    raise ValueError("Only FUELHH and WINDFOR are permitted data sources.")


def _http_get_with_retry(url: str, params: dict[str, str], dataset: str) -> requests.Response:
    """Execute GET request with retry backoff on transient 429 and 5xx errors."""
    backoff = 1.0
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}

    for attempt in range(MAX_RETRIES):
        t0 = time.monotonic()
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS, headers=headers)
            duration_ms = (time.monotonic() - t0) * 1000.0

            # If transient 429 or 5xx, retry with backoff if attempts remain
            if response.status_code in (429, 500, 502, 503, 504) and attempt < (MAX_RETRIES - 1):
                logger.warning(
                    "Elexon %s returned HTTP %s on attempt %d; retrying in %.1fs...",
                    dataset,
                    response.status_code,
                    attempt + 1,
                    backoff,
                )
                time.sleep(backoff)
                backoff *= 2
                continue

            if response.status_code == 429:
                raise ElexonAPIError(
                    f"Elexon rate-limited the {dataset} request (HTTP 429). Wait briefly, then refresh."
                )

            response.raise_for_status()
            logger.info("Elexon %s fetch completed in %.1fms with HTTP %s", dataset, duration_ms, response.status_code)
            return response
        except ElexonAPIError:
            raise
        except requests.Timeout as exc:
            if attempt < (MAX_RETRIES - 1):
                time.sleep(backoff)
                backoff *= 2
                continue
            logger.error("Elexon %s timed out after %ds", dataset, TIMEOUT_SECONDS)
            raise ElexonAPIError(
                f"The Elexon {dataset} request timed out after {TIMEOUT_SECONDS} seconds."
            ) from exc
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            if attempt < (MAX_RETRIES - 1) and status in (500, 502, 503, 504):
                time.sleep(backoff)
                backoff *= 2
                continue
            logger.warning("Elexon %s request failed%s: %s", dataset, suffix, type(exc).__name__)
            raise ElexonAPIError(
                f"Could not retrieve Elexon dataset {dataset}{suffix}. Check network/API availability and retry."
            ) from exc

    raise ElexonAPIError(f"Could not retrieve Elexon dataset {dataset} after {MAX_RETRIES} attempts.")


def fetch_stream(dataset: str, from_time: datetime, to_time: datetime) -> list[dict[str, Any]]:
    """Fetch a bounded range from an official, documented Elexon stream."""
    params = _dataset_params(dataset, from_time, to_time)
    url = f"{BASE_URL}/datasets/{dataset}/stream"
    response = _http_get_with_retry(url, params, dataset)

    try:
        payload = response.json()
    except ValueError as exc:
        raise ElexonAPIError(f"Elexon returned invalid JSON for {dataset}.") from exc
    return _unwrap_rows(payload, dataset)


def fetch_day_actuals(delivery_date: date) -> list[dict[str, Any]]:
    """Retrieve FUELHH revisions over a bounded publication-time window."""
    start = datetime(delivery_date.year, delivery_date.month, delivery_date.day, tzinfo=timezone.utc)
    return fetch_stream(
        "FUELHH",
        start,
        start + timedelta(days=ACTUAL_REVISION_WINDOW_DAYS + 1),
    )


def fetch_day_forecasts(delivery_date: date) -> list[dict[str, Any]]:
    """Retrieve forecast vintages published over a bounded lookback horizon."""
    start = datetime(delivery_date.year, delivery_date.month, delivery_date.day, tzinfo=timezone.utc)
    return fetch_stream(
        "WINDFOR",
        start - timedelta(days=FORECAST_LOOKBACK_DAYS),
        start + timedelta(days=1),
    )
