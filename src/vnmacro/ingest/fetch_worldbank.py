"""Fetch raw World Bank indicator data for Vietnam (see docs/SCOPE.md, section 2.1).

Run from the repository root:

    PYTHONPATH=src python -m vnmacro.ingest.fetch_worldbank
    PYTHONPATH=src python -m vnmacro.ingest.fetch_worldbank --only FR.INR.LEND

Every page of every indicator is saved byte for byte to
<out-root>/<snapshot date>/<CODE>_p<N>.json. Existing files are never overwritten;
a re-run only fetches the missing pages. manifest.json logs every call.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from typing import Any

import requests

from vnmacro import config
from vnmacro.ingest.common import (
    OK_STATUSES,
    HttpSettings,
    fetch_or_load,
    load_manifest,
    write_manifest,
)

# ---------- pure helpers ----------


def wb_url(api: str, country: str, code: str) -> str:
    """Build the World Bank URL for one indicator and country."""
    return f"{api}/country/{country}/indicator/{code}"


def wb_params(
    start_year: int, end_year: int, per_page: int, page: int
) -> dict[str, str]:
    """Build the query parameters for one page of a year range."""
    return {
        "format": "json",
        "date": f"{start_year}:{end_year}",
        "per_page": str(per_page),
        "page": str(page),
    }


def parse_wb_page(payload: Any) -> dict[str, Any] | None:
    """Return {'pages', 'rows'} for a valid page, or None for an API error message.

    A valid page is [metadata, rows]; rows is null when there is no data.
    An error (e.g. unknown code) is a one-element list with a 'message' key.
    """
    if not isinstance(payload, list) or len(payload) < 2:
        return None
    meta, rows = payload[0], payload[1]
    if not isinstance(meta, dict) or "pages" not in meta:
        return None
    return {"pages": max(int(meta["pages"] or 0), 1), "rows": rows or []}


def summarize_wb_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count rows and non-null values; give the first/last year with a value."""
    years = sorted(str(r["date"]) for r in rows if r.get("value") is not None)
    return {
        "n_rows": len(rows),
        "n_values": len(years),
        "first_period": years[0] if years else None,
        "last_period": years[-1] if years else None,
    }


def select_codes(codes: Iterable[str], only: Iterable[str] | None) -> list[str]:
    """Keep only `only` (all if None); raise on unknown codes."""
    codes = list(codes)
    if only is None:
        return codes
    unknown = set(only) - set(codes)
    if unknown:
        raise ValueError(f"Unknown indicator codes: {sorted(unknown)}")
    return [c for c in codes if c in set(only)]


# ---------- I/O ----------


def fetch_indicator(
    code: str,
    out_dir: Path,
    session: requests.Session,
    settings: HttpSettings,
    start_year: int,
    end_year: int,
    country: str = config.WB_COUNTRY,
    per_page: int = config.WB_PER_PAGE,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch all pages of one indicator; return (manifest entry, call records)."""
    url = wb_url(settings.base_url, country, code)
    rows: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    files: list[str] = []
    page, pages, status = 1, 1, "ok"
    while page <= pages:
        path = out_dir / f"{code}_p{page}.json"
        params = wb_params(start_year, end_year, per_page, page)
        st, payload, rec = fetch_or_load(
            session,
            url,
            params,
            path,
            settings,
            is_valid=lambda p: parse_wb_page(p) is not None,
            sleep=sleep,
        )
        if rec:
            calls.append(rec)
        if st not in OK_STATUSES:
            status = st
            break
        parsed = parse_wb_page(payload)
        pages = parsed["pages"]
        rows += parsed["rows"]
        files.append(path.name)
        page += 1
    summary = summarize_wb_rows(rows)
    for rec in calls:
        rec["pages"] = pages
    entry = {
        "label": config.WB_INDICATORS.get(code),
        "status": status,
        "pages": pages,
        "files": files,
        **summary,
    }
    return entry, calls


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Fetch raw World Bank data.")
    parser.add_argument("--only", nargs="+", help="only these indicator codes")
    parser.add_argument(
        "--snapshot-date", type=date.fromisoformat, default=date.today()
    )
    parser.add_argument("--out-root", type=Path, default=config.RAW_WB_DIR)
    args = parser.parse_args(argv)
    try:
        codes = select_codes(config.WB_INDICATORS, args.only)
    except ValueError as exc:
        parser.error(str(exc))

    end_year = args.snapshot_date.year
    snapshot_dir = args.out_root / args.snapshot_date.isoformat()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = snapshot_dir / "manifest.json"
    manifest = load_manifest(
        manifest_path,
        {
            "source": "World Bank",
            "snapshot_date": args.snapshot_date.isoformat(),
            "endpoint": f"GET {config.WB_API}/country/{{country}}/indicator/{{code}}",
            "country": config.WB_COUNTRY,
            "years_requested": f"{config.WB_START_YEAR}:{end_year}",
            "indicators": {},
            "calls": [],
        },
    )
    settings = HttpSettings(base_url=config.WB_API, headers=config.WB_HEADERS)
    session = requests.Session()
    for code in codes:
        entry, calls = fetch_indicator(
            code, snapshot_dir, session, settings, config.WB_START_YEAR, end_year
        )
        manifest["calls"].extend(calls)
        manifest["indicators"][code] = entry
        write_manifest(manifest_path, manifest)
        print(
            f"{code:22} {entry['status']:8} {entry['n_values']:3} values "
            f"{entry['first_period']} -> {entry['last_period']} "
            f"({entry['pages']} page(s))"
        )
    bad = [c for c, e in manifest["indicators"].items() if e["status"] != "ok"]
    print(f"\nSnapshot: {snapshot_dir}")
    if bad:
        print(f"Not OK: {' '.join(bad)} -> re-run with --only {' '.join(bad)}")


if __name__ == "__main__":
    main()
