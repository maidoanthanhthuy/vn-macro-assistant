-- Schema for the RAG document layer (PostgreSQL 16 + pgvector).
-- Design notes: docs/SCHEMA.md. Kept apart from sql/schema.sql so the numeric tables
-- (schema public) and the document tables (schema rag) can be recreated independently.

CREATE SCHEMA rag;

-- The extension lives in schema rag, not public: recreating the numeric tables with
-- DROP SCHEMA public CASCADE must not drop the vector type (and with it the embedding
-- column). Queries that use vector operators need rag on the search_path, or
-- OPERATOR(rag.<=>).
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA rag;

COMMENT ON SCHEMA rag IS
    'Documents, chunks and embeddings for retrieval (RAG). Not exposed to the Text-to-SQL tool, which only sees the numeric tables in schema public.';

-- ---------------------------------------------------------------------------
-- rag.documents
-- ---------------------------------------------------------------------------
CREATE TABLE rag.documents (
    doc_id            TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    doc_type          TEXT NOT NULL,
    title             TEXT NOT NULL,
    context_label     TEXT NOT NULL,
    reference_period  TEXT NOT NULL
                      CHECK (reference_period ~ '^[0-9]{4}(-(0[1-9]|1[0-2])|-Q[1-4])?$'),
    period_start      DATE NOT NULL,
    period_end        DATE NOT NULL,
    published_date    DATE NOT NULL,
    url               TEXT NOT NULL,
    snapshot_date     DATE NOT NULL,
    CHECK (period_start <= period_end)
);

COMMENT ON TABLE rag.documents IS
    'One row per source document (NSO monthly report, SBV directive or press conference). Loaded from data/manual/documents.csv (verified rows only).';
COMMENT ON COLUMN rag.documents.doc_id IS
    'Document id from documents.csv, e.g. nso_report_2026_06, sbv_press_2026_q2.';
COMMENT ON COLUMN rag.documents.source IS
    'Publishing agency: ''NSO'' (General Statistics Office) or ''SBV'' (State Bank of Vietnam).';
COMMENT ON COLUMN rag.documents.doc_type IS
    'Document type, e.g. nso_monthly_report, sbv_directive, sbv_quarterly_press.';
COMMENT ON COLUMN rag.documents.title IS
    'Original Vietnamese title.';
COMMENT ON COLUMN rag.documents.context_label IS
    'Short Vietnamese label (agency, type, period) prepended to every chunk of this document.';
COMMENT ON COLUMN rag.documents.reference_period IS
    'Period the document covers: ''YYYY-MM'' (month), ''YYYY-Qn'' (quarter) or ''YYYY'' (year).';
COMMENT ON COLUMN rag.documents.period_start IS
    'First day of reference_period, derived at load time (month, quarter or year start).';
COMMENT ON COLUMN rag.documents.period_end IS
    'Last day of reference_period, derived at load time (month, quarter or year end).';
COMMENT ON COLUMN rag.documents.published_date IS
    'Date the agency published the document.';
COMMENT ON COLUMN rag.documents.url IS
    'Public URL of the document page, used for citations.';
COMMENT ON COLUMN rag.documents.snapshot_date IS
    'Date of the raw snapshot (data/raw/documents/<date>/) the text was extracted from.';

-- ---------------------------------------------------------------------------
-- rag.chunks
-- ---------------------------------------------------------------------------
CREATE TABLE rag.chunks (
    chunk_id      TEXT PRIMARY KEY,
    doc_id        TEXT NOT NULL REFERENCES rag.documents (doc_id) ON DELETE CASCADE,
    strategy      TEXT NOT NULL,
    seq           INTEGER NOT NULL CHECK (seq >= 1),
    heading_path  TEXT[] NOT NULL DEFAULT '{}',
    context       TEXT NOT NULL,
    text          TEXT NOT NULL,
    char_count    INTEGER NOT NULL CHECK (char_count > 0),
    UNIQUE (doc_id, strategy, seq)
);

COMMENT ON TABLE rag.chunks IS
    'One row per chunk of a document under one chunking strategy. Several strategies can coexist; filter on strategy.';
COMMENT ON COLUMN rag.chunks.chunk_id IS
    'Chunk id from chunks.jsonl, unique across strategies.';
COMMENT ON COLUMN rag.chunks.doc_id IS
    'Document the chunk belongs to; see rag.documents.';
COMMENT ON COLUMN rag.chunks.strategy IS
    'Chunking strategy name, e.g. ''heading_v1''.';
COMMENT ON COLUMN rag.chunks.seq IS
    'Position of the chunk within the document for this strategy, starting at 1.';
COMMENT ON COLUMN rag.chunks.heading_path IS
    'Headings from the top level down to the chunk''s section; empty if none.';
COMMENT ON COLUMN rag.chunks.context IS
    'context_label › heading path; prepended (plus a blank line) to text when embedding.';
COMMENT ON COLUMN rag.chunks.text IS
    'Chunk body in Markdown, as cut from the extracted document.';
COMMENT ON COLUMN rag.chunks.char_count IS
    'Number of characters in text.';

-- ---------------------------------------------------------------------------
-- rag.chunk_embeddings
-- ---------------------------------------------------------------------------
-- No vector index (HNSW / IVFFlat) on purpose: see the table comment.
CREATE TABLE rag.chunk_embeddings (
    chunk_id    TEXT NOT NULL REFERENCES rag.chunks (chunk_id) ON DELETE CASCADE,
    model_name  TEXT NOT NULL,
    embedding   rag.vector(1024) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, model_name)
);

COMMENT ON TABLE rag.chunk_embeddings IS
    'One embedding per chunk and embedding model, so vectors from several models can be compared. No vector index (HNSW/IVFFlat) on purpose: with only a few hundred chunks an exact full scan is fast and returns exact nearest neighbours; add an approximate index only when chunks reach tens of thousands.';
COMMENT ON COLUMN rag.chunk_embeddings.chunk_id IS
    'Embedded chunk; see rag.chunks.';
COMMENT ON COLUMN rag.chunk_embeddings.model_name IS
    'Embedding model id; filter on it so only vectors of one model are compared.';
COMMENT ON COLUMN rag.chunk_embeddings.embedding IS
    'Embedding of context + blank line + text, 1024 dimensions.';
COMMENT ON COLUMN rag.chunk_embeddings.created_at IS
    'Time the embedding was computed and stored.';
