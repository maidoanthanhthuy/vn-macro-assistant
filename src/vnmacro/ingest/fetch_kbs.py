"""Fetch raw daily OHLCV snapshots from the KBS API (see docs/data_sources.md).

Run from the repository root, after the market close:

    PYTHONPATH=src python -m vnmacro.ingest.fetch_kbs
    PYTHONPATH=src python -m vnmacro.ingest.fetch_kbs --symbols FPT VN30

Each response is saved byte for byte to <out-root>/<snapshot date>/<SYMBOL>.json.
Existing files are never overwritten, so a re-run only fetches what is missing
(for example a symbol that failed). manifest.json in the same folder logs every call.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from vnmacro import config
from vnmacro.ingest.common import (
    OK_STATUSES,
    HttpSettings,
    fetch_with_retry,
    save_new_file,
    utc_now,
    write_manifest,
)


@dataclass(frozen=True)
class Job:
    """One symbol to fetch; kind is the KBS URL segment ('stocks' or 'index')."""

    symbol: str
    kind: str
    start: date
    end: date


@dataclass(frozen=True)
class FetchSettings(HttpSettings):
    """HTTP and validation settings for KBS calls."""

    base_url: str = config.KBS_BASE_URL
    headers: dict[str, str] = field(default_factory=lambda: dict(config.KBS_HEADERS))
    rows_key: str = config.KBS_ROWS_KEY
    min_ratio: float = config.KBS_MIN_ROW_RATIO


# ---------- pure helpers ----------


def build_jobs(
    tickers: Iterable[str],
    indices: Iterable[str],
    stock_start: date,
    index_start: date,
    end: date,
) -> list[Job]:
    """Return one job per stock ticker and per index, all ending on `end`."""
    stocks = [Job(s, "stocks", stock_start, end) for s in tickers]
    return stocks + [Job(s, "index", index_start, end) for s in indices]


def select_jobs(jobs: list[Job], symbols: Iterable[str] | None) -> list[Job]:
    """Keep only the jobs for `symbols` (all if None); raise on unknown symbols."""
    if symbols is None:
        return list(jobs)
    wanted = {s.upper() for s in symbols}
    unknown = wanted - {j.symbol for j in jobs}
    if unknown:
        raise ValueError(f"Unknown symbols: {sorted(unknown)}")
    return [j for j in jobs if j.symbol in wanted]


def kbs_url(base_url: str, kind: str, symbol: str, interval: str = "day") -> str:
    """Build the KBS history URL for a stock or an index."""
    return f"{base_url}/{kind}/{symbol}/data_{interval}"


def kbs_params(start: date, end: date) -> dict[str, str]:
    """Build the KBS query parameters (dates as DD-MM-YYYY)."""
    return {"sdate": start.strftime("%d-%m-%Y"), "edate": end.strftime("%d-%m-%Y")}


def summarize_payload(
    payload: Any, rows_key: str = config.KBS_ROWS_KEY
) -> dict[str, Any]:
    """Return the row count and first/last date ('t' is 'YYYY-MM-DD 07:00')."""
    rows = payload.get(rows_key) if isinstance(payload, dict) else None
    rows = rows if isinstance(rows, list) else []
    dates = sorted(str(r["t"])[:10] for r in rows if isinstance(r, dict) and r.get("t"))
    return {
        "n_rows": len(rows),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
    }


def combine_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Add up row counts and take the overall first and last date."""
    firsts = [s["first_date"] for s in summaries if s["first_date"]]
    lasts = [s["last_date"] for s in summaries if s["last_date"]]
    return {
        "n_rows": sum(s["n_rows"] for s in summaries),
        "first_date": min(firsts, default=None),
        "last_date": max(lasts, default=None),
    }


def weekdays_between(start: date, end: date) -> int:
    """Count Monday-Friday days from `start` to `end`, both included."""
    if end < start:
        return 0
    full_weeks, rest = divmod((end - start).days + 1, 7)
    tail = (start + timedelta(days=full_weeks * 7 + i) for i in range(rest))
    return full_weeks * 5 + sum(d.weekday() < 5 for d in tail)


def looks_truncated(
    n_rows: int, start: date, end: date, min_ratio: float = config.KBS_MIN_ROW_RATIO
) -> bool:
    """True if there are fewer rows than `min_ratio` x weekdays in the range."""
    return n_rows < min_ratio * weekdays_between(start, end)


def year_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into calendar-year pieces."""
    return [
        (max(start, date(y, 1, 1)), min(end, date(y, 12, 31)))
        for y in range(start.year, end.year + 1)
    ]


def new_manifest(snapshot_date: date, base_url: str) -> dict[str, Any]:
    """Return an empty manifest for one snapshot folder."""
    return {
        "source": "KBS",
        "snapshot_date": snapshot_date.isoformat(),
        "endpoint": f"{base_url}/{{kind}}/{{symbol}}/data_day",
        "price_adjustment": "probably adjusted, not yet confirmed "
        "(see docs/data_sources.md)",
        "units": {"stocks": "VND", "index": "index points"},
        "symbols": {},
        "calls": [],
    }


# ---------- I/O ----------


def get_or_fetch(
    session: requests.Session,
    url: str,
    start: date,
    end: date,
    path: Path,
    settings: FetchSettings,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """Reuse the file at `path` if present, else fetch and save it.

    Returns (status, summary, call record); the record is None if no call was made.
    """
    if path.exists():
        payload = json.loads(path.read_bytes())
        return "existing", summarize_payload(payload, settings.rows_key), None
    params = kbs_params(start, end)
    res = fetch_with_retry(session, url, params, settings, sleep)
    summary = summarize_payload(res["payload"], settings.rows_key)
    if res["error"]:
        status = "error"
    elif summary["n_rows"] == 0:
        status = "empty"
    else:
        status = "ok"
        save_new_file(path, res["content"])
    record = {
        "file": path.name if status == "ok" else None,
        "url": url,
        "params": params,
        "status": status,
        "http_status": res["http_status"],
        "attempts": res["attempts"],
        "error": res["error"],
        **summary,
        "fetched_at": utc_now(),
    }
    return status, summary, record


def fetch_job(
    job: Job,
    out_dir: Path,
    session: requests.Session,
    settings: FetchSettings,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch one symbol; refetch year by year if the full call looks capped."""
    url = kbs_url(settings.base_url, job.kind, job.symbol)
    full_name = f"{job.symbol}.json"
    status, full, rec = get_or_fetch(
        session, url, job.start, job.end, out_dir / full_name, settings, sleep
    )
    calls = [rec] if rec else []
    ok = status in OK_STATUSES
    entry = {
        "kind": job.kind,
        "start": job.start.isoformat(),
        "end": job.end.isoformat(),
        "status": "ok" if ok else status,
        "chunked": False,
        "files": [full_name] if ok else [],
        **full,
    }
    if not ok or not looks_truncated(
        full["n_rows"], job.start, job.end, settings.min_ratio
    ):
        return entry, calls

    pieces, files, failed = [], [], False
    for start, end in year_ranges(job.start, job.end):
        name = f"{job.symbol}_{start.year}.json"
        st, summary, rec = get_or_fetch(
            session, url, start, end, out_dir / name, settings, sleep
        )
        calls += [rec] if rec else []
        pieces.append(summary)
        if st in OK_STATUSES:
            files.append(name)
        failed = failed or st == "error"
    entry.update(
        status="error" if failed else "ok",
        chunked=True,
        full_call_rows=full["n_rows"],
        files=files,
        **combine_summaries(pieces),
    )
    return entry, calls


def run(
    jobs: list[Job],
    snapshot_dir: Path,
    snapshot_date: date,
    settings: FetchSettings,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch all jobs into `snapshot_dir`, updating manifest.json after each one."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = new_manifest(snapshot_date, settings.base_url)
    session = session or requests.Session()
    for job in jobs:
        entry, calls = fetch_job(job, snapshot_dir, session, settings)
        manifest["calls"].extend(calls)
        manifest["symbols"][job.symbol] = entry
        write_manifest(manifest_path, manifest)
        chunk = " (year by year)" if entry["chunked"] else ""
        print(
            f"{job.symbol:9} {entry['status']:6} {entry['n_rows']:5} rows "
            f"{entry['first_date']} -> {entry['last_date']}{chunk}"
        )
    return manifest


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Fetch raw KBS price snapshots.")
    parser.add_argument("--symbols", nargs="+", help="only these symbols")
    parser.add_argument(
        "--snapshot-date",
        type=date.fromisoformat,
        default=date.today(),
        help="snapshot folder and end date (default: today)",
    )
    parser.add_argument("--out-root", type=Path, default=config.RAW_KBS_DIR)
    args = parser.parse_args(argv)
    if args.snapshot_date > date.today():
        parser.error("--snapshot-date cannot be in the future")

    all_jobs = build_jobs(
        config.STOCK_TICKERS,
        config.INDEX_SYMBOLS,
        config.STOCK_START,
        config.INDEX_START,
        args.snapshot_date,
    )
    try:
        jobs = select_jobs(all_jobs, args.symbols)
    except ValueError as exc:
        parser.error(str(exc))

    snapshot_dir = args.out_root / args.snapshot_date.isoformat()
    manifest = run(jobs, snapshot_dir, args.snapshot_date, FetchSettings())
    bad = [s for s, e in manifest["symbols"].items() if e["status"] != "ok"]
    print(f"\nSnapshot: {snapshot_dir}")
    if bad:
        print(f"Not OK: {' '.join(bad)} -> re-run with --symbols {' '.join(bad)}")


if __name__ == "__main__":
    main()
