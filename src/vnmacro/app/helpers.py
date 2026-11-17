"""Pure helpers for the Streamlit app (no Streamlit import, no I/O)."""

from __future__ import annotations

import datetime as dt
import hmac
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from vnmacro import config


def password_ok(given: str | None, expected: str | None) -> bool:
    """True when the typed password equals APP_PASSWORD (never when it is unset)."""
    if not expected or given is None:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def local_today(tz: str = config.MARKET_TZ, now: dt.datetime | None = None) -> dt.date:
    """Today's date in Vietnam (the server may run in UTC)."""
    moment = now or dt.datetime.now(dt.timezone.utc)
    return moment.astimezone(ZoneInfo(tz)).date()


def feedback_row(
    request_id: str,
    rating: str,
    comment: str | None,
    session_id: str | None = None,
    max_chars: int = config.FEEDBACK_MAX_CHARS,
    ratings: tuple[str, ...] = config.FEEDBACK_RATINGS,
) -> dict[str, Any]:
    """Validated app.feedback row; ValueError for a bad id or rating."""
    if rating not in ratings:
        raise ValueError(f"rating must be one of {ratings}")
    rid = str(uuid.UUID(request_id))
    sid = str(uuid.UUID(session_id)) if session_id else None
    text = (comment or "").strip()[:max_chars] or None
    return {"request_id": rid, "session_id": sid, "rating": rating, "comment": text}


ROUTE_LABELS: dict[str, str] = {
    "sql": "Số liệu (SQL)",
    "rag": "Tài liệu (RAG)",
    "both": "Số liệu + tài liệu",
    "explain": "Giải thích kiến thức chung",
    "out_of_scope": "Ngoài phạm vi",
}


def details_markdown(
    route: str | None, period: str | None, rag_query: str | None
) -> str:
    """Markdown for the 'Chi tiết' box (the SQL is shown separately as code)."""
    lines = [f"- **Route:** {ROUTE_LABELS.get(route or '', route or '-')}"]
    if period:
        lines.append(f"- **Kỳ dữ liệu:** {period}")
    if rag_query:
        lines.append(f"- **Tìm tài liệu với:** {rag_query}")
    return "\n".join(lines)


STEP_LABELS: dict[str, str] = {
    "route": "Đang phân loại câu hỏi...",
    "retrieve": "Đang tìm tài liệu...",
    "sql": "Đang tra số liệu...",
    "answer": "Đang viết câu trả lời...",
}


def db_target_env(env: dict[str, str | None]) -> dict[str, str]:
    """Environment updates for DB_TARGET=neon (local runs against Neon); else none.

    Points DATABASE_URL_READER / _LOGGER at the NEON_* URLs and defaults the embedding
    backend to openai (Neon holds only the OpenAI vectors).
    """
    if (env.get("DB_TARGET") or "").lower() != "neon":
        return {}
    updates = {}
    for name in ("DATABASE_URL_READER", "DATABASE_URL_LOGGER"):
        value = env.get(f"NEON_{name}")
        if not value:
            raise SystemExit(f"DB_TARGET=neon but NEON_{name} is not set in .env")
        updates[name] = value
    updates["EMBEDDING_BACKEND"] = env.get("NEON_EMBEDDING_BACKEND") or "openai"
    return updates
