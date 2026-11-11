"""Fetch raw daily data from Vietcap, as a validation source only.

Vietcap numbers are used to check KBS data; they are never merged into the main
data. Run from the repository root:

    PYTHONPATH=src python -m vnmacro.ingest.fetch_vietcap
    # one stock over a short window, e.g. to check missing KBS dates:
    PYTHONPATH=src python -m vnmacro.ingest.fetch_vietcap --symbols VHM \
        --start 2018-05-14 --end 2018-05-25

Responses are saved byte for byte to <out-root>/<snapshot date>/<SYMBOL>.json
(SYMBOL = our name, e.g. HNXINDEX). Existing files are never overwritten.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from vnmacro import config
from vnmacro.ingest.common import (
    HttpSettings,
    fetch_with_retry,
    save_new_file,
    utc_now,
    write_manifest,
)
from vnmacro.ingest.fetch_kbs import weekdays_between

# ---------- pure helpers ----------


def vietcap_body(
    vietcap_symbol: str, start: date, end: date, tz: str = config.MARKET_TZ
) -> dict[str, Any]:
    """Build the gap-chart request body for daily bars from `start` to `end`."""
    to = datetime.combine(end + timedelta(days=1), time(), tzinfo=ZoneInfo(tz))
    return {
        "timeFrame": "ONE_DAY",
        "symbols": [vietcap_symbol],
        "to": int(to.timestamp()),
        "countBack": weekdays_between(start, end) + 1,
    }


def vietcap_closes(payload: Any, tz: str = config.MARKET_TZ) -> dict[str, float]:
    """Map local date (YYYY-MM-DD) -> close from a gap-chart response."""
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return {}
    bars = payload[0]
    zone = ZoneInfo(tz)
    return {
        datetime.fromtimestamp(int(float(t)), tz=zone).date().isoformat(): float(c)
        for t, c in zip(bars.get("t") or [], bars.get("c") or [], strict=False)
    }


def summarize_closes(closes: dict[str, float]) -> dict[str, Any]:
    """Return the row count and first/last date of a date -> close mapping."""
    dates = sorted(closes)
    return {
        "n_rows": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
    }


# ---------- I/O ----------


def fetch_index(
    symbol: str,
    vietcap_symbol: str,
    start: date,
    end: date,
    out_dir: Path,
    session: requests.Session,
    settings: HttpSettings,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Fetch one index unless its file exists; return its manifest entry."""
    path = out_dir / f"{symbol}.json"
    if path.exists():
        summary = summarize_closes(vietcap_closes(json.loads(path.read_bytes())))
        return {"vietcap_symbol": vietcap_symbol, "status": "existing", **summary}
    body = vietcap_body(vietcap_symbol, start, end)
    kwargs = {"sleep": sleep} if sleep else {}
    res = fetch_with_retry(
        session, settings.base_url, {}, settings, json_body=body, **kwargs
    )
    summary = summarize_closes(vietcap_closes(res["payload"]))
    if res["error"]:
        status = "error"
    elif summary["n_rows"] == 0:
        status = "empty"
    else:
        status = "ok"
        save_new_file(path, res["content"])
    return {
        "vietcap_symbol": vietcap_symbol,
        "file": path.name if status == "ok" else None,
        "body": body,
        "status": status,
        "http_status": res["http_status"],
        "attempts": res["attempts"],
        "error": res["error"],
        **summary,
        "fetched_at": utc_now(),
    }


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Fetch Vietcap data (check only).")
    parser.add_argument(
        "--snapshot-date", type=date.fromisoformat, default=date.today()
    )
    parser.add_argument(
        "--symbols", nargs="+", help="our symbols (default: the three indices)"
    )
    parser.add_argument("--start", type=date.fromisoformat, default=config.INDEX_START)
    parser.add_argument("--end", type=date.fromisoformat, help="default: snapshot date")
    parser.add_argument("--out-root", type=Path, default=config.EXTERNAL_VIETCAP_DIR)
    args = parser.parse_args(argv)

    snapshot_dir = args.out_root / args.snapshot_date.isoformat()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {
            "source": "Vietcap",
            "purpose": "validation of KBS data only; never merged into main data",
            "snapshot_date": args.snapshot_date.isoformat(),
            "endpoint": f"POST {config.VIETCAP_URL}",
            "symbols": {},
        }
    settings = HttpSettings(base_url=config.VIETCAP_URL, headers=config.VIETCAP_HEADERS)
    session = requests.Session()
    symbols = args.symbols or list(config.VIETCAP_INDEX_SYMBOLS)
    for symbol in symbols:
        vc_symbol = config.VIETCAP_INDEX_SYMBOLS.get(symbol, symbol)
        entry = fetch_index(
            symbol,
            vc_symbol,
            args.start,
            args.end or args.snapshot_date,
            snapshot_dir,
            session,
            settings,
        )
        if entry["status"] != "existing":
            manifest["symbols"][symbol] = entry
            write_manifest(manifest_path, manifest)
        print(
            f"{symbol:9} {entry['status']:8} {entry['n_rows']:5} rows "
            f"{entry['first_date']} -> {entry['last_date']}"
        )
    print(f"\nSnapshot: {snapshot_dir}")


if __name__ == "__main__":
    main()
