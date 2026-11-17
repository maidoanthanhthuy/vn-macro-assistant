# User test: findings and changes

## Setup

- Deployed app on Neon (Postgres) with the OpenAI embedding backend; 4 invited users.
- Baseline: 2026-11-17 08:23:24 UTC. Every `app.query_log` / `app.feedback` row after it
  comes from the test. Snapshot below: first session, 2026-11-17 17:04-17:43
  (Asia/Ho_Chi_Minh).
- Numbers come from read-only queries on Neon (owner role); no rows were changed.

## What users asked

| | Count |
|---|---|
| Questions | 28 |
| Route `sql` | 12 |
| Route `out_of_scope` | 12 |
| Route `rag` | 4 |
| Route `both` | 0 |
| Step errors (`status = 'error'`) | 0 |
| Text-to-SQL `cannot_answer` | 2 |
| Feedback | 21 (17 up, 4 down) |

## Findings

1. **Beginner concept questions were declined.** Many users are new to investing and asked
   what a term means or how something works ("đầu cơ là gì", "mua cổ phiếu ở đâu có bị
   mất tiền không", "có ít tiền thì nên học đầu tư vào chỗ nào"). The router had no route
   for general knowledge, so these went to `out_of_scope` and got a refusal. Three of the
   four thumbs-down were on such refusals; one comment asked for more information.
2. **Users did not know what data the app holds.** Questions about real estate prices,
   gold, Nvidia, SpaceX and a stock outside the 15 symbols (VNG) were refused or answered
   "no data" without saying what *is* available. One comment asked whether data only went
   up to 2017, so the data range shown on screen was not clear enough.
3. **Personal advice requests are common** ("nên mua gì", "đầu tư vào đâu"). Declining is
   still right, but the refusal should point to something useful.
4. **Answer style:** one comment on a stock price answer said it gave no up/down trend and
   that the "Giải thích thêm" part felt too long. Not changed yet (noted for later).
5. **Off-topic and probing questions** (Python code, an English prompt about jailbreaks)
   were routed `out_of_scope` and declined correctly.
6. **Logging bug under concurrent use:** two pairs of questions asked within seconds of
   each other share one `request_id` (one cached agent object served every session and
   stored the id on itself). Answers were not affected, but log rows and feedback of
   those questions cannot be joined reliably. Fixed in commit 94d974c (ids are now
   thread-local).
7. **No session id:** the questions could not be grouped by user session. Fixed in commit
   94d974c: an anonymous `session_id` (random uuid4 made when the app opens, kept only in
   the Streamlit session) is stored with every log and feedback row.

## Changes

- **Route `explain`** (router prompt + answer prompt): concept or basic-knowledge
  questions about investing, the stock market or the economy get a 2-4 sentence general
  explanation, with no market numbers and no buy/sell advice. The code adds a note that it
  is a general explanation, not taken from the app's data, and one lookup question the
  app can answer (`suggestion`, chosen by the LLM from the data scope). Personal advice
  stays `out_of_scope`.
- **Data scope on refusals:** the answer step now returns `declined` (true for
  `out_of_scope` and when data is missing). The code then appends the data scope, built
  from the database at startup: the 15 stocks and 3 indices with the price date range,
  the annual indicators with their years (and the IMF forecast horizon), monthly CPI,
  SBV rate changes and the documents per type with their periods.
- **Main screen:** a short scope under the title (symbols, indices, indicators, and how
  recent each data set is), refreshed hourly, plus the "not investment advice" note.
- **Dev set:** 4 questions from the test added (q30-q33): two `explain` questions, one
  personal advice request (`out_of_scope`) and one stock outside the list (VNG, route
  `sql`, must say it is not covered). The official test set was not re-run.

## Dev-set check after the changes

Dev set only (33 questions, local database); the test set was not run.

- Router (`run_sql_dev --router`, prompt 5f64bbd9ce05): 33/33 routes as expected,
  including q30-q31 `explain`, q32 `out_of_scope` and q33 `sql`; $0.0031 in total.
- Agent (`run_sql_dev --agent`, final run 2026-11-17 18:45): 0 errors, $0.00057 and
  10.4 s per question on average.
  - q30-q31 (`explain`): 2-sentence explanation, no market numbers or advice, the
    general-knowledge note and a lookup suggestion (VN-Index's biggest yearly drop).
  - q32 (advice): declines, suggests a past-price question, data scope appended.
  - q33 (VNG): says VNG is not in the data, data scope appended.
  - Scope appended on 10 answers: the out-of-scope questions (q18-q20, q24, q25, q32)
    and missing or partial data (q11 documents from 2023, q23 VHM before its listing,
    q27 M2 for 2024, q33 VNG). Not on answers that give the latest value instead of the
    asked day (q26).
- Prompt tuning during the check: the first run appended the scope to q26 (answered with
  the latest close) and gave long term lists on `explain` answers; the prompt now says
  `declined` is false for a latest-value answer and limits `explain` to at most two
  specialised terms. The LLM sometimes returns no suggestion, so the code falls back to
  the first suggested question of the app.
- Seen once, not caused by these changes: in one run Text-to-SQL filtered HPG through
  `symbols.aliases` instead of `symbol`, got no rows and q06 said the data was missing
  (correct in the two other runs). Fixed below.

## Follow-up fixes

- **Suggestion wording:** the lead-in is now "Câu hỏi gợi ý:" and the prompt asks for the
  question as the user would type it (no "Bạn ..."), so the line no longer repeats "Bạn".
- **Symbol lookup:** only 6 of 18 symbols list their own ticker in `symbols.aliases`
  (FPT, SSI, VCB, VN30, and HNXINDEX / VNINDEX through "HNXIndex" / "VNIndex"); the
  other 12 (BID, CTG, GAS, HPG, MBB, MSN, MWG, TCB, VHM, VIC, VNM, VPB) do not, so an
  aliases-only filter on a ticker returns no rows. The SQL conventions now require both
  tests, `upper(s.symbol) = upper('<text>') OR ', ' || s.aliases || ',' ILIKE
  '%, <text>,%'`, and both SQL examples use this pattern (one with a lower-case ticker).
  The data was not changed.
- **Current price:** the router sent "giá ... hiện tại" (current price) to
  `out_of_scope` as a real-time price, for tickers and names alike (3/3 runs). The router
  prompt now says the current price is the latest daily close (`sql`, `latest`) and has
  a lower-case ticker example.
- Checks: q06 3/3 and the new q34 ("giá hpg hiện tại là bao nhiêu?") 3/3 correct in
  Text-to-SQL, all matched on `symbol`; router on the dev set 34/34 (prompt
  7eacfe7053d4); the agent answers q34 with HPG's close of 2026-11-10.
