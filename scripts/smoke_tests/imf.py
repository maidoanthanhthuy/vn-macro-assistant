"""Smoke test for the new IMF Data Portal API (SDMX 3.0, api.imf.org).

Does NOT use the retired dataservices.imf.org API.
Checks: (1) Vietnam real GDP growth from WEO (incl. projections);
(1b) which WEO years are forecasts (LATEST_ACTUAL_ANNUAL_DATA) and the WEO vintage;
(2) whether the CPI dataset has MONTHLY series for Vietnam.
"""

from __future__ import annotations

import csv
import io

import requests

API = "https://api.imf.org/external/sdmx/3.0"
DATA_ACCEPT = {"Accept": "application/vnd.sdmx.data+json;version=2.0.0"}
# Series attributes such as LATEST_ACTUAL_ANNUAL_DATA are returned only in the CSV
# format with attributes=all (not in SDMX-JSON).
CSV_ACCEPT = {"Accept": "application/vnd.sdmx.data+csv;version=2.0.0"}


def fetch_series(flow: str, key: str) -> list[dict]:
    """Fetch an SDMX-JSON 2.0 data message and return one dict per series.

    flow: 'AGENCY/ID', e.g. 'IMF.RES/WEO'; key: dot-separated dimension values.
    Each dict holds the series dimension codes and a sorted list of (period, value).
    """
    url = f"{API}/data/dataflow/{flow}/+/{key}"
    resp = requests.get(url, headers=DATA_ACCEPT, timeout=120)
    resp.raise_for_status()
    body = resp.json()["data"]
    struct = body["structures"][0]["dimensions"]
    series_dims = struct["series"]
    # Value entries carry either "id" or "value" (TIME_PERIOD uses "value").
    periods = [v.get("id", v.get("value")) for v in struct["observation"][0]["values"]]
    out = []
    for skey, s in (body["dataSets"][0].get("series") or {}).items():
        dims = {
            d["id"]: d["values"][int(i)].get("id", d["values"][int(i)].get("value"))
            for d, i in zip(series_dims, skey.split(":"), strict=True)
        }
        obs = sorted(
            (periods[int(k)], v[0])
            for k, v in (s.get("observations") or {}).items()
            if v and v[0] not in (None, "")
        )
        out.append({**dims, "obs": obs})
    return out


def fetch_csv_rows(flow: str, key: str) -> list[dict]:
    """Fetch SDMX-CSV 2.0 with all attributes; one dict per observation."""
    url = f"{API}/data/dataflow/{flow}/+/{key}"
    resp = requests.get(
        url, params={"attributes": "all"}, headers=CSV_ACCEPT, timeout=180
    )
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def main() -> None:
    print("== (1) WEO: Vietnam real GDP growth (NGDP_RPCH), annual ==")
    weo = fetch_series("IMF.RES/WEO", "VNM.NGDP_RPCH.A")
    for s in weo:
        obs = s["obs"]
        print(f"  {len(obs)} obs, {obs[0][0]} -> {obs[-1][0]}")
        print("  recent:", obs[-8:])

    print("\n== (1b) WEO: forecast start and vintage (CSV, attributes=all) ==")
    rows = fetch_csv_rows("IMF.RES/WEO", "VNM.NGDP_RPCH.A")
    last_actual = {r["LATEST_ACTUAL_ANNUAL_DATA"] for r in rows}
    print(f"  LATEST_ACTUAL_ANNUAL_DATA: {last_actual}")
    print(f"  PUBLICATION_DATE: {rows[-1]['PUBLICATION_DATE']}")
    print(f"  COUNTRY_UPDATE_DATE: {rows[-1]['COUNTRY_UPDATE_DATE']}")
    if len(last_actual) == 1 and (year := last_actual.pop()).isdigit():
        fc = [r["TIME_PERIOD"] for r in rows if int(r["TIME_PERIOD"]) > int(year)]
        print(f"  forecast years (> {year}): {fc[0]} -> {fc[-1]}")

    print("\n== (2) CPI: all Vietnam series, by frequency ==")
    cpi = fetch_series("IMF.STA/CPI", "VNM.*.*.*.*")
    by_freq: dict[str, list[dict]] = {}
    for s in cpi:
        by_freq.setdefault(s["FREQUENCY"], []).append(s)
    for freq, items in sorted(by_freq.items()):
        print(f"  FREQUENCY={freq}: {len(items)} series")
    monthly = [s for s in by_freq.get("M", []) if s["obs"]]
    print(f"\n  Monthly series with data: {len(monthly)}")
    headline = [s for s in monthly if s["COICOP_1999"] == "_T"]  # all items
    print("  Headline (COICOP_1999=_T, all items):")
    for s in sorted(
        headline, key=lambda s: (s["INDEX_TYPE"], s["TYPE_OF_TRANSFORMATION"])
    ):
        obs = s["obs"]
        print(
            f"  {s['INDEX_TYPE']}.{s['COICOP_1999']}.{s['TYPE_OF_TRANSFORMATION']}: "
            f"{len(obs)} obs, {obs[0][0]} -> {obs[-1][0]}, last={obs[-1][1]}"
        )


if __name__ == "__main__":
    main()
