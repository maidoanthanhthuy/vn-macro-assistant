"""Answer step: one LLM call writes the Vietnamese answer from the gathered data.

The LLM writes the short answer and term explanations (prompts/answer.md) and says which
document excerpts it used. The source list is built by code: tables read by the final
SQL (config.SOURCE_TABLE_LABELS) and the used documents (title, period, URL).
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vnmacro import config
from vnmacro.agent.retrieve import RetrievedChunk
from vnmacro.llm import LLMResponse, cost_usd
from vnmacro.sql_agent.context import format_rows
from vnmacro.sql_agent.prompt import build_messages

LLMCall = Callable[[list[dict[str, str]]], LLMResponse]
WriteLog = Callable[[dict[str, Any]], None]

SCHEMA_NAME = "final_answer"
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "short_answer": {"type": "string"},
        "explanations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["term", "explanation"],
                "additionalProperties": False,
            },
        },
        "used_documents": {"type": "array", "items": {"type": "integer"}},
        "declined": {"type": "boolean"},
    },
    "required": [
        "short_answer",
        "explanations",
        "used_documents",
        "declined",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class SQLData:
    """What the answer step needs from a Text-to-SQL result."""

    status: str
    sql: str | None
    columns: list[str]
    rows: list[tuple[Any, ...]]
    notes: str = ""
    reason: str | None = None


@dataclass(frozen=True)
class DraftAnswer:
    """Parsed LLM output."""

    short_answer: str
    explanations: list[tuple[str, str]]
    used_documents: list[int]
    declined: bool = False  # out of scope or data missing: the data scope is appended


# ---------- pure helpers ----------


def format_input(
    question: str,
    route: str,
    notes: list[str],
    sql: SQLData | None,
    chunks: list[RetrievedChunk],
    max_chars: int | None = config.ANSWER_MAX_CELL_CHARS,
) -> str:
    """User message for the answer LLM: question, route, notes, SQL result, excerpts."""
    parts = [f"Question: {question}", f"Route: {route}"]
    if notes:
        parts.append("System notes:\n" + "\n".join(f"- {n}" for n in notes))
    if sql is not None:
        lines = [f"## SQL result (status: {sql.status})"]
        if sql.status == "ok":
            lines.append(f"Query:\n{sql.sql}")
            if sql.rows:
                lines.append("Rows:\n" + format_rows(sql.columns, sql.rows, max_chars))
            else:
                lines.append("Rows: none (empty result)")
        if sql.reason:
            lines.append(f"Reason it cannot answer: {sql.reason}")
        if sql.notes:
            lines.append(f"Notes: {sql.notes}")
        parts.append("\n".join(lines))
    if chunks:
        lines = ["## Document excerpts"]
        for i, c in enumerate(chunks, start=1):
            lines.append(
                f"[{i}] {c.context_label} (period {c.reference_period})\n{c.text}"
            )
        parts.append("\n\n".join(lines))
    return "\n\n".join(parts)


def parse_draft(
    content: str, n_chunks: int, max_terms: int = config.EXPLANATION_MAX_TERMS
) -> DraftAnswer:
    """Parse the JSON output; drop missing document numbers and extra terms."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Output is not valid JSON: {e}") from e
    if not isinstance(data, dict) or set(data) != set(RESPONSE_SCHEMA["required"]):
        raise ValueError("Output does not have exactly the fields of the schema.")
    short = data["short_answer"]
    if not isinstance(short, str) or not short.strip():
        raise ValueError("Output field short_answer must be a non-empty string.")
    try:
        explanations = [
            (str(e["term"]).strip(), str(e["explanation"]).strip())
            for e in data["explanations"]
        ]
        used = [int(i) for i in data["used_documents"]]
    except (TypeError, KeyError, ValueError) as e:
        raise ValueError(f"Output lists have the wrong shape: {e}") from e
    used = sorted({i for i in used if 1 <= i <= n_chunks})
    declined = data["declined"]
    if not isinstance(declined, bool):
        raise ValueError("Output field declined must be a boolean.")
    return DraftAnswer(
        short.strip(),
        [e for e in explanations if all(e)][:max_terms],
        used,
        declined,
    )


def sql_tables(sql: str | None) -> list[str]:
    """Sorted table names read by a query (CTE names excluded)."""
    if not sql:
        return []
    import sqlglot
    from sqlglot import exp

    tree = sqlglot.parse_one(sql, read="postgres")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    return sorted({t.name for t in tree.find_all(exp.Table) if t.name} - ctes)


def build_sources(
    sql: SQLData | None,
    chunks: list[RetrievedChunk],
    used_documents: list[int],
    table_labels: dict[str, str] = config.SOURCE_TABLE_LABELS,
) -> list[str]:
    """Source lines: tables of the final SQL (if it ran), then the used documents."""
    lines: list[str] = []
    if sql is not None and sql.status == "ok" and sql.rows:
        for name in sql_tables(sql.sql):
            if name in table_labels:
                lines.append(f"Bảng `{name}`: {table_labels[name]}")
    seen: set[str] = set()
    for i in used_documents:
        c = chunks[i - 1]
        if c.doc_id in seen:
            continue
        seen.add(c.doc_id)
        lines.append(f"{c.title} (kỳ {c.reference_period}): {c.url}")
    return lines


def fold_text(text: str) -> str:
    """Lower case without Vietnamese diacritics ("Lãi suất" -> "lai suat")."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def pick_suggestion(
    question: str,
    topics: tuple[tuple[str, tuple[str, ...]], ...] = config.EXPLAIN_SUGGESTION_TOPICS,
    default: str = config.APP_SUGGESTED_QUESTIONS[0],
) -> str:
    """App question of the first topic with a keyword in the question, else default."""
    folded = fold_text(question)
    for suggestion, keywords in topics:
        if any(re.search(rf"\b{re.escape(k)}\b", folded) for k in keywords):
            return suggestion
    return default


def answer_footer(
    route: str,
    draft: DraftAnswer,
    scope_text: str,
    suggestion: str = config.APP_SUGGESTED_QUESTIONS[0],
    explain_note: str = config.EXPLAIN_NOTE,
    suggestion_lead: str = config.EXPLAIN_SUGGESTION_LEAD,
) -> list[str]:
    """Lines after the answer: explain note + suggestion, or the scope on a refusal."""
    if route == "explain":
        return [explain_note, f"{suggestion_lead}: “{suggestion}”"]
    if (route == "out_of_scope" or draft.declined) and scope_text:
        return [scope_text]
    return []


def render(
    draft: DraftAnswer,
    sources: list[str],
    footer: list[str] | None = None,
    title: str = config.ANSWER_TITLES["default"],
) -> str:
    """Final Markdown answer: answer, explanations, sources, then the footer."""
    parts = [f"**{title}**", draft.short_answer]
    if draft.explanations:
        parts += ["", "**Giải thích thêm**"]
        parts += [f"- **{term}**: {text}" for term, text in draft.explanations]
    if sources:
        parts += ["", "**Nguồn**"]
        parts += [f"- {s}" for s in sources]
    for block in footer or []:
        parts += ["", block]
    return "\n".join(parts)


@dataclass
class AnswerResult:
    """Outcome of the answer step (also the content of its app.query_log row)."""

    run_id: str
    status: str  # 'ok' or 'error'
    text: str = ""
    draft: DraftAnswer | None = None
    suggestion: str | None = None  # route explain: app question picked by code
    sources: list[str] = field(default_factory=list)
    error: str | None = None
    latency_ms: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None


def answer_log_row(
    res: AnswerResult,
    question: str,
    model: str,
    prompt_version: str,
    component: str = config.LOG_COMPONENT_ANSWER,
) -> dict[str, Any]:
    """Map an answer result to the columns of app.query_log."""
    step: dict[str, Any] = {"attempt": 1, "stage": res.status, "error": res.error}
    if res.draft:
        step.update(
            used_documents=res.draft.used_documents,
            sources=res.sources,
            declined=res.draft.declined,
            suggestion=res.suggestion,
        )
    return {
        "run_id": res.run_id, "component": component, "question": question,
        "model": model, "prompt_version": prompt_version, "status": res.status,
        "final_sql": None, "attempts": 1, "sql_attempts": [step], "error": res.error,
        "row_count": None, "latency_ms": res.latency_ms,
        "input_tokens": res.input_tokens,
        "cached_input_tokens": res.cached_input_tokens,
        "output_tokens": res.output_tokens, "cost_usd": res.cost_usd,
        "answer_text": res.text,
    }  # fmt: skip


@dataclass
class Answerer:
    """Write the final answer with one LLM call and log it."""

    fixed_prompt: str
    prompt_version: str
    model: str
    llm: LLMCall
    write_log: WriteLog
    prices: dict[str, dict[str, float]] = field(
        default_factory=lambda: config.LLM_PRICES_USD_PER_MTOK
    )
    scope_text: str = ""  # data scope appended to refusals (scope.format_scope)

    def answer(
        self,
        question: str,
        route: str,
        notes: list[str],
        sql: SQLData | None,
        chunks: list[RetrievedChunk],
    ) -> AnswerResult:
        """Write the answer for the gathered data."""
        start = time.perf_counter()
        res = AnswerResult(run_id=str(uuid.uuid4()), status="error")
        message = format_input(question, route, notes, sql, chunks)
        try:
            reply = self.llm(build_messages(self.fixed_prompt, message))
            res.input_tokens = reply.input_tokens
            res.cached_input_tokens = reply.cached_input_tokens
            res.output_tokens = reply.output_tokens
            if reply.refusal:
                raise ValueError(f"Model refused: {reply.refusal}")
            res.draft = parse_draft(reply.content, len(chunks))
            res.sources = build_sources(sql, chunks, res.draft.used_documents)
            if route == "explain":
                res.suggestion = pick_suggestion(question)
            footer = answer_footer(
                route, res.draft, self.scope_text, res.suggestion or ""
            )
            title = config.ANSWER_TITLES.get(route, config.ANSWER_TITLES["default"])
            res.text = render(res.draft, res.sources, footer, title)
            res.status = "ok"
        except Exception as e:  # LLM/network error or invalid output
            res.error = f"{type(e).__name__}: {e}"
            res.text = config.ANSWER_ERROR_TEXT
        res.latency_ms = round((time.perf_counter() - start) * 1000)
        res.cost_usd = cost_usd(
            self.model,
            res.input_tokens,
            res.cached_input_tokens,
            res.output_tokens,
            self.prices,
        )
        self.write_log(answer_log_row(res, question, self.model, self.prompt_version))
        return res
