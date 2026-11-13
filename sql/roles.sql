-- Read-only role for the Text-to-SQL agent (docs/SCHEMA.md, "Read-only role for
-- Text-to-SQL"). Safe to run many times. Contains no password: the password is set by
-- `python -m vnmacro.roles apply`, which runs this file as the database owner.
--
-- The role may only read the tables in schema public. It has no access to schema rag,
-- cannot write, cannot create objects, and cannot create temporary tables.

-- Role (LOGIN, no other attributes)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vnmacro_reader') THEN
        CREATE ROLE vnmacro_reader LOGIN;
    END IF;
END
$$;
ALTER ROLE vnmacro_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    NOREPLICATION NOBYPASSRLS;

-- Per-role settings (applied at every new session of the role)
ALTER ROLE vnmacro_reader SET default_transaction_read_only = on;
ALTER ROLE vnmacro_reader SET statement_timeout = '5s';
ALTER ROLE vnmacro_reader SET search_path = public;

-- Database: connect only. PostgreSQL grants TEMP (temporary tables) to PUBLIC by
-- default, so it is revoked from PUBLIC; the owner keeps it as owner/superuser.
DO $$
BEGIN
    EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM vnmacro_reader', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO vnmacro_reader', current_database());
END
$$;

-- Schema public: read every table, create nothing.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM vnmacro_reader;
GRANT USAGE ON SCHEMA public TO vnmacro_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM vnmacro_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO vnmacro_reader;
-- Tables created later in public by the role running this file (the owner) are
-- readable too. These defaults belong to the schema: rerun this file after
-- DROP SCHEMA public CASCADE.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO vnmacro_reader;

-- Schema rag: no access at all (skipped when the schema does not exist yet).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'rag') THEN
        REVOKE ALL ON SCHEMA rag FROM vnmacro_reader;
        REVOKE ALL ON ALL TABLES IN SCHEMA rag FROM vnmacro_reader;
    END IF;
END
$$;
