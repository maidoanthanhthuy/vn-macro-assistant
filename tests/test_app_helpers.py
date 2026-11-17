import datetime as dt
import uuid

import pytest

from vnmacro.app.helpers import (
    STEP_LABELS,
    db_target_env,
    details_markdown,
    feedback_row,
    local_today,
    password_ok,
)


def test_password_ok():
    assert password_ok("s3cret", "s3cret")
    assert not password_ok("wrong", "s3cret")
    assert not password_ok("", "")  # no password configured: never open
    assert not password_ok(None, "s3cret")
    assert not password_ok("x", None)


def test_local_today_uses_vietnam_time():
    late_utc = dt.datetime(2026, 11, 16, 20, 0, tzinfo=dt.timezone.utc)
    assert local_today("Asia/Ho_Chi_Minh", late_utc) == dt.date(2026, 11, 17)


def test_feedback_row():
    rid = str(uuid.uuid4())
    assert feedback_row(rid, "up", "  hay  ") == {
        "request_id": rid,
        "session_id": None,
        "rating": "up",
        "comment": "hay",
    }
    assert feedback_row(rid, "down", "   ")["comment"] is None
    assert feedback_row(rid, "down", None)["comment"] is None
    assert len(feedback_row(rid, "up", "x" * 50, max_chars=10)["comment"]) == 10
    with pytest.raises(ValueError):
        feedback_row(rid, "meh", None)
    with pytest.raises(ValueError):
        feedback_row("not-a-uuid", "up", None)
    sid = str(uuid.uuid4())
    assert feedback_row(rid, "up", None, sid)["session_id"] == sid
    with pytest.raises(ValueError):
        feedback_row(rid, "up", None, "not-a-uuid")


def test_details_markdown():
    text = details_markdown("both", "2026-10-01 → 2026-10-31", "CPI?")
    assert text.splitlines() == [
        "- **Route:** Số liệu + tài liệu",
        "- **Kỳ dữ liệu:** 2026-10-01 → 2026-10-31",
        "- **Tìm tài liệu với:** CPI?",
    ]
    assert details_markdown("sql", None, None) == "- **Route:** Số liệu (SQL)"


def test_db_target_env():
    env = {"NEON_DATABASE_URL_READER": "r", "NEON_DATABASE_URL_LOGGER": "l"}
    assert db_target_env(env) == {}
    assert db_target_env({**env, "DB_TARGET": "NEON"}) == {
        "DATABASE_URL_READER": "r",
        "DATABASE_URL_LOGGER": "l",
        "EMBEDDING_BACKEND": "openai",
    }
    with pytest.raises(SystemExit):
        db_target_env({"DB_TARGET": "neon"})


def test_step_labels_cover_agent_steps():
    from vnmacro.agent.agent import STEPS

    assert set(STEP_LABELS) == set(STEPS)
