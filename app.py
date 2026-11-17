"""Streamlit app: password screen, questions, answers with sources, thumbs feedback.

    streamlit run app.py

Settings come from environment variables: .env locally, root-level secrets on Streamlit
Cloud (APP_PASSWORD, OPENAI_API_KEY, OPENAI_MODEL, DATABASE_URL_READER,
DATABASE_URL_LOGGER, EMBEDDING_BACKEND). All logic lives in src/vnmacro.

Local run against Neon (uses the NEON_* URLs from .env):

    DB_TARGET=neon streamlit run app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dotenv import load_dotenv  # noqa: E402

from vnmacro import config  # noqa: E402
from vnmacro.app.helpers import (  # noqa: E402
    STEP_LABELS,
    data_note,
    db_target_env,
    details_markdown,
    feedback_row,
    local_today,
    password_ok,
)

load_dotenv()
os.environ.update(db_target_env(dict(os.environ)))  # DB_TARGET=neon: local run on Neon
st.set_page_config(page_title=config.APP_TITLE, page_icon="📊")


@st.cache_resource(show_spinner="Đang khởi động trợ lý...")
def get_agent():
    """The agent, built once per server process."""
    from vnmacro.agent.agent import build_agent

    return build_agent()


@st.cache_data(ttl=3600, show_spinner=False)
def get_data_note() -> str:
    """Data-date note, refreshed hourly."""
    from vnmacro.app.service import fetch_data_dates

    return data_note(*fetch_data_dates(os.environ["DATABASE_URL_READER"]))


def login() -> bool:
    """Password screen; True once the right password was entered in this session."""
    if st.session_state.get("authed"):
        return True
    expected = os.environ.get("APP_PASSWORD")
    st.title(config.APP_TITLE)
    if not expected:
        st.error("Ứng dụng chưa được cấu hình mật khẩu (APP_PASSWORD).")
        return False
    with st.form("login"):
        given = st.text_input("Mật khẩu", type="password")
        if st.form_submit_button("Vào"):
            if password_ok(given, expected):
                st.session_state["authed"] = True
                st.rerun()
            st.error("Mật khẩu không đúng.")
    return False


def ask(question: str) -> None:
    """Run the agent (showing each step) and keep the answer in the session history."""
    agent = get_agent()
    with st.status("Đang xử lý câu hỏi...", expanded=True) as status:

        def on_step(step: str) -> None:
            label = STEP_LABELS.get(step, step)
            status.update(label=label)
            status.write(label)

        res = agent.ask(question, today=local_today(), on_step=on_step)
        done = "Đã xong" if res.status == "ok" else "Có lỗi khi xử lý"
        status.update(label=done, state="complete", expanded=False)
    period = res.period
    st.session_state["history"].append(
        {
            "question": question,
            "text": res.text,
            "route": res.route,
            "period": f"{period.start} → {period.end}"
            if period and period.start
            else None,
            "rag_query": res.rag_query,
            "sql": res.sql.sql if res.sql else None,
            "request_id": res.request_id,
        }
    )


def send_feedback(item: dict, rating: str) -> None:
    """Store one thumbs up/down with the optional comment."""
    from vnmacro.app.service import write_feedback

    rid = item["request_id"]
    comment = st.session_state.get(f"comment_{rid}")
    ok = write_feedback(
        os.environ["DATABASE_URL_LOGGER"], feedback_row(rid, rating, comment)
    )
    st.session_state["feedback"][rid] = rating if ok else "error"


def show_answer(item: dict) -> None:
    """One question and its answer, details and feedback controls."""
    with st.chat_message("user"):
        st.markdown(item["question"])
    with st.chat_message("assistant"):
        st.markdown(item["text"])
        if item["route"]:
            with st.expander("Chi tiết"):
                st.markdown(
                    details_markdown(item["route"], item["period"], item["rag_query"])
                )
                if item["sql"]:
                    st.code(item["sql"], language="sql")
        rid = item["request_id"]
        sent = st.session_state["feedback"].get(rid)
        if sent in ("up", "down"):
            st.caption("Cảm ơn bạn đã góp ý!")
        else:
            if sent == "error":
                st.caption("Chưa lưu được góp ý, bạn thử lại nhé.")
            st.text_input(
                "Góp ý (không bắt buộc)",
                key=f"comment_{rid}",
                max_chars=config.FEEDBACK_MAX_CHARS,
            )
            up, down, _ = st.columns([1, 1, 6])
            up.button("👍", key=f"up_{rid}", on_click=send_feedback, args=(item, "up"))
            down.button(
                "👎", key=f"down_{rid}", on_click=send_feedback, args=(item, "down")
            )


def main() -> None:
    """Page layout."""
    if not login():
        return
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("feedback", {})
    st.title(config.APP_TITLE)
    st.caption(get_data_note())

    pending = None
    if not st.session_state["history"]:
        st.markdown("**Bạn có thể thử:**")
        for i, q in enumerate(config.APP_SUGGESTED_QUESTIONS):
            if st.button(q, key=f"suggest_{i}"):
                pending = q
    for item in st.session_state["history"]:
        show_answer(item)
    question = st.chat_input("Nhập câu hỏi về cổ phiếu, chỉ số, kinh tế vĩ mô...")
    if question or pending:
        ask(question or pending)
        st.rerun()


main()
