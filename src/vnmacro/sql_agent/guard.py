"""Safety check for generated SQL (layer 1; the read-only database role is layer 2).

A query passes only if it is exactly one SELECT (WITH ... SELECT and set operations
allowed) that reads allowed tables in allowed schemas, writes nothing anywhere (also not
inside a CTE), has no SELECT ... INTO, no row locks and calls no blocked function. A
missing or too large LIMIT is not a reason to block: it is set to the maximum.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from vnmacro import config

# Statement nodes that write or change anything, or that sqlglot could not parse as a
# query (Command). Looked up by name so a node missing in a sqlglot version is skipped.
_FORBIDDEN_NODE_NAMES = (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterTable",
    "TruncateTable", "Command", "Copy", "Set", "Transaction", "Commit", "Rollback",
    "Grant", "Revoke", "Use", "Pragma", "Analyze", "Refresh", "Cache", "Uncache",
)  # fmt: skip
FORBIDDEN_NODES: tuple[type, ...] = tuple(
    getattr(exp, n) for n in _FORBIDDEN_NODE_NAMES if hasattr(exp, n)
)
QUERY_ROOTS: tuple[type, ...] = (exp.Select, exp.SetOperation)


@dataclass(frozen=True)
class CheckResult:
    """Outcome of the check: the SQL to run (LIMIT fixed) or the reason for blocking."""

    ok: bool
    sql: str | None = None
    error: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def function_name(node: exp.Func) -> str:
    """Lower-case name of a function call as written (known or anonymous)."""
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def is_blocked_function(
    name: str,
    blocked: tuple[str, ...] = config.SQL_BLOCKED_FUNCTIONS,
    prefixes: tuple[str, ...] = config.SQL_BLOCKED_FUNCTION_PREFIXES,
) -> bool:
    """True if a function name is on the block list (exact name or prefix)."""
    name = name.lower()
    return name in blocked or name.startswith(prefixes)


def _limit_value(node: exp.Expression | None) -> int | None:
    """Row count of a LIMIT n / FETCH FIRST n clause if it is a plain integer."""
    if isinstance(node, exp.Limit):
        value = node.expression
    elif isinstance(node, exp.Fetch):
        value = node.args.get("count")
    else:
        return None
    if isinstance(value, exp.Literal) and not value.is_string:
        try:
            return int(value.this)
        except ValueError:
            return None
    return None


def enforce_limit(
    tree: exp.Query, original_sql: str, max_rows: int = config.SQL_MAX_ROWS
) -> tuple[str, str | None]:
    """Return SQL with an outer LIMIT <= max_rows and a note when it had to change."""
    current = tree.args.get("limit")
    value = _limit_value(current)
    if value is not None and value <= max_rows:
        return original_sql, None
    fixed = tree.copy().limit(max_rows).sql(dialect="postgres")
    if current is None:
        note = f"LIMIT was missing; set to {max_rows}."
    elif value is not None:
        note = f"LIMIT {value} lowered to {max_rows}."
    else:
        clause = current.sql(dialect="postgres")
        note = f"LIMIT clause '{clause}' replaced by {max_rows}."
    return fixed, note


def check_sql(
    sql: str,
    allowed_tables: tuple[str, ...] | list[str],
    max_rows: int = config.SQL_MAX_ROWS,
    allowed_schemas: tuple[str, ...] = config.SQL_ALLOWED_SCHEMAS,
    blocked_functions: tuple[str, ...] = config.SQL_BLOCKED_FUNCTIONS,
    blocked_prefixes: tuple[str, ...] = config.SQL_BLOCKED_FUNCTION_PREFIXES,
) -> CheckResult:
    """Check one generated query; on success return it with the LIMIT enforced."""
    text = sql.strip().rstrip(";").strip()
    if not text:
        return CheckResult(False, error="Empty SQL.")
    try:
        statements = [s for s in sqlglot.parse(text, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        return CheckResult(False, error=f"SQL could not be parsed: {e}")
    if len(statements) != 1:
        return CheckResult(
            False, error=f"Expected exactly one statement, got {len(statements)}."
        )
    tree = statements[0]
    if not isinstance(tree, QUERY_ROOTS):
        return CheckResult(False, error="Only a SELECT query is allowed.")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            kind = type(node).__name__.upper()
            return CheckResult(False, error=f"{kind} is not allowed (only reads).")
        if isinstance(node, exp.Into):
            return CheckResult(False, error="SELECT ... INTO is not allowed.")
        if isinstance(node, exp.Lock):
            return CheckResult(False, error="FOR UPDATE / FOR SHARE is not allowed.")
        if isinstance(node, exp.Func):
            name = function_name(node)
            if is_blocked_function(name, blocked_functions, blocked_prefixes):
                return CheckResult(False, error=f"Function {name}() is not allowed.")
        if isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func):
            schema = str(node.this.name).lower()
            if schema not in allowed_schemas:
                return CheckResult(
                    False, error=f"Schema {schema} is not allowed (only public)."
                )

    ctes = {str(c.alias).lower() for c in tree.find_all(exp.CTE)}
    allowed = {t.lower() for t in allowed_tables}
    for table in tree.find_all(exp.Table):
        name, schema = str(table.name).lower(), str(table.db).lower()
        if not name:  # a function used as a table, e.g. generate_series(...)
            continue
        if table.catalog:
            return CheckResult(False, error=f"Database prefix is not allowed: {table}.")
        if schema and schema not in allowed_schemas:
            return CheckResult(
                False, error=f"Schema {schema} is not allowed (only public)."
            )
        if name not in allowed and not (not schema and name in ctes):
            return CheckResult(False, error=f"Unknown table {name}.")

    fixed, note = enforce_limit(tree, text, max_rows)
    return CheckResult(True, sql=fixed, notes=(note,) if note else ())
