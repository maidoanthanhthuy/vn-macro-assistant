"""Smoke test for the World Bank API: the 8 indicators in docs/SCOPE.md for Vietnam.

Reports, per indicator: whether the code exists, how many years have data,
the first and latest year with data, and the latest value.
"""

from __future__ import annotations

import time

import requests

API = "https://api.worldbank.org/v2"
COUNTRY = "VNM"
INDICATORS = {
    "NY.GDP.MKTP.KD.ZG": "GDP growth (annual %)",
    "FP.CPI.TOTL.ZG": "Inflation, consumer prices (annual %)",
    "FR.INR.LEND": "Lending interest rate (%)",
    "PA.NUS.FCRF": "Official exchange rate (VND per USD)",
    "SL.UEM.TOTL.ZS": "Unemployment (% of labor force)",
    "BX.KLT.DINV.WD.GD.ZS": "FDI, net inflows (% of GDP)",
    "NE.EXP.GNFS.ZS": "Exports of goods and services (% of GDP)",
    "FM.LBL.BMNY.ZG": "Broad money growth (annual %)",
}


def fetch(code: str) -> tuple[str | None, list[tuple[int, float]]]:
    """Return (indicator name or None, [(year, value)] for non-null values)."""
    url = f"{API}/country/{COUNTRY}/indicator/{code}"
    resp = requests.get(url, params={"format": "json", "per_page": 200}, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    time.sleep(0.5)
    if len(body) < 2 or body[1] is None:  # unknown code -> error message, no rows
        return None, []
    name = body[1][0]["indicator"]["value"] if body[1] else None
    rows = [(int(r["date"]), r["value"]) for r in body[1] if r["value"] is not None]
    return name, sorted(rows)


def main() -> None:
    print(
        f"{'code':24} {'years':>5} {'first':>5} {'latest':>6}  latest value | WB name"
    )
    for code, label in INDICATORS.items():
        name, rows = fetch(code)
        if name is None:
            print(f"{code:24} INVALID CODE or no response ({label})")
            continue
        if not rows:
            print(f"{code:24} NO DATA for {COUNTRY} | {name}")
            continue
        first, latest = rows[0], rows[-1]
        print(
            f"{code:24} {len(rows):>5} {first[0]:>5} {latest[0]:>6}  "
            f"{latest[1]:.2f} | {name}"
        )


if __name__ == "__main__":
    main()
