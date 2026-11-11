# vn-macro-assistant

![CI](https://github.com/maidoanthanhthuy/vn-macro-assistant/actions/workflows/ci.yml/badge.svg)

A Vietnamese-language question-answering assistant for Vietnam's stock market and
macroeconomy. An agent routes each question to Text-to-SQL (prices, macro indicators,
policy events) or RAG (official NSO and SBV documents), or both, and answers with
numbers and citations. See [docs/SCOPE.md](docs/SCOPE.md).

## Project layout

```
docs/                  Scope, schema and design notes
eval/                  Evaluation set (seed_questions.csv)
scripts/smoke_tests/   Checks that each data source downloads for Vietnam
sql/                   Database schema (schema.sql)
src/vnmacro/
  ingest/              Fetch and load data into PostgreSQL / pgvector
  tools/               Text-to-SQL and RAG tools
  agent/               Router and answer generation
  app/                 Streamlit UI
tests/                 pytest tests
data/                  Local data (only data/manual/ is committed)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # then fill in real values
```

## Database

PostgreSQL 16 + pgvector runs in Docker on `127.0.0.1:5432` (port from `POSTGRES_PORT` in
`.env`). It does not start on boot; start it by hand when needed.

```bash
docker compose up -d      # start (data is kept in the named volume "pgdata")
docker compose ps         # wait until the status shows "healthy"
docker compose stop       # stop, data is kept
```

Create the tables (first run, on an empty database):

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/schema.sql
```

Recreate the tables after changing `sql/schema.sql`:

> **WARNING: this DELETES ALL DATA in the database** (every table in the `public` schema).

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/schema.sql
```

Remove the container and its volume:

> **WARNING: `down -v` DELETES ALL DATA** (the `pgdata` volume is removed for good).

```bash
docker compose down -v
```

## Run tests

```bash
ruff check . && ruff format --check . && pytest
```
