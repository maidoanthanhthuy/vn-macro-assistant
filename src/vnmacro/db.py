"""Reusable database connections: a small pool of open connections per URL.

Opening a connection to a remote database (Neon) costs seconds, so the agent keeps open
autocommit connections and reuses them. Each call borrows one connection for itself and
gives it back afterwards, so the explicit transactions of concurrent requests never mix,
and connections survive across threads (Streamlit runs every script rerun in a new
thread). A connection closed by the server (idle timeout, compute suspended) is
dropped, a new one is opened and the call is retried once.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")
MAX_IDLE_PER_URL = 4  # open connections kept for reuse per URL
_lock = threading.Lock()
_idle: dict[str, list[Any]] = {}


def _connect(url: str) -> Any:
    """Open one autocommit connection."""
    import psycopg

    return psycopg.connect(url, autocommit=True)


def _usable(conn: Any) -> bool:
    """True when the connection is still open and not broken."""
    return not (conn.closed or getattr(conn, "broken", False))


def _close(conn: Any) -> None:
    """Close a connection, ignoring errors from an already broken one."""
    try:
        conn.close()
    except Exception:
        pass


def acquire(url: str, connect: Callable[[str], Any] = _connect) -> Any:
    """Borrow an idle open connection for url, or open a new one."""
    with _lock:
        idle = _idle.setdefault(url, [])
        while idle:
            conn = idle.pop()
            if _usable(conn):
                return conn
            _close(conn)
    return connect(url)


def release(url: str, conn: Any, max_idle: int = MAX_IDLE_PER_URL) -> None:
    """Give a connection back (closed instead when broken or the pool is full)."""
    with _lock:
        idle = _idle.setdefault(url, [])
        if _usable(conn) and len(idle) < max_idle:
            idle.append(conn)
            return
    _close(conn)


def with_connection(
    url: str,
    fn: Callable[[Any], T],
    connect: Callable[[str], Any] = _connect,
    lost: tuple[type[BaseException], ...] | None = None,
) -> T:
    """Run fn(conn) on a borrowed connection; reconnect and retry once if it was lost.

    Only a lost connection is retried (the error is one of `lost`, default
    psycopg.OperationalError, and the connection is now broken or closed); query
    errors are raised at once.
    """
    if lost is None:
        import psycopg

        lost = (psycopg.OperationalError,)
    for attempt in (1, 2):
        conn = acquire(url, connect)
        try:
            result = fn(conn)
        except lost:
            gone = not _usable(conn)
            release(url, conn)
            if attempt == 2 or not gone:
                raise
            continue
        except BaseException:
            release(url, conn)
            raise
        release(url, conn)
        return result
    raise AssertionError("unreachable")


def close_all() -> None:
    """Close every idle connection."""
    with _lock:
        conns = [c for idle in _idle.values() for c in idle]
        _idle.clear()
    for conn in conns:
        _close(conn)
