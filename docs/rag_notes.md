# RAG Notes

Observations from retrieval checks. These are quick looks, not the official eval
(Phase 5).

## Retrieval smoke test 1 (Phase 2, step 9)

| Setting | Value |
|---|---|
| Date | 2026-11-13 |
| Model | `AITeamVN/Vietnamese_Embedding_v2`, commit `18b44161e041bf1d3a333ab5144b5b7b93f914d2` |
| Chunking | `heading_v1` (max 1500, min 300, overlap 0), 762 chunks, document snapshot 2026-11-12 |
| Search | exact dot product on normalized vectors (= cosine), top 5, no filters, no reranking |
| Latest NSO report in the database | 2026-10 |

Questions from `eval/seed_questions.csv`; for q16 only the RAG part
("Lạm phát tháng gần nhất là bao nhiêu?") was searched.

| Question | Answer chunk | Rank (of 762) | Months of the top 5 |
|---|---|---|---|
| q09 Latest report on inflation | `nso_report_2026_10_029` | 46 (not in top 5) | 2025-12, 2026-Q2 (SBV), 2026-09, 2025-12, 2026-09 |
| q10 Why CPI fell in June 2026 | `nso_report_2026_06_052` | 1 | all 2026-06 |
| q11 SBV reasons for 2023 rate cuts | none in data | - | 2026 SBV press conferences, 2025-12 NSO |
| q12 GDP in H1 2026 | `nso_report_2026_06_003` | 3 | all 2026-06 |
| q13 Exports in August 2026 | `nso_report_2026_08_026` | 2 | 2026-08 (4), 2026-09 (1) |
| q14 SBV credit policy for 2026 | `sbv_directive_2026_01_002` | 1 | 2026 directive, 2026-Q1..Q3 SBV |
| q16 (RAG part) Latest inflation | `nso_report_2026_10_029` | 37 (not in top 5) | 2025-12, 2025-12, 2026-03, 2026-06, 2026-06 |

Questions that name the period (q10, q12, q13, q14) find the answer in the top 3.
The full top-5 lists (score, context, first 150 characters) were saved to
`data/reports/retrieval_smoke_heading_v1.md` (local, not in git).

### Findings

1. **Relative periods miss.** Questions with a relative period ("tháng gần nhất") do not
   find the latest report: q09 ranks the answer 46th, q16 37th. Nothing in the query points
   to 2026-10, so general text about inflation from other months ranks higher, and q16's
   rank 2 even holds a December 2025 number (wrong month).
   **Phase 4:** resolve the period first (e.g. latest `reference_period` of the doc type)
   and filter on `rag.documents` period columns before the semantic search.
2. **q11 misses because there are no 2023 documents.** Known: q11 needs the 2022-2023 SBV
   documents planned for a later version. The top 5 are 2026 texts (wrong year); the agent
   must say the data does not cover 2023 instead of answering from them.
3. **q12 answer needs care.** In `nso_report_2026_06_003` the assessment "đạt mức tăng
   trưởng khá" refers to **Q2 2026** GDP (+8.39%), not the first six months. The H1 figure
   is a separate sentence: "GDP sáu tháng đầu năm 2026 tăng 8,18% so với cùng kỳ năm
   trước (cùng kỳ năm 2025 tăng 7,63%)." Keep the two apart when writing the eval
   reference answer.
4. **Labelling bug.** The closing summary at the end of an NSO report is labelled with the
   heading of the report's last section (e.g. `nso_report_2025_12_090` and
   `nso_report_2026_09_090` carry "III. MỘT SỐ VẤN ĐỀ XÃ HỘI › 8. Bảo vệ môi trường và
   phòng chống cháy, nổ"). The plan was to fix it in extraction/chunking so the summary
   gets its own label.
   **Fixed 2026-11-13.** The summary has no heading in the source but
   always starts with "Khái quát lại," (once, in the 4 quarterly reports; monthly reports
   have no summary). `extract_text` now adds a level-1 heading "Kết luận chung" before that
   paragraph (`config.NSO_CLOSING_MARKERS`, `config.NSO_CLOSING_HEADING`; the heading is not
   in the source). After rerunning `extract_text` -> `chunking` -> `vnmacro.rag.build`:
   still 762 chunks, 24 chunks in the 4 quarterly reports changed (summary chunks now
   labelled "<report> › Kết luận chung"), only those 24 re-embedded; all checks pass and
   the q10 answer chunk is still rank 1 (score 0.5980). The top-5 tables above were made
   before this fix.

## Retrieval check 2 (Phase 4, step 4b): period filter + semantic search

| Setting | Value |
|---|---|
| Date | 2026-11-17 |
| Model, chunking | as in smoke test 1 (762 chunks, closing-summary labels fixed) |
| Pipeline | router -> period resolver -> `vnmacro.agent.retrieve` (filter: documents whose period overlaps the resolved period; none overlap -> search all, with a note) |
| Search | exact dot product, top 5, as `vnmacro_reader` |
| Query | the full dev question (smoke test 1 used only the RAG part for q16) |

Run: `python -m vnmacro.eval.run_sql_dev --rag`. Graded at document level (an answer
document from `config.EVAL_RAG_DOCS` in the top 5); the answer-chunk rank is shown for
comparison with smoke test 1.

| Question | Period filter | Answer doc in top 5 (rank) | Answer chunk rank | Smoke test 1 chunk rank |
|---|---|---|---|---|
| q09 Latest report on inflation | 2026-10 | yes (1) | 2 | 46 |
| q10 Why CPI fell in June 2026 | 2026-06 | yes (1) | 1 | 1 |
| q11 SBV reasons for 2023 rate cuts | 2023 -> no documents, searched all (note) | n/a | - | - |
| q12 GDP in H1 2026 | 2026-01..2026-06 | yes (1) | 4 | 3 |
| q13 Exports in August 2026 | 2026-08 | yes (1) | 2 | 2 |
| q14 SBV credit policy for 2026 | 2026 | yes (1) | 1 | 1 |
| q16 Latest inflation + bank stocks | 2026-10 | yes (3) | not in top 5 | 37 |

Answer document in the top 5 for 6 of 6 graded questions. Model load 9.6 s once per
process; retrieval (embed + search) 190 ms mean per question.

### Findings

1. **The period filter fixes relative periods.** q09's answer chunk moves from rank 46
   to 2. q16 with only its RAG part as the query ("Lạm phát tháng gần nhất là bao
   nhiêu?") ranks the answer chunk 2 (smoke test 1: 37).
2. **The full hybrid question dilutes the search.** With the full q16 question (inflation
   + bank stocks) the top 2 are chunks of the 2026 SBV directive (banking words), and the
   October CPI chunk drops out of the top 5. The annual directive overlaps every month
   of 2026, so it survives any monthly filter. For `both` questions the agent should
   search with the document part of the question only.
3. **Document-level grading is easy after filtering.** A one-month filter leaves one
   NSO report plus the annual directive, so "answer doc in top 5" is nearly guaranteed;
   chunk-level ranks (and answer quality in Phase 5) are the stricter measure.
4. q11 falls back to all documents with a note, as intended (no 2023 documents).

## Retrieval check 3 (Phase 4, step 4b): search with the router's rag_query

Same setting as check 2, but the router now also returns `rag_query` (the document part
of the question, `rag`/`both` only) and `retrieve` searches with it instead of the full
question (fallback: the full question when `rag_query` is null).

| Question | rag_query | Answer doc rank | Answer chunk rank | Check 2 chunk rank |
|---|---|---|---|---|
| q09 | Báo cáo kinh tế - xã hội tháng gần nhất nói gì về lạm phát? | 1 | 2 | 2 |
| q10 | Vì sao chỉ số giá tiêu dùng tháng 6/2026 giảm so với tháng trước? | 1 | 1 | 1 |
| q11 | NHNN đưa ra lý do gì khi giảm lãi suất điều hành trong năm 2023? | n/a | - | - |
| q12 | Báo cáo 6 tháng đầu năm 2026 đánh giá tăng trưởng GDP như thế nào? | 1 | 4 | 4 |
| q13 | Tình hình xuất khẩu được mô tả thế nào trong báo cáo tháng 8/2026? | 1 | 2 | 2 |
| q14 | NHNN định hướng điều hành tín dụng năm 2026 ra sao? | 1 | 1 | 1 |
| q16 | Lạm phát tháng gần nhất là bao nhiêu | 1 | 2 | not in top 5 |

Two identical runs; router still 25/25 on the dev set (prompt version 156b5930ebb8).
Retrieval 100-110 ms per question after a 5-7 s model load.

### Findings

1. **q16 fixed:** without the bank-stock part, the October CPI chunk is rank 2 again.
2. **Rephrasing hurts.** Two earlier prompt versions let the LLM rewrite the query.
   Dropping time words turned q12 into a generic GDP question (the Q1 report won,
   answer doc rank 4); a free rewrite of q16 ("Lạm phát được ghi nhận bao nhiêu?") put
   the answer chunk out of the top 5. The final rule: copy the user's words, remove only
   the parts `sql` answers.
3. **q11 routing is unstable:** across runs the router sent q11 to `rag` (2023 period,
   fallback note) or `out_of_scope` (the documents start in 2025). Both lead to a
   "not covered" answer, but the answer step must handle either.

## Retrieval check 4 (Phase 7, step 7a): local vs OpenAI embeddings

| Setting | Value |
|---|---|
| Date | 2026-11-17 |
| Models | `AITeamVN/Vietnamese_Embedding_v2` (local, CPU) vs OpenAI `text-embedding-3-large`, `dimensions=1024` (`model_name` `openai/text-embedding-3-large@dim1024`) |
| Chunk text | the same `embedding_text()` (context + blank line + text), 762 chunks |
| Embedding cost (OpenAI) | 480,594 input tokens, $0.062 at $0.13 per 1M tokens; 19 s |
| Pipeline | one router call per question, then the same rag_query and period filter for both models; top 20 |

Run: `python -m vnmacro.eval.run_sql_dev --embeddings local,openai` (two identical runs).

| Question | Period filter | Answer chunk rank, local | Answer chunk rank, OpenAI |
|---|---|---|---|
| q09 Latest report on inflation | 2026-10 | 2 | 4 |
| q10 Why CPI fell in June 2026 | 2026-06 | 1 | 1 |
| q11 SBV reasons 2023 | 2023 (no documents) | - | - |
| q12 GDP in H1 2026 | 2026-01..2026-06 | 4 | 3 |
| q13 Exports in August 2026 | 2026-08 | 2 | 1 |
| q14 SBV credit policy 2026 | 2026 | 1 | 1 |
| q16 Latest inflation (RAG part) | 2026-10 | 2 | 3 |

Answer chunk in the top 5: 6 / 6 with both models. Mean retrieval time (embed the
question + search): local about 240 ms after a 5-10 s model load; OpenAI about 620 ms
(API call), no model load and no torch in the app. On this small dev set the two models
are equivalent; the deployed app uses OpenAI to avoid torch (several GB) in the image.
