# vn-macro-assistant

![CI](https://github.com/maidoanthanhthuy/vn-macro-assistant/actions/workflows/ci.yml/badge.svg)

A Vietnamese-language question-answering assistant for Vietnam's stock market and
macroeconomy. An agent routes each question to Text-to-SQL (prices, macro indicators,
policy events) or RAG (official NSO and SBV documents), or both, and answers with
numbers and citations. See [docs/SCOPE.md](docs/SCOPE.md).

## Project layout

```
docs/                  Scope and design notes
eval/                  Evaluation set (seed_questions.csv)
scripts/smoke_tests/   Checks that each data source downloads for Vietnam
src/vnmacro/
  ingest/              Fetch and load data into PostgreSQL / pgvector
  tools/               Text-to-SQL and RAG tools
  agent/               Router and answer generation
  app/                 Streamlit UI
tests/                 pytest tests
data/                  Local data (not committed)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # then fill in real values
```

## Run tests

```bash
ruff check . && ruff format --check . && pytest
```
