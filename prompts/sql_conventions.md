# SQL conventions

Rules for writing PostgreSQL queries against the database described above.

## Output
- Return exactly one SELECT statement (a WITH ... SELECT is allowed). No other statements.
- No trailing semicolon.
- Always end with LIMIT, at most 200 rows.
- Do not round in SQL; return full precision. Rounding is done when the answer is written.
- Every percentage column in the result is in percent units, like
  cpi_monthly.inflation_yoy: 5.08 means 5.08%, and a 15% rise is 15, not 0.15.

## Transparency
- Return the inputs of every calculation, not only the final number. Example for a
  return: start_date, start_close, end_date, end_close, pct_change.
- Return the dates actually used, so the answer can state the date range.
- For macro values, also return indicators.source, and is_forecast and vintage from
  macro_annual, so the answer can name the source and flag forecasts.

## Relative time
- "Latest", "current", "this year" ("gần nhất", "hiện tại", "hiện nay", "năm nay")
  refer to the data, never to CURRENT_DATE or now().
- Example: "current price" of a symbol = the row with the largest date in daily_prices
  for that symbol. "Latest month" of CPI = MAX(month) in cpi_monthly.
- "Today", "yesterday" ("hôm nay", "hôm qua") are calendar days counted from the date
  given in the message ("Today's date: YYYY-MM-DD"), never from CURRENT_DATE. Query the
  latest trading day on or before that calendar day (date <= that day ORDER BY date DESC
  LIMIT 1), not the n-th latest row; the answer step says when it is an earlier day.
- Always return the actual date used.

## Prices and returns
- Stock prices are adjusted for dividends and bonus shares; use them for all percentage
  changes. Volume is the real traded volume (not adjusted).
- Returns are close-to-close, in percent.
- Period return (year, quarter, month):
  pct_change = (end_close / start_close - 1) * 100, where:
  - end = last trading day in the period: MAX(date) <= last calendar day of the period.
  - start = last trading day before the period: MAX(date) < first calendar day of the
    period.
  - Never hard-code trading dates such as 31 December; find them with MAX(date).
- If there is no close before the period (first period with data), start from the
  first close in the period (MIN(date) in the period) and return that date, so the
  answer can say the period is incomplete.
- "N months after event X": start = first trading day on or after the event date; end =
  last trading day on or before the event date + N months (MAX(date) <= event date +
  INTERVAL 'N months'). For a policy_events row the event date is effective_date.

## Market overview
- A question on the general state of the market ("tình hình thị trường", "thị trường dạo
  này thế nào") without a named stock or period: from the latest VN-Index date, return
  VN-Index's % change over 1 week, 1 month and since the start of the year (start =
  last close on or before the reference day; for the year, the last close of the
  previous year), plus the 3 stocks with the largest and the 3 with the smallest
  1-month % change. Label each row (row_type, period). Do not return every stock.

## Policy rates
- policy_events lists every SBV policy-rate change since 2020; a rate with no later row
  has not changed. The current ("hiện nay", "hiện tại") rate of a type = new_rate of its
  latest row; return effective_date so the answer can say since when it applies. Do not
  set cannot_answer because the last change is long before today's date.

## Why-questions
- A question why a stock or index rose or fell ("tại sao ... tăng", "vì sao ... giảm") is
  answered with the move itself: return the period's first and last close (with dates)
  and the % change. The answer step says the reasons are not in the data. Do not set
  cannot_answer because the data has no reasons; only when the move itself is missing.

## Symbols
- Find a stock or index the user names (ticker or name, any letter case) by matching
  both the ticker and the aliases:
  upper(s.symbol) = upper('<text>') OR ', ' || s.aliases || ',' ILIKE '%, <text>,%'.
  Always keep both tests: users often type tickers in lower case ("hpg", "vnm") and many
  tickers are not listed in aliases. The aliases test is a whole-name match, as in the
  column comment; never a plain substring match.

## Macro data and sources
- Default source when the user does not name one:
  - Past years (annual macro): World Bank.
  - Future years: IMF WEO (rows with is_forecast = true).
  - Monthly inflation: IMF CPI (cpi_monthly).
- If the user names a source, use exactly that source.
- Forecast values are rows with is_forecast = true; always return is_forecast and
  vintage with them. Never compute a forecast in SQL.
- Inflation = year-over-year % change of the CPI index versus the same month of the
  previous year (cpi_monthly.inflation_yoy).
- If the asked month is not in cpi_monthly yet, set cannot_answer = true and give the
  latest month in cpi_monthly in reason; the answer will come from the NSO monthly report
  (documents).

## Partly answerable questions
- A question often mixes a data part with a part the database cannot answer: a judgment
  ("có tin được không", "có tốt không", "có giàu không"), a reason, a prediction or a
  missing indicator. Answer the data part with SQL (cannot_answer = false) and say in
  notes which part the data cannot answer and why. The answer step explains that part.
  Example: "Dự báo tăng trưởng năm 2030 có đáng tin không?" -> return the IMF forecast
  row for 2030; notes: the data cannot judge how reliable the forecast is.

## Missing data
- If the data cannot answer the question (topic or indicator not in the database, period
  outside the data range), do not guess or estimate: set cannot_answer = true, sql = null,
  and state the reason in reason (for a period outside the data, give the available range
  from the data coverage above).
