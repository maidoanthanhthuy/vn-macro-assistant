# Data Sources: Stock and Index Prices

Status: smoke-tested on 2026-11-09 (see "Smoke test results" at the end). Scripts are in
`scripts/smoke_tests/`; they print results only and load nothing into a database.

## Policy

- vnstock and vnai are quarantined on PyPI pending a security review. Do not install vnstock
  by any other route (GitHub, custom installer) until that review is finished.
- Prices are fetched directly from the KBS API (primary) or the Vietcap API (fallback).
  Both are unofficial, undocumented APIs that may change without notice, with unclear terms
  of use. Use them for learning purposes only.
- Fetch once, save a snapshot to `data/raw/` (gitignored), and never commit raw data.
  The app reads only from the snapshot / PostgreSQL and never calls these APIs at runtime.
- Every snapshot records: fetch date (snapshot date), source (KBS or Vietcap), endpoint,
  date range, and whether prices are adjusted or unadjusted.

## How the endpoints were found

Read-only review of the vnstock source on GitHub (https://github.com/thinh-vu/vnstock).
The package was not installed and none of its code was run.

- Commit read: `71b853f0db18c0d783c2b9eeafaedbcbf4d05fba` (2026-10-13), the last commit
  with the full codebase.
- Note: on 2026-11-07 the source code was removed from the `main` branch (commit
  `c75f763cd9f4d89fbf68e691936173815eeebfce`, "reposition repository as Generation 6 landing
  hub and retire legacy codebase"). `main` now holds only a README and images, so always
  read the source at the commit above.

Files read:

- `vnstock/explorer/kbs/const.py`, `vnstock/explorer/kbs/quote.py`
- `vnstock/explorer/vci/const.py`, `vnstock/explorer/vci/quote.py`
- `vnstock/core/utils/user_agent.py` (request headers)

## Primary: KBS (KB Securities Vietnam)

Daily OHLCV history, `GET` request:

| Asset | URL |
|---|---|
| Stock | `https://kbbuddywts.kbsec.com.vn/iis-server/investment/stocks/{symbol}/data_day` |
| Index | `https://kbbuddywts.kbsec.com.vn/iis-server/investment/index/{symbol}/data_day` |

- Query parameters: `sdate`, `edate`, both in `DD-MM-YYYY` format.
- Other intervals replace the `day` suffix: `week`, `month`, `1P`, `5P`, `30P`, `60P` (minutes).
- Response: JSON object; rows are under the key `data_day` (generally `data_{suffix}`).
- Row fields: `t` time, `o` open, `h` high, `l` low, `c` close, `v` volume
  (an extra `va` field, probably traded value, may be present).
- Units: stock prices are in VND (vnstock divides them by 1000 to get thousand VND);
  index values are in index points (no division).
- Index symbols: `VNINDEX`, `VN30`, `HNXINDEX` (also `UPCOMINDEX`, `HNX30`, `VN100`).
- Headers: vnstock sends only a browser User-Agent for KBS (no special Referer/Origin).

## Fallback: Vietcap (VCI)

Daily OHLCV history, `POST` request:

- URL: `https://trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart`
- JSON body:

  ```json
  {"timeFrame": "ONE_DAY", "symbols": ["FPT"], "to": 1767225600, "countBack": 2800}
  ```

  - `to`: end time as a Unix timestamp (seconds).
  - `countBack`: number of bars before `to` (vnstock uses business days in range + 1).
  - Other time frames: `ONE_HOUR`, `ONE_MINUTE`.
- Response: a list with one object per symbol; each holds parallel arrays
  `t`, `o`, `h`, `l`, `c`, `v`.
- Index symbols differ from KBS: `VNINDEX`, `VN30`, `HNXIndex` (also `HNXUpcomIndex`).
- Headers: `Referer` and `Origin` set to `https://trading.vietcap.com.vn/`, plus a browser
  User-Agent.

## Open questions for the smoke test

KBS answers are from the 2026-11-09 smoke test; Vietcap is not tested yet.

- [ ] Adjusted or unadjusted? KBS: **probably adjusted** (no FPT daily move beyond +/-7%
      in ten years). Still to confirm with the bonus-share check below.
- [x] Earliest date available (scope needs 2015-01-01). KBS: indices from 2015-01-05;
      stocks only from mid-2016 (see results). No per-request cap was found.
- [x] Format of `t`. KBS: string `"YYYY-MM-DD 07:00"` (date plus a fixed 07:00).
- [x] Price units. KBS: stocks in VND (e.g. FPT close `51000`); indices in points.
- [ ] Rate limits or blocking behavior. About 20 KBS requests, 1 s apart, all succeeded;
      no limit observed. Keep requests few and slow.

## How to check price adjustment

1. Pick one bonus-share issue (stock dividend) by one of the 15 tickers, with a known
   ex-rights date and ratio. Take it from the company's official announcement or the
   exchange's disclosure (HOSE), not from memory.
2. Fetch KBS daily prices for a few weeks around that ex-rights date.
3. Compare the close on the last trading day before the ex-rights date with the open/close
   on the ex-rights date:
   - **Unadjusted:** the price drops suddenly on the ex-rights date by roughly the bonus
     ratio (e.g. a 20% bonus issue gives a reference price of about 1/1.2 of the old
     price, a drop of about 17%), while the index does not move the same way.
   - **Adjusted:** no sudden drop on that date; instead, all prices before the date are
     scaled down by the same factor.
4. Record the result (ticker, ex-rights date, ratio, observed prices, verdict) here and
   in the snapshot metadata. Repeat the same check for Vietcap if it is used.
5. Cross-check the closes around that date against the Mendeley reference dataset below.

## Reference dataset (validation only)

Mendeley Data, "Unrewarded but Amplified": https://data.mendeley.com/datasets/8584zp8rtr/1

Used only to cross-check closing prices for 2015-2024. It is not a primary source.
Check its license and price adjustment method before comparing.

## Smoke test results (2026-11-09)

| Source | Works? | Data range | Notes |
|---|---|---|---|
| KBS daily prices (stocks) | Yes | Mid-2016 to today (FPT from 2016-09-21, VCB 2016-07-25, HPG 2016-05-25) | No data before mid-2016, so 2015-01 to mid-2016 is missing for stocks. Probably adjusted prices. |
| KBS daily prices (indices) | Yes | VNINDEX 2015-01-05 to today | Values are sometimes JSON numbers, sometimes strings: always parse as float. |
| Vietcap (fallback) | Not tested | - | Only needed if KBS fails, or to fill the 2015-2016 stock gap. |
| World Bank API | Yes, all 8 codes valid | From 1983-1996 (varies) to 2022-2025 | Latest year differs per indicator (table below). |
| IMF WEO (SDMX 3.0) | Yes | Real GDP growth 1980-2031 | 2026-2031 are IMF projections. |
| IMF CPI (SDMX 3.0) | Yes, monthly series exist | Headline CPI index 2001-12 to 2026-09 (y/y change from 2002-12) | 62 monthly Vietnam series, including CPI by COICOP group. |
| NSO monthly report | Yes | Monthly; archive has 33 listing pages (not checked back to 2022) | HTML summary page plus a `.docx` (full text) and `.xlsx` (tables). Text is easy to extract. |
| SBV press release | Yes | Monthly lending-rate release checked (Sep 2026) | The HTML page has no body text; the content is an attached text-based PDF. Extraction with pypdf works. |

### KBS (`scripts/smoke_tests/kbs_prices.py`)

- Last month: FPT 22 rows and VNINDEX 22 rows (2026-10-09 to 2026-11-09).
- Full FPT history in one request: 2,530 rows. Fetching year by year gives the same 2,530
  rows, so **no per-request row cap** was found.
- Earliest data: a request starting in 2000 returns nothing before 2016. Stocks start in
  mid-2016 and the date differs per ticker; VNINDEX starts on 2015-01-05.
  **Gap vs scope:** stock prices from 2015-01-01 to mid-2016 are not available from KBS.
- Price adjustment: 0 daily close moves beyond +/-7% (the HOSE band) for FPT from 2016 to
  2026. Prices are therefore **probably adjusted**. FPT's first close (8,926 VND in 2016)
  is low compared with today's 51,000, which also fits back-adjustment. Confirm with the
  bonus-share check above.
- Extra field `va` (traded value) appears on some rows. The row for the current day may be
  incomplete (`va` missing), so take snapshots after the market close.

### World Bank (`scripts/smoke_tests/world_bank.py`)

All 8 indicator codes in `docs/SCOPE.md` are valid and have data for Vietnam (VNM).

| Code | Years with data | First | Latest | Latest value |
|---|---|---|---|---|
| NY.GDP.MKTP.KD.ZG (GDP growth) | 41 | 1985 | 2025 | 8.02 |
| FP.CPI.TOTL.ZG (inflation) | 30 | 1996 | 2025 | 3.31 |
| FR.INR.LEND (lending rate) | 29 | 1993 | **2023** | 9.32 |
| PA.NUS.FCRF (VND per USD) | 40 | 1983 | **2024** | 24,164.89 |
| SL.UEM.TOTL.ZS (unemployment, ILO modeled) | 35 | 1991 | 2025 | 1.52 |
| BX.KLT.DINV.WD.GD.ZS (FDI, % GDP) | 41 | 1985 | 2025 | 4.27 |
| NE.EXP.GNFS.ZS (exports, % GDP) | 40 | 1986 | 2025 | 98.24 |
| FM.LBL.BMNY.ZG (broad money growth) | 28 | 1993 | **2022** | 5.68 |

Lending rate, exchange rate and broad money lag behind the other indicators (latest year
2022-2024).

### IMF Data Portal (`scripts/smoke_tests/imf.py`)

- API: `https://api.imf.org/external/sdmx/3.0` (not the retired dataservices.imf.org).
  Data query: `GET /data/dataflow/{agency}/{flow}/+/{key}` with header
  `Accept: application/vnd.sdmx.data+json;version=2.0.0`.
- WEO: flow `IMF.RES/WEO`, key `VNM.NGDP_RPCH.A` (dimensions COUNTRY.INDICATOR.FREQUENCY).
  The series has 52 annual values from 1980 to 2031; the latest are 2025 = 8.02 and
  2026 = 8.4 (projection).
- **Which WEO years are forecasts.** The series attribute `LATEST_ACTUAL_ANNUAL_DATA` is
  the new portal's equivalent of the old "Estimates Start After" column. It is returned
  **only** in the SDMX-CSV format with `attributes=all`
  (`Accept: application/vnd.sdmx.data+csv;version=2.0.0`), not in SDMX-JSON. For
  `VNM.NGDP_RPCH.A` it is `2025`, so 2026-2031 are forecasts.
  - Rule: `is_forecast = year > LATEST_ACTUAL_ANNUAL_DATA`, read per series (country and
    indicator), because the value can differ between series.
  - Fallback if the attribute is empty for a series: treat every year >= the year of
    `PUBLICATION_DATE` as a forecast, and log a warning.
  - `DERIVATION_TYPE` (observation level) is empty for every year, so it cannot be used.
- **WEO vintage.** Derived from `PUBLICATION_DATE`: April -> "WEO April YYYY",
  September/October -> "WEO October YYYY". At the smoke test, `PUBLICATION_DATE` was
  2026-10-13, i.e. **WEO October 2026** (`COUNTRY_UPDATE_DATE` for Vietnam: 2026-09-24).
  The flow `IMF.RES/WEO` always holds the latest vintage; older vintages are separate
  flows (e.g. `WEO_2026_APR_VINTAGE`, `WEO_2025_OCT_VINTAGE`).
- CPI: flow `IMF.STA/CPI`, dimensions COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY.
  **Monthly data exists for Vietnam**: 62 monthly series. Headline series (`COICOP_1999=_T`):
  `CPI._T.IX` (index, 2001-M12 to 2026-M09), `CPI._T.YOY_PCH_PA_PT` (y/y %, 2002-M12 to 2026-M09),
  `CPI._T.POP_PCH_PA_PT` (m/m %), plus `SRP_*` variants from 1995.
- TIME_PERIOD values use the key `value` (not `id`) in the SDMX-JSON structure.
- **Selected headline CPI series (loaded into the database): `VNM.CPI._T.IX.M`**
  (flow `IMF.STA/CPI`; COUNTRY=VNM, INDEX_TYPE=CPI, COICOP_1999=_T all items,
  TYPE_OF_TRANSFORMATION=IX, FREQUENCY=M).
  - IMF returns an **index level, not a % change**: reference period 2024 = 100
    (observation attribute `REFERENCE_PERIOD = 2024A`). Example: 2026-M09 = 108.66.
  - Inflation is computed from it as the y/y % change (same month of the previous year).
    Checked against IMF's own y/y series `VNM.CPI._T.YOY_PCH_PA_PT.M`: identical to 4
    decimals for 2010-M06, 2025-M01, 2025-M09, 2026-M01 and 2026-M09 (2026-M09: 5.0797%).
  - The `SRP_*` variants (from 1995) are not used; their meaning is not yet checked.
- The CPI data lags the NSO release by about a month (IMF latest 2026-M09; NSO already
  published October).

### Documents (`scripts/smoke_tests/documents.py`)

- **NSO**: the monthly report page (e.g. October 2026) is **HTML** (WordPress) and carries
  a summary of about 16.8k characters, easy to extract from `<p>` tags. Attachments: the
  full report as **`.docx`** (521 paragraphs, about 55.8k characters, extracted with the
  standard library only) and the statistical tables as **`.xlsx`**. Best source for RAG:
  the `.docx`.
- **SBV**: the press release page (Liferay) is **HTML with no body text**. The content is
  an attached **PDF** linked as `/documents/.../<name>.pdf/<uuid>?t=...`. The PDF is
  text-based, not scanned: 2 pages, extracted with `pypdf` with Vietnamese diacritics
  intact. Only this one release was checked; other SBV release types may differ.
