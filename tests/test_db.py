import threading

import pytest

from vnmacro import db


class FakeConn:
    def __init__(self):
        self.closed, self.broken = False, False

    def close(self):
        self.closed = True


class Lost(Exception):
    pass


def setup_function():
    db.close_all()


def counting_connect():
    made = []

    def connect(url):
        made.append(FakeConn())
        return made[-1]

    return connect, made


def test_connection_is_reused_across_calls_and_threads():
    connect, made = counting_connect()
    seen = []
    db.with_connection("u", seen.append, connect)
    t = threading.Thread(target=db.with_connection, args=("u", seen.append, connect))
    t.start()
    t.join()
    assert len(made) == 1 and seen == [made[0], made[0]]


def test_concurrent_borrowers_get_different_connections():
    connect, made = counting_connect()
    a = db.acquire("u", connect)
    b = db.acquire("u", connect)
    assert a is not b and len(made) == 2
    db.release("u", a)
    db.release("u", b)
    assert db.acquire("u", connect) in (a, b)


def test_closed_connection_is_not_reused_and_pool_is_bounded():
    connect, made = counting_connect()
    a = db.acquire("u", connect)
    a.closed = True
    db.release("u", a)
    assert db.acquire("u", connect) is not a
    conns = [FakeConn() for _ in range(3)]
    for c in conns:
        db.release("v", c, max_idle=2)
    assert conns[2].closed and not conns[0].closed


def test_with_connection_retries_once_when_connection_lost():
    connect, made = counting_connect()
    calls = []

    def fn(conn):
        calls.append(conn)
        if len(calls) == 1:
            conn.broken = True
            raise Lost("server closed the connection")
        return "ok"

    assert db.with_connection("u", fn, connect, lost=(Lost,)) == "ok"
    assert len(made) == 2 and made[0].closed and calls == made


def test_with_connection_does_not_retry_query_errors_and_keeps_connection():
    connect, made = counting_connect()
    calls = []

    def fn(conn):
        calls.append(conn)
        raise Lost("query error, connection fine")

    with pytest.raises(Lost):
        db.with_connection("u", fn, connect, lost=(Lost,))
    assert len(calls) == 1 and db.acquire("u", connect) is made[0]


def test_with_connection_gives_up_after_second_loss():
    def fn(conn):
        conn.broken = True
        raise Lost("down")

    with pytest.raises(Lost):
        db.with_connection("u", fn, lambda url: FakeConn(), lost=(Lost,))
