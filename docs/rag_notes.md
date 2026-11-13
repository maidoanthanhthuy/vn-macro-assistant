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
