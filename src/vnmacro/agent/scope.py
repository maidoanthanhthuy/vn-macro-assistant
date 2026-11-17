"""Data scope: what the app can look up (symbols, indicators, periods), from the DB.

Built once at startup. The full text is appended to refusals and given to the answer
step (for valid suggestions); a short version is shown on the app's main screen.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from vnmacro import config


@dataclass(frozen=True)
class DataScope:
    """Symbols, indicators and date ranges available in the database."""

    stocks: tuple[tuple[str, str], ...]  # (symbol, name)
    indices: tuple[tuple[str, str], ...]
    price_first: dt.date | None
    price_last: dt.date | None
    some_listed_later: bool  # a symbol's data starts after price_first
    annual: tuple[str, ...]  # annual indicator names
    annual_first: int | None
    annual_last: int | None  # last year with actual (not forecast) values
    forecast_last: int | None
    cpi_first: dt.date | None
    cpi_last: dt.date | None
    policy_first: dt.date | None
    policy_last: dt.date | None
    documents: tuple[tuple[str, str, str, int], ...]  # (doc_type, first, last, count)


def short_name(name: str) -> str:
    """Indicator name without its trailing unit in brackets."""
    return name.split(" (")[0].strip()


def fmt_date(d: dt.date | None) -> str:
    """Date as DD/MM/YYYY ('?' when unknown)."""
    return f"{d:%d/%m/%Y}" if d else "?"


def fmt_month(d: dt.date | None) -> str:
    """Month as MM/YYYY ('?' when unknown)."""
    return f"{d:%m/%Y}" if d else "?"


def fmt_period(period: str) -> str:
    """Document reference period in Vietnamese order: 2026-10 -> 10/2026."""
    if "-" not in period:
        return period
    year, part = period.split("-", 1)
    return f"{part}/{year}"


def build_scope(
    symbols: list[tuple[str, str, str, dt.date]],
    prices: tuple[dt.date | None, dt.date | None],
    indicators: list[str],
    annual: tuple[int | None, int | None, int | None],
    cpi: tuple[dt.date | None, dt.date | None],
    policy: tuple[dt.date | None, dt.date | None],
    documents: list[tuple[str, str, str, int]],
) -> DataScope:
    """DataScope from query rows; symbols are (symbol, name, asset_type, first_date)."""
    first = prices[0]
    return DataScope(
        stocks=tuple((s, n) for s, n, t, _ in sorted(symbols) if t == "stock"),
        indices=tuple(
            (s, n) for s, n, t, _ in sorted(symbols, reverse=True) if t == "index"
        ),  # VNINDEX, VN30, HNXINDEX
        price_first=first,
        price_last=prices[1],
        some_listed_later=any(first and d > first for *_, d in symbols),
        annual=tuple(dict.fromkeys(short_name(n) for n in indicators)),
        annual_first=annual[0],
        annual_last=annual[1],
        forecast_last=annual[2],
        cpi_first=cpi[0],
        cpi_last=cpi[1],
        policy_first=policy[0],
        policy_last=policy[1],
        documents=tuple(sorted(documents)),
    )


def format_scope(
    scope: DataScope,
    title: str = config.SCOPE_TITLE,
    doc_labels: dict[str, str] = config.SCOPE_DOC_TYPE_LABELS,
) -> str:
    """Full Markdown scope (Vietnamese): symbols, indicators, documents, periods."""
    stocks = ", ".join(f"{s} ({n})" for s, n in scope.stocks)
    later = "; mã niêm yết sau thì từ ngày niêm yết" if scope.some_listed_later else ""
    lines = [
        f"**{title}**",
        f"- Giá cổ phiếu (giá đóng cửa điều chỉnh, khối lượng hằng ngày) từ "
        f"{fmt_date(scope.price_first)} đến {fmt_date(scope.price_last)}{later}: "
        f"{stocks}.",
        f"- Chỉ số: {', '.join(n for _, n in scope.indices)} (cùng khoảng thời gian).",
    ]
    if scope.annual:
        forecast = (
            f", có dự báo tăng trưởng GDP của IMF đến {scope.forecast_last}"
            if scope.forecast_last and scope.forecast_last > (scope.annual_last or 0)
            else ""
        )
        lines.append(
            f"- Chỉ tiêu vĩ mô hằng năm của Việt Nam, {scope.annual_first}–"
            f"{scope.annual_last} (tùy chỉ tiêu){forecast}: "
            f"{'; '.join(scope.annual)}."
        )
    if scope.cpi_last:
        lines.append(
            f"- CPI và lạm phát so với cùng kỳ hằng tháng: {fmt_month(scope.cpi_first)}"
            f" – {fmt_month(scope.cpi_last)}."
        )
    if scope.policy_last:
        lines.append(
            f"- Các lần Ngân hàng Nhà nước đổi lãi suất điều hành: "
            f"{fmt_date(scope.policy_first)} – {fmt_date(scope.policy_last)}."
        )
    for doc_type, first, last, n in scope.documents:
        label = doc_labels.get(doc_type, doc_type)
        span = (
            fmt_period(first)
            if first == last
            else (f"{fmt_period(first)} – {fmt_period(last)}")
        )
        lines.append(f"- Tài liệu: {label}, {span} ({n} tài liệu).")
    return "\n".join(lines)


def format_scope_brief(scope: DataScope) -> str:
    """Three short Markdown lines for the main screen: symbols, indicators, dates."""
    symbols = ", ".join(s for s, _ in scope.stocks)
    indices = ", ".join(n for _, n in scope.indices)
    data = ["giá ngày"]
    if scope.annual:
        data.append(f"vĩ mô năm ({'; '.join(scope.annual)})")
    data += ["CPI tháng", "lãi suất điều hành NHNN", "báo cáo Cục Thống kê và NHNN"]
    dates = [f"giá {fmt_date(scope.price_last)}"]
    if scope.cpi_last:
        dates.append(f"CPI {fmt_month(scope.cpi_last)}")
    if scope.annual_last:
        dates.append(f"vĩ mô năm {scope.annual_last}")
    reports = [last for t, _, last, _ in scope.documents if t == config.NSO_REPORT_TYPE]
    if reports:
        dates.append(f"báo cáo Cục Thống kê {fmt_period(max(reports))}")
    return "  \n".join([
        f"**Mã:** {symbols} · **Chỉ số:** {indices}",
        f"**Chỉ tiêu:** {' · '.join(data)}",
        f"**Dữ liệu đến:** {' · '.join(dates)}",
    ])  # fmt: skip


def answer_prompt(instructions: str, scope_text: str) -> str:
    """Fixed answer prompt: instructions, then the data scope (valid suggestions)."""
    return (
        instructions.strip() + "\n\n# Data the app can look up\n\n" + scope_text + "\n"
    )


# ---------- I/O ----------

_SCOPE_SQL: dict[str, str] = {
    "symbols": "SELECT symbol, name, asset_type, first_date FROM symbols",
    "prices": "SELECT min(date), max(date) FROM daily_prices",
    "indicators": (
        "SELECT name FROM indicators WHERE frequency = 'annual' ORDER BY name"
    ),
    "annual": (
        "SELECT min(year), max(year) FILTER (WHERE NOT is_forecast), "
        "max(year) FILTER (WHERE is_forecast) FROM macro_annual"
    ),
    "cpi": "SELECT min(month), max(month) FROM cpi_monthly",
    "policy": "SELECT min(announced_date), max(announced_date) FROM policy_events",
    "documents": (
        "SELECT doc_type, min(reference_period), max(reference_period), count(*) "
        "FROM rag.documents GROUP BY doc_type"
    ),
}


def fetch_scope(url: str) -> DataScope:
    """Read the data scope as the reader."""
    from vnmacro.db import with_connection

    def run(conn: Any) -> DataScope:
        q = {k: conn.execute(v).fetchall() for k, v in _SCOPE_SQL.items()}
        return build_scope(
            [tuple(r) for r in q["symbols"]],
            tuple(q["prices"][0]),
            [r[0] for r in q["indicators"]],
            tuple(q["annual"][0]),
            tuple(q["cpi"][0]),
            tuple(q["policy"][0]),
            [tuple(r) for r in q["documents"]],
        )

    return with_connection(url, run)
