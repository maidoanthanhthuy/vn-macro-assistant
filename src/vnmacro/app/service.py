"""Database I/O for the Streamlit app: data dates for the note, feedback rows."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from vnmacro import config

log = logging.getLogger(__name__)

_DATES_SQL = """
SELECT (SELECT max(date) FROM public.daily_prices),
       (SELECT max(reference_period) FROM rag.documents WHERE doc_type = %(doc_type)s)
"""
_FEEDBACK_SQL = (
    "INSERT INTO app.feedback (request_id, rating, comment) "
    "VALUES (%(request_id)s, %(rating)s, %(comment)s)"
)


def fetch_data_dates(url: str) -> tuple[dt.date | None, str | None]:
    """(latest price date, latest NSO monthly report period), as the reader."""
    from vnmacro.db import with_connection

    def run(conn: Any) -> tuple[Any, Any]:
        row = conn.execute(_DATES_SQL, {"doc_type": config.LATEST_REPORT_TYPE})
        return tuple(row.fetchone())

    return with_connection(url, run)


def write_feedback(url: str, row: dict[str, Any]) -> bool:
    """Insert one app.feedback row as the logger; False (and a warning) on failure."""
    from vnmacro.db import with_connection

    try:
        with_connection(url, lambda conn: conn.execute(_FEEDBACK_SQL, row))
        return True
    except Exception as e:  # feedback must never break the app
        log.warning("feedback insert failed: %s", e)
        return False
