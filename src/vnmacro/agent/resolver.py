"""Turn the router's time reference into a concrete period (pure code, no LLM).

- latest + rag/both: the period of the newest NSO monthly report in rag.documents.
- latest + sql: left open; Text-to-SQL finds the newest period in its own tables.
- specific/range: checked (start <= end) and noted when outside the data coverage.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from vnmacro import config
from vnmacro.agent.router import RouteDecision
from vnmacro.sql_agent.context import Coverage

Period = tuple[dt.date, dt.date]
# route -> data sources whose coverage the period is checked against
ROUTE_SOURCES: dict[str, tuple[str, ...]] = {
    "sql": ("sql",),
    "rag": ("rag",),
    "both": ("sql", "rag"),
}


@dataclass(frozen=True)
class DataCoverage:
    """Date range of the numeric tables and the documents, plus the newest report."""

    sql: Period
    rag: Period
    latest_report: Period | None


@dataclass(frozen=True)
class ResolvedPeriod:
    """Period after resolution (None = open) and notes for the answer step."""

    start: dt.date | None
    end: dt.date | None
    notes: tuple[str, ...] = ()


def as_date(value: Any, end: bool = False) -> dt.date:
    """Date from a period value; an int year becomes its first (or last) day."""
    if isinstance(value, int):
        return dt.date(value, 12, 31) if end else dt.date(value, 1, 1)
    return value


def data_coverage(
    coverage: list[Coverage],
    documents: list[tuple[str, str, dt.date, dt.date]],
    latest_type: str = config.LATEST_REPORT_TYPE,
) -> DataCoverage:
    """Coverage from public table ranges and (doc_type, period, start, end) rows."""
    sql = (
        min(as_date(c.first) for c in coverage),
        max(as_date(c.last, end=True) for c in coverage),
    )
    rag = (min(d[2] for d in documents), max(d[3] for d in documents))
    reports = [(d[2], d[3]) for d in documents if d[0] == latest_type]
    return DataCoverage(sql, rag, max(reports, key=lambda p: p[1], default=None))


def resolve_period(decision: RouteDecision, cov: DataCoverage) -> ResolvedPeriod:
    """Concrete period for a router decision (see module docstring)."""
    if decision.route == "out_of_scope" or decision.time_ref == "none":
        return ResolvedPeriod(None, None)
    if decision.time_ref == "latest":
        if decision.route == "sql":
            return ResolvedPeriod(None, None)
        if cov.latest_report is None:
            return ResolvedPeriod(None, None, ("No monthly report in the documents.",))
        return ResolvedPeriod(*cov.latest_report)

    start = decision.period_start or decision.period_end
    end = decision.period_end or decision.period_start
    if start is None or end is None:
        return ResolvedPeriod(None, None, ("No period dates given by the router.",))
    if start > end:
        note = f"Invalid period: start {start} is after end {end}; period ignored."
        return ResolvedPeriod(None, None, (note,))
    notes = []
    for source in ROUTE_SOURCES[decision.route]:
        first, last = getattr(cov, source)
        if start < first or end > last:
            part = "outside" if end < first or start > last else "partly outside"
            notes.append(
                f"Period {start}..{end} is {part} the {source} data ({first}..{last})."
            )
    return ResolvedPeriod(start, end, tuple(notes))
