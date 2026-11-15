"""Build the database description ("schema context") sent to the LLM for Text-to-SQL.

Everything is read from the PostgreSQL catalog and the data, as the read-only role
(DATABASE_URL_READER). The text is deterministic: same data -> same text, so it can
sit in a cached prompt prefix.

Preview from the repository root (database running, .env filled in):

    PYTHONPATH=src python -m vnmacro.sql_agent.context
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from vnmacro import config


@dataclass(frozen=True)
class Column:
    """One table column from the catalog."""

    name: str
    type: str
    nullable: bool
    comment: str | None


@dataclass(frozen=True)
class Table:
    """One table: catalog facts plus either sample rows or all rows."""

    name: str
    comment: str | None
    columns: tuple[Column, ...]
    constraints: tuple[str, ...]  # pg_get_constraintdef output, PK first
    row_count: int
    rows: tuple[tuple[Any, ...], ...]  # sample rows, or all rows for full tables
    row_columns: tuple[str, ...]  # column names of rows (samples may skip some)
    rows_order: str  # human description of the row order, e.g. "date DESC, symbol"
    full: bool  # True when rows holds the whole table


@dataclass(frozen=True)
class Coverage:
    """Period range of a table, optionally per group (e.g. per symbol)."""

    table: str
    column: str
    first: Any
    last: Any
    group_column: str | None = None
    groups: tuple[tuple[Any, Any, Any, int], ...] = ()  # (group, first, last, rows)
    only_differing_last: bool = False  # list only groups ending before/after `last`


# ---------- pure formatting ----------


def format_value(
    value: Any, max_chars: int | None = None, decimals: int | None = None
) -> str:
    """Render one cell as compact text (NULL, ISO dates, plain decimals)."""
    if decimals is not None and isinstance(value, (Decimal, float)):
        step = Decimal(1).scaleb(-decimals)
        dec = value if isinstance(value, Decimal) else Decimal(repr(value))
        if dec.as_tuple().exponent < -decimals:  # only shorten, never pad
            value = dec.quantize(step, rounding=ROUND_HALF_UP)
    if value is None:
        text = "NULL"
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (dt.date, dt.datetime)):
        text = value.isoformat()
    elif isinstance(value, Decimal):
        text = format(value, "f")
    else:
        text = " ".join(str(value).split())
    if max_chars is not None and len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def format_rows(
    columns: list[str] | tuple[str, ...],
    rows: tuple[tuple[Any, ...], ...] | list[tuple[Any, ...]],
    max_chars: int | None = None,
    decimals: int | None = None,
) -> str:
    """Pipe-separated header line plus one line per row."""
    lines = [" | ".join(columns)]
    lines += [
        " | ".join(format_value(v, max_chars, decimals) for v in row) for row in rows
    ]
    return "\n".join(lines)


def _matching_paren(text: str, start: int) -> int:
    """Index of the ')' that closes the '(' at text[start]; -1 if unbalanced."""
    depth = 0
    for i in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            return i
    return -1


def clean_constraint(definition: str) -> str:
    """Shorten pg_get_constraintdef text: no casts, IN (..), no redundant parens."""
    text = re.sub(r"::\w+(?: varying| precision)?(?:\[\])?", "", definition)
    text = re.sub(r"= ANY \(ARRAY\[(.*?)\]\)", r"IN (\1)", text)
    text = re.sub(r"\((-?\d+(?:\.\d+)?)\)", r"\1", text)  # (0) -> 0
    prefix = "CHECK ("
    if text.startswith(prefix + "(") and text.endswith("))"):
        inner = len(prefix)
        if _matching_paren(text, inner) == len(text) - 2:
            text = prefix + text[inner + 1 : -2] + ")"
    return text


def sample_order(
    primary_key: list[str] | tuple[str, ...], period_column: str | None
) -> list[tuple[str, bool]]:
    """Row order for samples: newest period first, then the primary key ascending."""
    order = [(period_column, True)] if period_column else []
    order += [(c, False) for c in primary_key if c != period_column]
    return order


def order_text(order: list[tuple[str, bool]]) -> str:
    """Describe an order as SQL-like text, e.g. 'date DESC, symbol'."""
    return ", ".join(f"{c} DESC" if desc else c for c, desc in order)


def sample_columns(
    columns: list[str] | tuple[str, ...], exclude: tuple[str, ...] = ()
) -> list[str]:
    """Columns to show in sample rows, in table order, minus the excluded ones."""
    return [c for c in columns if c not in exclude]


def sample_note(
    order: list[tuple[str, bool]],
    period_column: str | None = None,
    key: tuple[str, tuple[str, ...]] | None = None,
) -> str:
    """Describe how sample rows were picked, e.g. 'date = latest, symbol IN (..)'."""
    text = f"ordered by {order_text(order)}"
    if key and period_column:
        values = ", ".join(key[1])
        text = f"{period_column} = latest, {key[0]} IN ({values}); {text}"
    return text


def coverage_groups(cov: Coverage) -> tuple[tuple[Any, Any, Any, int], ...]:
    """Groups to list: all, or only those whose last period differs from the table's."""
    if not cov.only_differing_last:
        return cov.groups
    return tuple(g for g in cov.groups if g[2] != cov.last)


def format_table(
    table: Table, max_chars: int | None = None, decimals: int | None = None
) -> str:
    """Markdown section for one table: comment, columns, constraints, rows."""
    lines = [f"## {table.name} ({table.row_count} rows)"]
    if table.comment:
        lines.append(table.comment)
    lines.append("")
    lines.append("Columns:")
    for col in table.columns:
        null = ", nullable" if col.nullable else ""
        note = f": {col.comment}" if col.comment else ""
        lines.append(f"- {col.name} ({col.type}{null}){note}")
    if table.constraints:
        lines.append("")
        lines.append("Constraints:")
        lines += [f"- {clean_constraint(c)}" for c in table.constraints]
    lines.append("")
    if table.full:
        lines.append(f"All rows ({table.rows_order}):")
        lines.append(format_rows(table.row_columns, table.rows))
    else:
        lines.append(f"Sample rows ({table.rows_order}):")
        lines.append(format_rows(table.row_columns, table.rows, max_chars, decimals))
    return "\n".join(lines)


def format_coverage(items: list[Coverage] | tuple[Coverage, ...]) -> str:
    """Markdown section with min/max period per table and per group."""
    lines = ["## Data coverage (min .. max)"]
    for cov in items:
        first, last = format_value(cov.first), format_value(cov.last)
        lines.append(f"- {cov.table}.{cov.column}: {first} .. {last}")
        groups = coverage_groups(cov)
        if groups:
            label = (
                f"  {cov.group_column} values with a different last {cov.column}:"
                if cov.only_differing_last
                else f"  By {cov.group_column}:"
            )
            lines.append(label)
            for group, g_first, g_last, n in groups:
                lines.append(
                    f"  - {format_value(group)}: {format_value(g_first)} .. "
                    f"{format_value(g_last)} ({n} rows)"
                )
    return "\n".join(lines)


def build_schema_context(
    schema: str,
    tables: list[Table] | tuple[Table, ...],
    coverage: list[Coverage] | tuple[Coverage, ...],
    max_chars: int | None = config.SQL_CONTEXT_MAX_VALUE_CHARS,
    decimals: int | None = config.SQL_CONTEXT_SAMPLE_DECIMALS,
) -> str:
    """Assemble the full schema context text (tables, coverage) in a fixed order."""
    header = (
        f"# Database: PostgreSQL, schema {schema} (read-only)\n"
        "Prices, macro indicators, monthly CPI and SBV policy rate changes for Vietnam."
    )
    parts = [header]
    ordered = sorted(tables, key=lambda t: t.name)
    parts += [format_table(t, max_chars, decimals) for t in ordered]
    if coverage:
        parts.append(format_coverage(sorted(coverage, key=lambda c: c.table)))
    return "\n\n".join(parts) + "\n"


def size_report(
    text: str, chars_per_token: int = config.SQL_CONTEXT_CHARS_PER_TOKEN
) -> str:
    """One line with the character count and a rough token estimate."""
    n = len(text)
    tokens = round(n / chars_per_token)
    return f"{n} characters, ~{tokens} tokens (chars / {chars_per_token})"


# ---------- I/O: catalog and data queries ----------

_TABLES_SQL = """
SELECT c.relname, obj_description(c.oid, 'pg_class')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relkind IN ('r', 'p')
ORDER BY c.relname
"""
_COLUMNS_SQL = """
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull,
       col_description(c.oid, a.attnum)
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relkind IN ('r', 'p') AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""
# PK first, then FK, then CHECK; by name inside each kind
_CONSTRAINTS_SQL = """
SELECT c.relname, pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND con.contype IN ('p', 'f', 'c')
ORDER BY c.relname, array_position(ARRAY['p', 'f', 'c'], con.contype::text),
         con.conname
"""
_PK_SQL = """
SELECT c.relname, a.attname
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
WHERE n.nspname = %s AND con.contype = 'p'
ORDER BY c.relname, k.ord
"""


def _group(rows: list[tuple[Any, ...]]) -> dict[str, list[tuple[Any, ...]]]:
    """Group catalog rows by their first field (table name)."""
    out: dict[str, list[tuple[Any, ...]]] = {}
    for row in rows:
        out.setdefault(row[0], []).append(row[1:])
    return out


def fetch_tables(
    conn: Any,
    schema: str = config.SQL_CONTEXT_SCHEMA,
    full_tables: tuple[str, ...] = config.SQL_CONTEXT_FULL_TABLES,
    coverage_columns: dict[
        str, tuple[str, str | None, bool]
    ] = config.SQL_CONTEXT_COVERAGE,
    n_samples: int = config.SQL_CONTEXT_SAMPLE_ROWS,
    sample_keys: dict[
        str, tuple[str, tuple[str, ...]]
    ] = config.SQL_CONTEXT_SAMPLE_KEYS,
    sample_exclude: dict[str, tuple[str, ...]] = config.SQL_CONTEXT_SAMPLE_EXCLUDE,
) -> list[Table]:
    """Read table, column and constraint facts plus sample or all rows."""
    from psycopg import sql

    with conn.cursor() as cur:
        tables = cur.execute(_TABLES_SQL, (schema,)).fetchall()
        columns = _group(cur.execute(_COLUMNS_SQL, (schema,)).fetchall())
        constraints = _group(cur.execute(_CONSTRAINTS_SQL, (schema,)).fetchall())
        pks = _group(cur.execute(_PK_SQL, (schema,)).fetchall())

        out = []
        for name, comment in tables:
            ident = sql.Identifier(schema, name)
            pk = [r[0] for r in pks.get(name, [])]
            full = name in full_tables
            period = None if full else coverage_columns.get(name, (None,))[0]
            key = None if full else sample_keys.get(name)
            order = sample_order(pk, period)
            names = [c[0] for c in columns.get(name, [])]
            excluded = () if full else sample_exclude.get(name, ())
            shown = sample_columns(names, excluded)
            order_sql = sql.SQL(", ").join(
                sql.SQL("{} DESC" if desc else "{}").format(sql.Identifier(c))
                for c, desc in order
            )
            query = sql.SQL("SELECT {} FROM {}").format(
                sql.SQL(", ").join(map(sql.Identifier, shown)), ident
            )
            if key and period:
                query += sql.SQL(
                    " WHERE {p} = (SELECT max({p}) FROM {t}) AND {k} = ANY({v})"
                ).format(
                    p=sql.Identifier(period),
                    t=ident,
                    k=sql.Identifier(key[0]),
                    v=sql.Literal(list(key[1])),
                )
            query += sql.SQL(" ORDER BY {}").format(order_sql)
            if not full:
                query += sql.SQL(" LIMIT {}").format(sql.Literal(n_samples))
            rows = cur.execute(query).fetchall()
            count = cur.execute(
                sql.SQL("SELECT count(*) FROM {}").format(ident)
            ).fetchone()[0]
            out.append(
                Table(
                    name=name,
                    comment=comment,
                    columns=tuple(Column(*c) for c in columns.get(name, [])),
                    constraints=tuple(r[0] for r in constraints.get(name, [])),
                    row_count=count,
                    rows=tuple(tuple(r) for r in rows),
                    row_columns=tuple(shown),
                    rows_order=sample_note(order, period, key),
                    full=full,
                )
            )
    return out


def fetch_coverage(
    conn: Any,
    schema: str = config.SQL_CONTEXT_SCHEMA,
    coverage_columns: dict[
        str, tuple[str, str | None, bool]
    ] = config.SQL_CONTEXT_COVERAGE,
) -> list[Coverage]:
    """Query min/max of each period column, per group when a group column is set."""
    from psycopg import sql

    out = []
    with conn.cursor() as cur:
        for table, (column, group, only_differing) in sorted(coverage_columns.items()):
            ident, col = sql.Identifier(schema, table), sql.Identifier(column)
            first, last = cur.execute(
                sql.SQL("SELECT min({c}), max({c}) FROM {t}").format(c=col, t=ident)
            ).fetchone()
            groups: tuple[tuple[Any, Any, Any, int], ...] = ()
            if group:
                g = sql.Identifier(group)
                groups = tuple(
                    tuple(r)
                    for r in cur.execute(
                        sql.SQL(
                            "SELECT {g}, min({c}), max({c}), count(*) FROM {t} "
                            "GROUP BY {g} ORDER BY {g}"
                        ).format(g=g, c=col, t=ident)
                    ).fetchall()
                )
            out.append(
                Coverage(table, column, first, last, group, groups, only_differing)
            )
    return out


def schema_context_from_db(
    url: str | None = None, schema: str = config.SQL_CONTEXT_SCHEMA
) -> str:
    """Connect as the read-only role and return the schema context text."""
    import psycopg
    from dotenv import load_dotenv

    load_dotenv()
    url = url or os.environ.get("DATABASE_URL_READER")
    if not url:
        raise SystemExit("DATABASE_URL_READER is not set in .env")
    with psycopg.connect(url) as conn:
        conn.read_only = True
        tables = fetch_tables(conn, schema)
        coverage = fetch_coverage(conn, schema)
    return build_schema_context(schema, tables, coverage)


def main() -> None:
    """Print the schema context and its size."""
    text = schema_context_from_db()
    print(text)
    print("---")
    print(size_report(text))


if __name__ == "__main__":
    main()
