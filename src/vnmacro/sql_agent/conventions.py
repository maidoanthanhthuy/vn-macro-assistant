"""Load the SQL conventions written for the LLM (prompts/sql_conventions.md)."""

from __future__ import annotations

from pathlib import Path

from vnmacro import config


def load_sql_conventions(path: Path = config.SQL_CONVENTIONS_FILE) -> str:
    """Return the conventions file verbatim."""
    return path.read_text(encoding="utf-8")
