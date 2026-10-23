"""Durable SQLite caching layer for Elexon raw dataset queries.

Provides persistence across container/dyno restarts so historical queries
never fail if Elexon is rate-limiting, slow, or undergoing maintenance.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(os.getenv("CACHE_DB_PATH", ".cache/elexon_cache.db"))
_db_lock = Lock()


def _get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_cache_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Initialize the SQLite schema if not already present."""
    with _db_lock:
        with _get_connection(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS elexon_raw_cache (
                    delivery_date TEXT PRIMARY KEY,
                    actual_rows_json TEXT NOT NULL,
                    forecast_rows_json TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    cached_epoch REAL NOT NULL
                )
                """
            )
            conn.commit()


def get_cached_day_rows(
    delivery_date: date,
    max_age_seconds: float | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime] | None:
    """Retrieve cached raw actual and forecast records for a delivery date."""
    try:
        init_cache_db(db_path)
        date_str = delivery_date.isoformat()
        with _db_lock:
            with _get_connection(db_path) as conn:
                cursor = conn.execute(
                    "SELECT actual_rows_json, forecast_rows_json, retrieved_at, cached_epoch FROM elexon_raw_cache WHERE delivery_date = ?",
                    (date_str,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                import time
                if max_age_seconds is not None and (time.time() - row["cached_epoch"]) > max_age_seconds:
                    return None

                actual_rows = json.loads(row["actual_rows_json"])
                forecast_rows = json.loads(row["forecast_rows_json"])
                retrieved_at = datetime.fromisoformat(row["retrieved_at"])
                return actual_rows, forecast_rows, retrieved_at
    except Exception as exc:
        logger.warning("Could not read from SQLite cache for %s: %s", delivery_date, exc)
        return None


def store_cached_day_rows(
    delivery_date: date,
    actual_rows: list[dict[str, Any]],
    forecast_rows: list[dict[str, Any]],
    retrieved_at: datetime,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    """Persist raw actual and forecast records into SQLite."""
    try:
        init_cache_db(db_path)
        date_str = delivery_date.isoformat()
        import time
        with _db_lock:
            with _get_connection(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO elexon_raw_cache (delivery_date, actual_rows_json, forecast_rows_json, retrieved_at, cached_epoch)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(delivery_date) DO UPDATE SET
                        actual_rows_json=excluded.actual_rows_json,
                        forecast_rows_json=excluded.forecast_rows_json,
                        retrieved_at=excluded.retrieved_at,
                        cached_epoch=excluded.cached_epoch
                    """,
                    (
                        date_str,
                        json.dumps(actual_rows),
                        json.dumps(forecast_rows),
                        retrieved_at.isoformat(),
                        time.time(),
                    ),
                )
                conn.commit()
    except Exception as exc:
        logger.warning("Could not persist to SQLite cache for %s: %s", delivery_date, exc)


def clear_persistent_cache(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Empty the persistent cache."""
    try:
        init_cache_db(db_path)
        with _db_lock:
            with _get_connection(db_path) as conn:
                conn.execute("DELETE FROM elexon_raw_cache")
                conn.commit()
    except Exception as exc:
        logger.warning("Could not clear SQLite cache: %s", exc)
