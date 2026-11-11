"""Clean the raw snapshots and manual tables, check them, and load them into PostgreSQL.

Run from the repository root (the database must be running, see README):

    PYTHONPATH=src python -m vnmacro.ingest.load_db            # latest snapshots
    PYTHONPATH=src python -m vnmacro.ingest.load_db --dry-run  # checks + report only
    PYTHONPATH=src python -m vnmacro.ingest.load_db --kbs-snapshot 2026-11-10

All tables are emptied and reloaded in one transaction. Blocking checks run before the
transaction is committed; any failure rolls everything back, so the database keeps its
previous content. A report is printed and saved to data/reports/.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from vnmacro import config

Row = dict[str, Any]

MANUAL_DROP_COLS = ("verified", "notes")
TABLE_ORDER = (  # lookup tables first
    "symbols",
    "indicators",
    "daily_prices",
    "macro_annual",
    "cpi_monthly",
    "policy_events",
)
TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "symbols": (
        "symbol",
        "name",
        "full_name",
        "aliases",
        "asset_type",
        "sector",
        "exchange",
        "price_unit",
        "first_date",
    ),
    "indicators": (
        "indicator_code",
        "name",
        "unit",
        "source",
        "frequency",
        "table_name",
        "notes",
    ),
    "daily_prices": ("date", "symbol", "open", "high", "low", "close", "volume"),
    "macro_annual": ("indicator_code", "year", "value", "is_forecast", "vintage"),
    "cpi_monthly": ("month", "cpi_index", "inflation_yoy"),
    "policy_events": (
        "announced_date",
        "effective_date",
        "rate_type",
        "old_rate",
        "new_rate",
        "direction",
        "document_no",
        "source_url",
        "notes",
    ),
}
PERIOD_COLUMN = {
    "symbols": "first_date",
    "indicators": None,
    "daily_prices": "date",
    "macro_annual": "year",
    "cpi_monthly": "month",
    "policy_events": "announced_date",
}


# ---------- pure helpers: parsing and cleaning ----------


def to_float(value: Any) -> float:
    """Convert a JSON number or numeric string (KBS mixes both) to float."""
    return float(value)


def empty_to_none(value: Any) -> Any:
    """Return None for an empty string, else the value unchanged."""
    return None if value == "" else value


def parse_kbs_rows(symbol: str, rows: Iterable[dict[str, Any]]) -> list[Row]:
    """Turn raw KBS rows ({'t','o','h','l','c','v'}) into typed price rows."""
    out = []
    for r in rows:
        v = r.get("v")
        out.append(
            {
                "date": date.fromisoformat(str(r["t"])[:10]),
                "symbol": symbol,
                "open": to_float(r["o"]),
                "high": to_float(r["h"]),
                "low": to_float(r["l"]),
                "close": to_float(r["c"]),
                "volume": None if v in (None, "") else int(to_float(v)),
            }
        )
    return out


def clean_prices(
    rows: Iterable[Row], start: date, fixes: Iterable[Row] = ()
) -> list[Row]:
    """Keep rows on/after `start`, apply drop_row / null_volume fixes, sort by date."""
    fixes = list(fixes)
    drop = {(f["symbol"], f["date"]) for f in fixes if f["action"] == "drop_row"}
    null_vol = {(f["symbol"], f["date"]) for f in fixes if f["action"] == "null_volume"}
    out = []
    for r in rows:
        key = (r["symbol"], r["date"])
        if r["date"] < start or key in drop:
            continue
        out.append({**r, "volume": None} if key in null_vol else dict(r))
    return sorted(out, key=lambda r: (r["symbol"], r["date"]))


def parse_price_fixes(rows: Iterable[dict[str, str]]) -> list[Row]:
    """Type the rows of price_fixes.csv; reject unknown actions."""
    allowed = {"drop_row", "null_volume", "known_missing"}
    out = []
    for r in rows:
        if r["action"] not in allowed:
            raise ValueError(f"Unknown price fix action: {r['action']!r}")
        out.append({**r, "date": date.fromisoformat(r["date"])})
    return out


def parse_worldbank(payload: list[Any], start_year: int) -> list[Row]:
    """World Bank JSON ([meta, rows]) -> macro rows from `start_year`, non-empty."""
    rows = payload[1] or []
    out = [
        {
            "indicator_code": r["indicator"]["id"],
            "year": int(r["date"]),
            "value": float(r["value"]),
            "is_forecast": False,
            "vintage": None,
        }
        for r in rows
        if r["value"] is not None and int(r["date"]) >= start_year
    ]
    return sorted(out, key=lambda r: r["year"])


def weo_vintage(publication_date: str) -> str:
    """Name the WEO release from its publication date: 'WEO April/October YYYY'."""
    d = datetime.fromisoformat(publication_date.replace("Z", "+00:00"))
    if d.month in (3, 4, 5):
        return f"WEO April {d.year}"
    if d.month in (9, 10, 11):
        return f"WEO October {d.year}"
    raise ValueError(f"Unexpected WEO publication month: {publication_date}")


def single_value(rows: list[dict[str, str]], column: str) -> str:
    """Return the one non-empty value of `column`; raise if absent or ambiguous."""
    values = {r[column] for r in rows if r.get(column)}
    if len(values) != 1:
        raise ValueError(f"Expected one value for {column}, got {sorted(values)}")
    return values.pop()


def parse_weo(rows: list[dict[str, str]], start_year: int) -> list[Row]:
    """WEO SDMX-CSV rows -> macro rows; forecast if year > LATEST_ACTUAL_ANNUAL_DATA."""
    code = single_value(rows, "INDICATOR")
    latest = int(single_value(rows, "LATEST_ACTUAL_ANNUAL_DATA"))
    vintage = weo_vintage(single_value(rows, "PUBLICATION_DATE"))
    out = []
    for r in rows:
        year = int(r[config.IMF_PERIOD_COL])
        if not r[config.IMF_VALUE_COL].strip() or year < start_year:
            continue
        out.append(
            {
                "indicator_code": code,
                "year": year,
                "value": float(r[config.IMF_VALUE_COL]),
                "is_forecast": year > latest,
                "vintage": vintage,
            }
        )
    return sorted(out, key=lambda r: r["year"])


def parse_month(period: str) -> date:
    """IMF monthly period 'YYYY-MNN' -> first day of that month."""
    year, month = period.split("-M")
    return date(int(year), int(month), 1)


def parse_imf_monthly(rows: Iterable[dict[str, str]]) -> dict[date, float]:
    """IMF monthly SDMX-CSV rows -> {month: value}, skipping empty placeholder rows."""
    return {
        parse_month(r[config.IMF_PERIOD_COL]): float(r[config.IMF_VALUE_COL])
        for r in rows
        if r[config.IMF_VALUE_COL].strip()
    }


def add_inflation_yoy(cpi: dict[date, float]) -> list[Row]:
    """CPI index by month -> rows with y/y inflation (%), None without last year."""
    out = []
    for month in sorted(cpi):
        prev = cpi.get(month.replace(year=month.year - 1))
        yoy = None if prev is None else (cpi[month] / prev - 1) * 100
        out.append({"month": month, "cpi_index": cpi[month], "inflation_yoy": yoy})
    return out


def strip_manual(
    rows: Iterable[dict[str, str]], drop: Iterable[str] = MANUAL_DROP_COLS
) -> list[Row]:
    """Drop bookkeeping columns from a manual table and turn '' into None."""
    drop = set(drop)
    return [{k: empty_to_none(v) for k, v in r.items() if k not in drop} for r in rows]


def first_dates(prices: Iterable[Row]) -> dict[str, date]:
    """First price date of each symbol."""
    out: dict[str, date] = {}
    for r in prices:
        if r["symbol"] not in out or r["date"] < out[r["symbol"]]:
            out[r["symbol"]] = r["date"]
    return out


def build_symbols(rows: Iterable[Row], firsts: dict[str, date]) -> list[Row]:
    """Add first_date to symbol rows; aliases default to ''."""
    return [
        {**r, "aliases": r.get("aliases") or "", "first_date": firsts.get(r["symbol"])}
        for r in rows
    ]


def type_policy_events(rows: Iterable[Row]) -> list[Row]:
    """Convert policy_events dates and rates to date / float."""
    out = []
    for r in rows:
        out.append(
            {
                **r,
                "announced_date": date.fromisoformat(r["announced_date"]),
                "effective_date": date.fromisoformat(r["effective_date"]),
                "old_rate": float(r["old_rate"]),
                "new_rate": float(r["new_rate"]),
            }
        )
    return out


# ---------- pure helpers: checks ----------


def check_unverified(tables: dict[str, list[dict[str, str]]]) -> list[str]:
    """Blocking: every manual row must have verified = yes."""
    errors = []
    for name, rows in tables.items():
        bad = [i + 2 for i, r in enumerate(rows) if r.get("verified") != "yes"]
        if bad:
            errors.append(f"{name}: rows not verified = yes (CSV lines {bad})")
    return errors


def check_symbols(
    prices: Iterable[Row], symbols: Iterable[Row], expected: int
) -> list[str]:
    """Blocking: price symbols must number `expected` and all exist in symbols."""
    in_prices = {r["symbol"] for r in prices}
    known = {r["symbol"] for r in symbols}
    errors = []
    if len(in_prices) != expected:
        errors.append(f"daily_prices has {len(in_prices)} symbols, expected {expected}")
    if in_prices - known:
        errors.append(
            f"symbols missing from symbols table: {sorted(in_prices - known)}"
        )
    if known - in_prices:
        errors.append(f"symbols without prices: {sorted(known - in_prices)}")
    return errors


def check_duplicate_keys(prices: Iterable[Row]) -> list[str]:
    """Blocking: (symbol, date) must be unique."""
    seen, dup = set(), []
    for r in prices:
        key = (r["symbol"], r["date"])
        if key in seen:
            dup.append(f"{key[0]} {key[1]}")
        seen.add(key)
    return [f"duplicate (symbol, date): {dup[:10]}"] if dup else []


def check_duplicate_ohlcv(prices: Iterable[Row]) -> list[str]:
    """Blocking: no row may repeat the full OHLCV of another date of the same symbol."""
    first_seen: dict[tuple, date] = {}
    errors = []
    for r in prices:
        key = (r["symbol"], r["open"], r["high"], r["low"], r["close"], r["volume"])
        if key in first_seen:
            errors.append(
                f"{r['symbol']} {r['date']} repeats the OHLCV of {first_seen[key]}"
            )
        else:
            first_seen[key] = r["date"]
    return errors


def check_stock_units(
    prices: Iterable[Row], stocks: set[str], min_price: float
) -> list[str]:
    """Blocking: stock closes below `min_price` VND suggest thousand-VND units."""
    low = [
        f"{r['symbol']} {r['date']} close {r['close']}"
        for r in prices
        if r["symbol"] in stocks and r["close"] < min_price
    ]
    return [f"stock prices below {min_price:g} VND: {low[:10]}"] if low else []


def check_yoy(
    cpi_rows: Iterable[Row], imf_yoy: dict[date, float], tolerance: float
) -> list[str]:
    """Blocking: our inflation_yoy must match IMF's y/y series within `tolerance`."""
    errors = []
    ours = {r["month"]: r["inflation_yoy"] for r in cpi_rows}
    for month, ref in sorted(imf_yoy.items()):
        mine = ours.get(month)
        if mine is None:
            errors.append(f"{month}: IMF y/y {ref:.4f} but no computed inflation_yoy")
        elif abs(mine - ref) > tolerance:
            errors.append(f"{month}: inflation_yoy {mine:.4f} vs IMF {ref:.4f}")
    extra = [m for m, v in ours.items() if v is not None and m not in imf_yoy]
    if extra:
        errors.append(f"inflation_yoy months not in IMF y/y series: {sorted(extra)}")
    return errors


def warn_big_moves(
    prices: Iterable[Row],
    exchange_of: dict[str, str],
    bands: dict[str, float],
    tolerance: float,
) -> list[str]:
    """Warning: close-to-close moves beyond the exchange's price band + tolerance."""
    warnings, prev = [], {}
    for r in sorted(prices, key=lambda r: (r["symbol"], r["date"])):
        p = prev.get(r["symbol"])
        if p is not None:
            pct = (r["close"] / p["close"] - 1) * 100
            limit = bands[exchange_of[r["symbol"]]] + tolerance
            if abs(pct) > limit:
                warnings.append(
                    f"{r['symbol']} {r['date']}: close {p['close']:g} -> "
                    f"{r['close']:g} ({pct:+.2f}%)"
                )
        prev[r["symbol"]] = r
    return warnings


def warn_date_mismatch(
    prices: Iterable[Row],
    symbols: Iterable[Row],
    known_missing: set[tuple[str, date]],
) -> list[str]:
    """Warning: dates in an index but not in a same-exchange stock, or the reverse.

    Each stock is compared only within its own first..last date range.
    """
    dates: dict[str, set[date]] = defaultdict(set)
    for r in prices:
        dates[r["symbol"]].add(r["date"])
    by_exchange: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"index": [], "stock": []}
    )
    for s in symbols:
        by_exchange[s["exchange"]][s["asset_type"]].append(s["symbol"])
    warnings = []
    for groups in by_exchange.values():
        for idx in sorted(groups["index"]):
            for stock in sorted(groups["stock"]):
                if not dates[idx] or not dates[stock]:
                    continue
                lo = max(min(dates[idx]), min(dates[stock]))
                hi = min(max(dates[idx]), max(dates[stock]))
                for missing, present in ((stock, idx), (idx, stock)):
                    gap = sorted(
                        d
                        for d in dates[present] - dates[missing]
                        if lo <= d <= hi and (missing, d) not in known_missing
                    )
                    if gap:
                        shown = ", ".join(str(d) for d in gap[:5])
                        more = f" (+{len(gap) - 5} more)" if len(gap) > 5 else ""
                        warnings.append(
                            f"{missing} missing {len(gap)} date(s) present in "
                            f"{present}: {shown}{more}"
                        )
    return warnings


def noted_latest_year(notes: str | None) -> int | None:
    """Read 'latest year YYYY' from an indicators note, if present."""
    m = re.search(r"latest year (\d{4})", notes or "", flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


def warn_wb_latest(macro: Iterable[Row], indicators: Iterable[Row]) -> list[str]:
    """Warning: a World Bank indicator's latest year is older than its note says."""
    latest: dict[str, int] = {}
    for r in macro:
        latest[r["indicator_code"]] = max(latest.get(r["indicator_code"], 0), r["year"])
    warnings = []
    for ind in indicators:
        if ind["source"] != "World Bank":
            continue
        noted = noted_latest_year(ind.get("notes"))
        got = latest.get(ind["indicator_code"])
        if noted and (got is None or got < noted):
            warnings.append(
                f"{ind['indicator_code']}: latest year {got} is older than the noted "
                f"{noted}"
            )
    return warnings


def table_stats(tables: dict[str, list[Row]]) -> list[tuple[str, int, Any, Any]]:
    """(table, rows, first period, last period) for each table in load order."""
    out = []
    for name in TABLE_ORDER:
        rows, col = tables[name], PERIOD_COLUMN[name]
        values = [r[col] for r in rows if col and r[col] is not None]
        out.append(
            (
                name,
                len(rows),
                min(values) if values else "-",
                max(values) if values else "-",
            )
        )
    return out


def build_report(
    snapshots: dict[str, str],
    stats: list[tuple[str, int, Any, Any]],
    errors: list[str],
    warnings: list[str],
    outcome: str,
) -> str:
    """Plain-text load report."""
    lines = [f"Load report ({outcome})", "", "Snapshots:"]
    lines += [f"  {k}: {v}" for k, v in snapshots.items()]
    lines += ["", f"{'table':15} {'rows':>7}  {'first':12} {'last':12}"]
    lines += [f"{t:15} {n:>7}  {str(a):12} {str(b):12}" for t, n, a, b in stats]
    lines += ["", f"Blocking checks failed: {len(errors)}"]
    lines += [f"  - {e}" for e in errors]
    lines += ["", f"Warnings: {len(warnings)}"]
    lines += [f"  - {w}" for w in warnings]
    return "\n".join(lines) + "\n"


# ---------- I/O ----------


def latest_snapshot(root: Path, wanted: str | None = None) -> Path:
    """Return root/<wanted>, or the newest dated snapshot folder with a manifest."""
    if wanted:
        path = root / wanted
        if not (path / "manifest.json").exists():
            raise FileNotFoundError(f"No snapshot at {path}")
        return path
    folders = sorted(
        p
        for p in root.iterdir()
        if p.is_dir()
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)
        and (p / "manifest.json").exists()
    )
    if not folders:
        raise FileNotFoundError(f"No snapshot under {root}")
    return folders[-1]


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV file into dicts."""
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_kbs(snapshot: Path, fixes: list[Row]) -> list[Row]:
    """Read only the files listed in the KBS manifest and clean them."""
    manifest = json.loads((snapshot / "manifest.json").read_text())
    out = []
    for symbol, entry in manifest["symbols"].items():
        start = config.STOCK_START if entry["kind"] == "stocks" else config.INDEX_START
        raw = []
        for name in entry["files"]:
            payload = json.loads((snapshot / name).read_text())
            raw += parse_kbs_rows(symbol, payload[config.KBS_ROWS_KEY])
        out += clean_prices(raw, start, fixes)
    return out


def read_worldbank(snapshot: Path) -> list[Row]:
    """Read every World Bank file listed in the manifest."""
    manifest = json.loads((snapshot / "manifest.json").read_text())
    out = []
    for code, entry in manifest["indicators"].items():
        if code not in config.WB_INDICATORS:
            continue
        for name in entry["files"]:
            payload = json.loads((snapshot / name).read_text())
            out += parse_worldbank(payload, config.MACRO_START_YEAR)
    return out


def db_connect() -> Any:
    """Open a psycopg connection with the settings in .env."""
    import psycopg
    from dotenv import load_dotenv

    load_dotenv()
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def load_tables(conn: Any, tables: dict[str, list[Row]], expected_symbols: int) -> None:
    """Empty and reload all tables in one transaction; roll back on any error."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"TRUNCATE {', '.join(TABLE_ORDER)}")
        for name in TABLE_ORDER:
            cols = TABLE_COLUMNS[name]
            with cur.copy(f"COPY {name} ({', '.join(cols)}) FROM STDIN") as copy:
                for r in tables[name]:
                    copy.write_row([r[c] for c in cols])
        for name in TABLE_ORDER:
            cur.execute(f"SELECT count(*) FROM {name}")
            n = cur.fetchone()[0]
            if n != len(tables[name]):
                raise RuntimeError(
                    f"{name}: {n} rows in database, {len(tables[name])} expected"
                )
        cur.execute("SELECT count(DISTINCT symbol) FROM daily_prices")
        n = cur.fetchone()[0]
        if n != expected_symbols:
            raise RuntimeError(f"daily_prices has {n} symbols in database")


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; returns the exit code."""
    parser = argparse.ArgumentParser(description="Clean, check and load all data.")
    parser.add_argument("--kbs-snapshot", help="KBS snapshot date (default: latest)")
    parser.add_argument("--wb-snapshot", help="World Bank snapshot date")
    parser.add_argument("--imf-snapshot", help="IMF snapshot date")
    parser.add_argument("--dry-run", action="store_true", help="do not write the DB")
    args = parser.parse_args(argv)

    kbs_dir = latest_snapshot(config.RAW_KBS_DIR, args.kbs_snapshot)
    wb_dir = latest_snapshot(config.RAW_WB_DIR, args.wb_snapshot)
    imf_dir = latest_snapshot(config.RAW_IMF_DIR, args.imf_snapshot)
    snapshots = {"KBS": str(kbs_dir), "World Bank": str(wb_dir), "IMF": str(imf_dir)}

    fixes = parse_price_fixes(read_csv(config.PRICE_FIXES_FILE))
    raw_manual = {
        n: read_csv(config.MANUAL_DIR / f"{n}.csv")
        for n in ("symbols", "indicators", "policy_events")
    }
    prices = read_kbs(kbs_dir, fixes)
    macro = read_worldbank(wb_dir) + parse_weo(
        read_csv(imf_dir / "WEO_NGDP_RPCH.csv"), config.MACRO_START_YEAR
    )
    cpi = add_inflation_yoy(parse_imf_monthly(read_csv(imf_dir / "CPI.csv")))
    imf_yoy = parse_imf_monthly(read_csv(imf_dir / "CPI_YOY.csv"))
    symbols = build_symbols(strip_manual(raw_manual["symbols"]), first_dates(prices))
    indicators = strip_manual(raw_manual["indicators"], drop=("verified",))
    policy = type_policy_events(
        strip_manual(raw_manual["policy_events"], drop=("verified",))
    )
    tables = {
        "symbols": symbols,
        "indicators": indicators,
        "daily_prices": prices,
        "macro_annual": macro,
        "cpi_monthly": cpi,
        "policy_events": policy,
    }

    stocks = {s["symbol"] for s in symbols if s["asset_type"] == "stock"}
    known_missing = {
        (f["symbol"], f["date"]) for f in fixes if f["action"] == "known_missing"
    }
    errors = (
        check_unverified(raw_manual)
        + check_symbols(prices, symbols, config.EXPECTED_SYMBOLS)
        + check_duplicate_keys(prices)
        + check_duplicate_ohlcv(prices)
        + check_stock_units(prices, stocks, config.MIN_STOCK_PRICE_VND)
        + check_yoy(cpi, imf_yoy, config.YOY_TOLERANCE_PP)
    )
    warnings = (
        warn_big_moves(
            prices,
            {s["symbol"]: s["exchange"] for s in symbols},
            config.PRICE_BAND_PCT,
            config.BAND_TOLERANCE_PP,
        )
        + warn_date_mismatch(prices, symbols, known_missing)
        + warn_wb_latest(macro, indicators)
    )

    if errors:
        outcome = "ABORTED: blocking checks failed, database unchanged"
    elif args.dry_run:
        outcome = "DRY RUN: database unchanged"
    else:
        try:
            with db_connect() as conn:
                load_tables(conn, tables, config.EXPECTED_SYMBOLS)
            outcome = "LOADED"
        except Exception as exc:  # report any DB failure; the transaction rolled back
            errors.append(
                f"database load failed, rolled back: {type(exc).__name__}: {exc}"
            )
            outcome = "ABORTED: database error, database unchanged"

    report = build_report(snapshots, table_stats(tables), errors, warnings, outcome)
    print(report)
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORTS_DIR / f"load_{datetime.now():%Y%m%d_%H%M%S}.txt"
    path.write_text(report, encoding="utf-8")
    print(f"Report saved to {path}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
