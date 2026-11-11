# Data Sources: Stock and Index Prices

Status: smoke-tested on 2026-11-09 (see "Smoke test results" at the end). Scripts are in
`scripts/smoke_tests/`; they print results only and load nothing into a database.

## Policy

- vnstock and vnai are quarantined on PyPI pending a security review. Do not install vnstock
  by any other route (GitHub, custom installer) until that review is finished.
- Prices are fetched directly from the KBS API (primary) or the Vietcap API (fallback).
  Vietcap is also the cross-check source for index data (indices only, never merged into
  the main data; see "Reference sources").
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

KBS answers are from the 2026-11-09 smoke test. Vietcap was tested for indices only on
2026-11-10 (see "Vietcap index cross-check").

- [x] Adjusted or unadjusted? KBS: **prices are adjusted, volume is not** (confirmed
      2026-11-11 against CafeF; see "KBS price adjustment check" below).
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
5. There is no independent reference for stock prices yet: Vietcap is not used to check
   stocks because its price adjustment method may differ from KBS.

## Reference sources (validation only)

### Vietcap: cross-check for index data

- Used only to check the KBS index series (VNINDEX, VN30, HNXINDEX). Not used for stock
  prices, because the price adjustment method may differ between the two sources.
- Vietcap numbers are never merged into the main data; KBS stays the primary source.
- Fetcher: `src/vnmacro/ingest/fetch_vietcap.py`; raw responses in
  `data/external/vietcap/<snapshot date>/`. Results: see "Vietcap index cross-check".

### Mendeley: rejected

Mendeley Data, "Unrewarded but Amplified" (https://data.mendeley.com/datasets/8584zp8rtr/1,
CC BY 4.0, raw data from Vietstock) was downloaded on 2026-11-10 and **is not used as a
reference**:

- Its `vnindex_daily.csv` does not match the real VN-Index: e.g. 2024-12-31 is 324.41
  against 1266.78 (KBS), and the ratio to KBS drifts from 1.18 to 5.41 over time.
- The correlation of daily returns with KBS VNINDEX is 0.02.
- It has values on days the market was closed (Tet, 1 January, 30 April, 2 September;
  371 such dates), and the values change on those days.
- Stock tickers are anonymised (VN001-VN627), and every ticker has a row on every date,
  so it cannot be used to check specific stocks or trading days.

## Smoke test results (2026-11-09)

| Source | Works? | Data range | Notes |
|---|---|---|---|
| KBS daily prices (stocks) | Yes | Mid-2016 to today (FPT from 2016-09-21, VCB 2016-07-25, HPG 2016-05-25) | No data before mid-2016, so 2015-01 to mid-2016 is missing for stocks. Probably adjusted prices. (Resolved 2026-11-11: see 'KBS price adjustment check') |
| KBS daily prices (indices) | Yes | VNINDEX 2015-01-05 to today | Values are sometimes JSON numbers, sometimes strings: always parse as float. |
| Vietcap (fallback) | Yes, indices (tested 2026-11-10) | Indices from 2014 to today | Used as a cross-check for indices. Stocks not tested. |
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
  (Resolved 2026-11-11: see 'KBS price adjustment check')
- Extra field `va` (traded value) appears on some rows. The row for the current day may be
  incomplete (`va` missing), so take snapshots after the market close.

### KBS snapshot 2026-11-10 (`src/vnmacro/ingest/fetch_kbs.py`)

- All 18 symbols fetched (48 calls, no errors, no retries). Stocks from 2017-01-03
  (TCB 2018-06-04, VPB 2017-08-17, VHM 2018-05-17: listed later); indices from 2015-01-05.
- TCB, VPB and VHM were refetched year by year (fewer rows than weekdays). The yearly
  totals equal the single-call totals, which confirms **no per-request row cap**.
- The three indices differ by 1-3 rows (VNINDEX 2,958, VN30 2,956, HNXINDEX 2,959).
  Dates present in only some of them:

  | Date | VNINDEX | VN30 | HNXINDEX | 15 HOSE stocks |
  |---|---|---|---|---|
  | 2016-03-04 | yes | missing | yes | not checked (stocks start 2017) |
  | 2018-01-23 | missing | missing | yes | all missing |
  | 2018-01-24 | yes (suspect) | missing | yes | all missing |

- Findings and decisions (confirmed by the Vietcap cross-check below):
  1. **HOSE did not trade on 2018-01-23 and 2018-01-24** because of a system failure
     (confirmed from HOSE / SSC announcements reported in the press). HNX traded normally.
     HOSE resumed trading on 2018-01-25. Sources (VnEconomy):
     - https://vneconomy.vn/hose-thong-bao-ngung-giao-dich-ngay-23-1-2018.htm
     - https://vneconomy.vn/hose-tiep-tuc-ngung-giao-dich-ngay-24-1.htm
     - https://vneconomy.vn/tu-25-1-hose-chinh-thuc-giao-dich-tro-lai.htm
     - The KBS VNINDEX row for 2018-01-24 is **fake**: its OHLCV is copied from 2018-01-22
       (o 1066.86, h 1088.05, l 1066.61, c 1087.42, v 246,215,500). Drop it at load time.
     - The Vietcap rows with volume 0 on these dates are placeholders, not trading days.
  2. **VNINDEX 2018-01-22:** KBS close 1087.42, Vietcap 1086.51 (0.08% apart). The failure
     happened during the closing (ATC) session; according to VnEconomy, the close for that
     day was taken as the last matched price of the day. Which of the two values equals
     that price is not verified. Keep the KBS value.
  3. **VN30 2016-03-04:** KBS is missing a real trading day (Vietcap has a normal row:
     close 580.94, volume 40.5 million). Do not fill it from Vietcap.
  4. **VNINDEX 2016-03-04:** the KBS volume (121,565,340) is wrong: it repeats 2016-03-03
     (Vietcap: 131,099,670). The close matches Vietcap (573.65). At load time keep the
     prices and set the volume to NULL.
- Handling (at the cleaning / database load step, raw files stay unchanged): apply the
  decisions above, and add automatic checks for rows whose OHLCV duplicates another date
  and for dates present in an index but not in the stocks of the same exchange (or the
  reverse).

### Vietcap index cross-check (2026-11-10, `src/vnmacro/ingest/fetch_vietcap.py`)

- Vietcap symbols: `VNINDEX`, `VN30`, `HNXIndex` (from the vnstock source at commit
  `71b853f0db`, read only). One request per index, 3,095 rows each (from 2014-06-23);
  compared from 2015-01-05. No weekend dates in Vietcap.
- Dates in only one source: none only in KBS. Only in Vietcap: VNINDEX 2018-01-23
  (placeholder); VN30 2016-03-04 (real row), 2018-01-23 and 2018-01-24 (placeholders).
  HNXINDEX: none.
- Close differences on common dates:

  | Index | Common dates | Max difference | Dates above 0.1% |
  |---|---|---|---|
  | VNINDEX | 2,958 | 0.33% (2015-10-02) | 5 |
  | VN30 | 2,956 | 1.24% (2016-02-29) | 17 |
  | HNXINDEX | 2,959 | 0.82% (2015-03-24) | 18 |

  Dates above 0.1%:
  - VNINDEX: 2015-10-02, 2018-02-28, 2018-11-13, 2019-03-14, 2019-09-23.
  - VN30: 2015-10-02, 2016-02-29, 2016-04-22, 2016-11-24, 2017-05-03, 2018-02-22,
    2018-02-28, 2018-11-13, 2019-03-14, 2019-07-26, 2019-07-29, 2020-03-30, 2020-04-09,
    2020-09-22, 2020-10-19, 2021-02-08, 2021-03-24.
  - HNXINDEX: 2015-03-02, 2015-03-19, 2015-03-20, 2015-03-24, 2015-03-25, 2015-03-26,
    2015-04-08, 2015-04-10, 2015-04-14, 2015-04-20, 2016-03-15, 2016-04-06, 2016-11-28,
    2017-12-07, 2017-12-26, 2020-01-08, 2021-01-07, 2021-08-20.

  All of them are before 09/2021; since then the two sources match. KBS stays the
  primary source.

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

### World Bank and IMF raw snapshot 2026-11-10 (`fetch_worldbank.py`, `fetch_imf.py`)

- World Bank (`data/raw/worldbank/2026-11-10/`): all 8 indicators OK, one page each,
  26 rows (2000-2025; the API returns no 2026 row although 2026 was requested).
  Latest year with a value: FR.INR.LEND 2023 (24 values), PA.NUS.FCRF 2024 (25),
  FM.LBL.BMNY.ZG 2022 (23); the other five 2025 (26). Two calls needed one retry.
- IMF CPI (`data/raw/imf/2026-11-10/CPI.csv`, SDMX-CSV with `attributes=all`):
  **1,521 rows, of which 1,223 are empty placeholders** (1900-M01 to 2001-M11, empty
  `OBS_VALUE`). The 298 rows with values cover 2001-M12 to 2026-M09 with no missing
  month. `REFERENCE_PERIOD` is `2024A` on every row (index, 2024 = 100). At load time,
  skip rows with an empty `OBS_VALUE`.
- IMF WEO (`data/raw/imf/2026-11-10/WEO_NGDP_RPCH.csv`): 52 values, 1980-2031.
  `PUBLICATION_DATE = 2026-10-13T02:00:00Z` (WEO October 2026),
  `LATEST_ACTUAL_ANNUAL_DATA = 2025` (one value for the whole series), so 2026-2031
  (6 years) are forecasts.

### KBS price adjustment check (2026-11-11)

**Conclusion: KBS returns ADJUSTED prices (for dividends and bonus shares) and REAL,
unadjusted volume.** Checked by MĐTT on CafeF in a browser on 2026-11-11, trading day
2025-12-31. CafeF shows prices in thousand VND, with a board close ("Đóng cửa") and an
adjusted close ("Điều chỉnh"):

| Ticker | CafeF close (board) | CafeF adjusted | Database (KBS) close | CafeF volume | Database volume |
|---|---|---|---|---|---|
| HPG | 26.40 | 23.57 | 23,565 | 20,149,700 | 20,149,700 |
| VCB | 57.50 | 57.02 | 57,078 | 2,530,800 | 2,530,800 |
| FPT | 95.80 | 85.91 | 85,932 | 3,082,600 | 3,082,600 |

- The KBS close matches CafeF's adjusted close within about 0.1% (rounding and possibly
  slightly different adjustment factors), and is 0.7%-11% below the board close.
- Volume matches CafeF exactly, so it is the real traded volume, not scaled for bonus
  shares. Consequence: adjusted close x volume is not the traded value of the day.
- Adjusted prices change when a later snapshot includes new corporate actions, so price
  levels (not only returns) depend on the snapshot date.
- Unadjusted board prices are not stored (idea for a later version in docs/SCHEMA.md).

### Database load checks (`src/vnmacro/ingest/load_db.py`)

- Known data fixes live in one file, `data/manual/price_fixes.csv` (symbol, date, action,
  reason). Actions: `drop_row` (fake row), `null_volume` (wrong volume, prices kept),
  `known_missing` (a missing date with a known or checked reason; skipped by the date
  mismatch warning).
- **Daily move warning uses each exchange's price band:** HOSE +/-7%, HNX +/-10%, plus
  0.1 percentage point for rounding of adjusted prices. The band is the limit a price
  cannot pass in a normal session, so a larger close-to-close move points to a data error,
  a corporate action not adjusted, or a special session (e.g. a first trading day). The
  exchange comes from `symbols.exchange` and applies to stocks and indices alike.
- **VHM 2018-05-18 and 2018-05-21** are missing in KBS although VNINDEX and VN30 traded.
  Vietcap (`data/external/vietcap/2026-11-11/VHM.json`, checked 2026-11-11) has rows with
  volume 0 on both dates, i.e. no trading in either source; the reason is unknown (VHM was
  listed on 2018-05-17). Recorded as `known_missing`; nothing is filled in.
  - Other oddities in the same Vietcap response (not used, noted only): 2018-05-22 has a
    volume of just 20 shares, and the response also holds rows from 2017, before the
    listing date, which look like API placeholders.

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
