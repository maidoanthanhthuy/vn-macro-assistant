"""Fetch raw IMF series (headline CPI, WEO GDP growth) as SDMX-CSV with all attributes.

Run from the repository root:

    PYTHONPATH=src python -m vnmacro.ingest.fetch_imf
    PYTHONPATH=src python -m vnmacro.ingest.fetch_imf --only WEO_NGDP_RPCH

Each series is saved byte for byte to <out-root>/<snapshot date>/<NAME>.csv. The IMF
always returns the latest data, whatever the snapshot date. Existing files are never
overwritten; a re-run only fetches the missing series. manifest.json logs every call.
"""

from __future__ import annotations

import argparse
import csv
import io
import time
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from typing import Any

import requests

from vnmacro import config
from vnmacro.ingest.common import (
    HttpSettings,
    fetch_or_load,
    load_manifest,
    write_manifest,
)

# ---------- pure helpers ----------


def imf_url(api: str, flow: str, key: str) -> str:
    """Build the SDMX 3.0 data URL for one flow ('AGENCY/ID') and series key."""
    return f"{api}/data/dataflow/{flow}/+/{key}"


def parse_sdmx_csv(text: str) -> list[dict[str, str]]:
    """Parse SDMX-CSV text into one dict per observation."""
    return list(csv.DictReader(io.StringIO(text)))


def is_valid_sdmx_csv(text: Any, period_col: str = config.IMF_PERIOD_COL) -> bool:
    """True if the text is SDMX-CSV with a period column and at least one row."""
    if not isinstance(text, str):
        return False
    rows = parse_sdmx_csv(text)
    return bool(rows) and period_col in rows[0]


def summarize_sdmx_rows(
    rows: list[dict[str, str]],
    period_col: str = config.IMF_PERIOD_COL,
    value_col: str = config.IMF_VALUE_COL,
) -> dict[str, Any]:
    """Count rows and non-empty values; give the first/last period with a value."""
    periods = sorted(r[period_col] for r in rows if (r.get(value_col) or "").strip())
    return {
        "n_rows": len(rows),
        "n_values": len(periods),
        "first_period": periods[0] if periods else None,
        "last_period": periods[-1] if periods else None,
    }


def series_attributes(
    rows: list[dict[str, str]], names: Iterable[str]
) -> dict[str, Any]:
    """Return each attribute's value; a sorted list if rows disagree, None if absent."""
    out: dict[str, Any] = {}
    for name in names:
        values = sorted({r[name] for r in rows if r.get(name)})
        out[name] = values[0] if len(values) == 1 else (values or None)
    return out


def select_names(names: Iterable[str], only: Iterable[str] | None) -> list[str]:
    """Keep only `only` (all if None); raise on unknown names."""
    names = list(names)
    if only is None:
        return names
    unknown = set(only) - set(names)
    if unknown:
        raise ValueError(f"Unknown series: {sorted(unknown)}")
    return [n for n in names if n in set(only)]


# ---------- I/O ----------


def fetch_series(
    name: str,
    spec: dict[str, Any],
    out_dir: Path,
    session: requests.Session,
    settings: HttpSettings,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Fetch one series; return (manifest entry, call record or None)."""
    url = imf_url(settings.base_url, spec["flow"], spec["key"])
    path = out_dir / f"{name}.csv"
    status, text, rec = fetch_or_load(
        session,
        url,
        {"attributes": "all"},
        path,
        settings,
        is_valid=is_valid_sdmx_csv,
        as_json=False,
        sleep=sleep,
    )
    rows = parse_sdmx_csv(text) if text else []
    summary = summarize_sdmx_rows(rows)
    entry = {
        "flow": spec["flow"],
        "key": spec["key"],
        "status": "ok" if status in ("ok", "existing") else status,
        "file": path.name if rows else None,
        **summary,
        **series_attributes(rows, spec["attributes"]),
    }
    if rec:
        rec.update(summary)
    return entry, rec


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Fetch raw IMF series.")
    parser.add_argument("--only", nargs="+", help="only these series names")
    parser.add_argument(
        "--snapshot-date", type=date.fromisoformat, default=date.today()
    )
    parser.add_argument("--out-root", type=Path, default=config.RAW_IMF_DIR)
    args = parser.parse_args(argv)
    try:
        names = select_names(config.IMF_SERIES, args.only)
    except ValueError as exc:
        parser.error(str(exc))

    snapshot_dir = args.out_root / args.snapshot_date.isoformat()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = snapshot_dir / "manifest.json"
    manifest = load_manifest(
        manifest_path,
        {
            "source": "IMF Data Portal (SDMX 3.0)",
            "snapshot_date": args.snapshot_date.isoformat(),
            "endpoint": f"GET {config.IMF_API}/data/dataflow/{{flow}}/+/{{key}}",
            "format": config.IMF_HEADERS["Accept"],
            "series": {},
            "calls": [],
        },
    )
    settings = HttpSettings(
        base_url=config.IMF_API,
        headers=config.IMF_HEADERS,
        timeout=config.IMF_TIMEOUT_SECONDS,
    )
    session = requests.Session()
    for name in names:
        entry, rec = fetch_series(
            name, config.IMF_SERIES[name], snapshot_dir, session, settings
        )
        if rec:
            manifest["calls"].append(rec)
        manifest["series"][name] = entry
        write_manifest(manifest_path, manifest)
        attrs = {a: entry[a] for a in config.IMF_SERIES[name]["attributes"]}
        print(
            f"{name:14} {entry['status']:8} {entry['n_values']:4} values "
            f"{entry['first_period']} -> {entry['last_period']} {attrs or ''}"
        )
    bad = [n for n, e in manifest["series"].items() if e["status"] != "ok"]
    print(f"\nSnapshot: {snapshot_dir}")
    if bad:
        print(f"Not OK: {' '.join(bad)} -> re-run with --only {' '.join(bad)}")


if __name__ == "__main__":
    main()
