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
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dotenv import load_dotenv  # noqa: E402

from vnmacro import config  # noqa: E402
from vnmacro.app.helpers import (  # noqa: E402
    STEP_LABELS,
    db_target_env,
    details_markdown,
    feedback_row,
    local_today,
    password_ok,
    recent_turns,
)
from vnmacro.app.jobs import QuestionJob, start_job  # noqa: E402

load_dotenv()
os.environ.update(db_target_env(dict(os.environ)))  # DB_TARGET=neon: local run on Neon
st.set_page_config(page_title=config.APP_TITLE, page_icon="📊")


@st.cache_resource(show_spinner="Đang khởi động trợ lý...")
def get_agent():
    """The agent, built once per server process."""
    from vnmacro.agent.agent import build_agent

    return build_agent()


@st.cache_resource
def get_executor() -> ThreadPoolExecutor:
    """Worker threads that answer questions, shared by all sessions."""
    return ThreadPoolExecutor(max_workers=config.APP_QUESTION_WORKERS)


@st.cache_data(ttl=3600, show_spinner=False)
def get_scope_brief() -> str:
    """Short data scope for the main screen (symbols, indicators, dates), hourly."""
    from vnmacro.agent.scope import fetch_scope, format_scope_brief

    return format_scope_brief(fetch_scope(os.environ["DATABASE_URL_READER"]))


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


def start_question(question: str) -> None:
    """Start the agent on a question in a worker thread; keep the job in the session."""
    st.session_state["job"] = start_job(
        get_executor(),
        get_agent().ask,
        question,
        today=local_today(),
        session_id=st.session_state["session_id"],
        turns=recent_turns(st.session_state["history"]),
    )


def wait_for(job: QuestionJob) -> None:
    """Show the job's steps until it ends, then move its answer to the history.

    A rerun during the wait (e.g. a feedback click) stops only this display; the job
    keeps running and the next run waits for it again.
    """
    with st.chat_message("user"):
        st.markdown(job.question)
    with st.status("Đang xử lý câu hỏi...", expanded=True) as status:
        shown = 0
        while True:
            done = job.done  # read before the steps, so no step is missed
            for step in job.steps[shown:]:
                status.write(STEP_LABELS.get(step, step))
            shown = len(job.steps)
            if done:
                break
            label = STEP_LABELS.get(job.steps[-1], "") if job.steps else ""
            status.update(label=label or "Đang xử lý câu hỏi...")
            time.sleep(config.APP_POLL_SECONDS)
        error = job.future.exception()
        ok = error is None and job.future.result().status == "ok"
        label = "Đã xong" if ok else "Có lỗi khi xử lý"
        status.update(label=label, state="complete", expanded=False)
    st.session_state["job"] = None
    if error is None:
        add_to_history(job.question, job.future.result())
    else:
        st.error(config.ANSWER_ERROR_TEXT)


def add_to_history(question: str, res) -> None:
    """Keep an agent result in the session history."""
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
            "short_answer": res.short_answer,
            "standalone": res.standalone_question,
        }
    )


def send_feedback(item: dict, rating: str) -> None:
    """Store one thumbs up/down with the optional comment."""
    from vnmacro.app.service import write_feedback

    rid = item["request_id"]
    comment = st.session_state.get(f"comment_{rid}")
    row = feedback_row(rid, rating, comment, st.session_state["session_id"])
    ok = write_feedback(os.environ["DATABASE_URL_LOGGER"], row)
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
                    details_markdown(
                        item["route"],
                        item["period"],
                        item["rag_query"],
                        item.get("standalone"),
                    )
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
    # Anonymous id of this browser session: random, nothing about the user.
    st.session_state.setdefault("session_id", str(uuid.uuid4()))
    if not login():
        return
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("feedback", {})
    st.title(config.APP_TITLE)
    st.caption(get_scope_brief() + "  \n" + config.APP_DISCLAIMER)

    job = st.session_state.get("job")
    busy = job is not None
    pending = None
    if not st.session_state["history"]:
        st.markdown("**Bạn có thể thử:**")
        for i, q in enumerate(config.APP_SUGGESTED_QUESTIONS):
            if st.button(q, key=f"suggest_{i}", disabled=busy):
                pending = q
    for item in st.session_state["history"]:
        show_answer(item)
    question = st.chat_input(
        "Nhập câu hỏi về cổ phiếu, chỉ số, kinh tế vĩ mô...", disabled=busy
    )
    if not busy and (question or pending):
        start_question(question or pending)
        job = st.session_state["job"]
    if job is not None:
        wait_for(job)
        st.rerun()


main()
