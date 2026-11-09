"""Smoke test for the KBS daily price API (see docs/data_sources.md).

Checks: recent month for FPT and VNINDEX, full FPT history since 2015, the earliest
date available, any per-request row cap, and daily moves beyond the +/-7% HOSE band.
Prints results only; nothing is saved or loaded into a database.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import requests

BASE = "https://kbbuddywts.kbsec.com.vn/iis-server/investment"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
HOSE_BAND = 7.0


def fetch_daily(kind: str, symbol: str, start: date, end: date) -> list[dict]:
    """Fetch daily OHLCV rows for a stock ('stocks') or index ('index')."""
    url = f"{BASE}/{kind}/{symbol}/data_day"
    params = {"sdate": start.strftime("%d-%m-%Y"), "edate": end.strftime("%d-%m-%Y")}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    rows = resp.json().get("data_day") or []
    time.sleep(1)  # be polite: few, slow requests
    return sorted(rows, key=lambda r: str(r["t"]))


def describe(label: str, rows: list[dict]) -> None:
    """Print row count, date range and the first/last rows."""
    if not rows:
        print(f"{label}: NO DATA")
        return
    print(f"{label}: {len(rows)} rows, {rows[0]['t']} -> {rows[-1]['t']}")
    print(f"  keys: {sorted(rows[0])}")
    print(f"  first: {rows[0]}")
    print(f"  last:  {rows[-1]}")


def big_moves(rows: list[dict], band: float = HOSE_BAND) -> list[tuple]:
    """Return (date, prev_close, close, pct) for daily close changes beyond the band."""
    out = []
    for prev, cur in zip(rows, rows[1:], strict=False):
        pct = (float(cur["c"]) / float(prev["c"]) - 1) * 100
        if abs(pct) > band:
            out.append((cur["t"], prev["c"], cur["c"], round(pct, 2)))
    return out


def main() -> None:
    today = date.today()
    month_ago = today - timedelta(days=31)

    print("== (1) Last month ==")
    describe("FPT", fetch_daily("stocks", "FPT", month_ago, today))
    describe("VNINDEX", fetch_daily("index", "VNINDEX", month_ago, today))

    print("\n== (2) Full FPT history in one request (2015-01-01 -> today) ==")
    one_call = fetch_daily("stocks", "FPT", date(2015, 1, 1), today)
    describe("FPT one call", one_call)

    print("\n== (3) FPT history fetched year by year (detects a per-request cap) ==")
    by_year: dict[str, dict] = {}
    for year in range(2015, today.year + 1):
        rows = fetch_daily("stocks", "FPT", date(year, 1, 1), date(year, 12, 31))
        print(f"  {year}: {len(rows)} rows")
        for r in rows:
            by_year[str(r["t"])] = r
    yearly = [by_year[k] for k in sorted(by_year)]
    describe("FPT year by year", yearly)
    print(f"  one call rows = {len(one_call)}, year-by-year rows = {len(yearly)}")

    print("\n== (4) Earliest date probe (request from 2000) ==")
    describe(
        "FPT since 2000",
        fetch_daily("stocks", "FPT", date(2000, 1, 1), date(2016, 1, 1)),
    )

    print(f"\n== (5) FPT daily close moves beyond +/-{HOSE_BAND}% ==")
    moves = big_moves(yearly)
    for m in moves:
        print(f"  {m[0]}: {m[1]} -> {m[2]} ({m[3]:+}%)")
    print(f"  total: {len(moves)}")

    print("\n== (6) VNINDEX full range (2015-01-01 -> today) ==")
    describe("VNINDEX full", fetch_daily("index", "VNINDEX", date(2015, 1, 1), today))


if __name__ == "__main__":
    main()
