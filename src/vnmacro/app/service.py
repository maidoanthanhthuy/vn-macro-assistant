"""Database I/O for the Streamlit app: feedback rows."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_FEEDBACK_SQL = (
    "INSERT INTO app.feedback (request_id, session_id, rating, comment) "
    "VALUES (%(request_id)s, %(session_id)s, %(rating)s, %(comment)s)"
)


def write_feedback(url: str, row: dict[str, Any]) -> bool:
    """Insert one app.feedback row as the logger; False (and a warning) on failure."""
    from vnmacro.db import with_connection

    try:
        with_connection(url, lambda conn: conn.execute(_FEEDBACK_SQL, row))
        return True
    except Exception as e:  # feedback must never break the app
        log.warning("feedback insert failed: %s", e)
        return False
