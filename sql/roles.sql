-- Database roles for the agent (docs/SCHEMA.md, "Read-only role for Text-to-SQL" and
-- "App schema and logger role"). Safe to run many times. Contains no passwords: they
-- are set by `python -m vnmacro.roles apply`, which runs this file as the owner.
--
-- vnmacro_reader may only read the tables in schemas public and rag (rag holds public
-- documents; the SQL check in guard.py still limits generated SQL to public). It has
-- no access to schema app, cannot write, cannot create objects or temporary tables.
--
-- vnmacro_logger may only INSERT into app.query_log and app.feedback. It cannot read
-- them (other users' questions and comments), has no access to schemas public and rag,
-- and cannot create objects or temporary tables. Run sql/app_schema.sql before this file; the app
-- grants are skipped while schema app does not exist.

-- Role (LOGIN, no other attributes)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vnmacro_reader') THEN
        CREATE ROLE vnmacro_reader LOGIN;
    END IF;
END
$$;
ALTER ROLE vnmacro_reader LOGIN NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION
    NOBYPASSRLS;
-- Only a superuser may name the SUPERUSER attribute (PostgreSQL 16+), even to turn it
-- off; managed services such as Neon run this file as a non-superuser owner, and a
-- role created by a non-superuser can never be a superuser anyway.
DO $$
BEGIN
    IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        ALTER ROLE vnmacro_reader NOSUPERUSER;
    END IF;
END
$$;

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

-- Schema rag: read every table, create nothing (skipped when the schema does not
-- exist yet). Default privileges as for public.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'rag') THEN
        REVOKE ALL ON SCHEMA rag FROM vnmacro_reader;
        GRANT USAGE ON SCHEMA rag TO vnmacro_reader;
        REVOKE ALL ON ALL TABLES IN SCHEMA rag FROM vnmacro_reader;
        GRANT SELECT ON ALL TABLES IN SCHEMA rag TO vnmacro_reader;
        ALTER DEFAULT PRIVILEGES IN SCHEMA rag GRANT SELECT ON TABLES TO vnmacro_reader;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- vnmacro_logger: INSERT into app.query_log, nothing else
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vnmacro_logger') THEN
        CREATE ROLE vnmacro_logger LOGIN;
    END IF;
END
$$;
ALTER ROLE vnmacro_logger LOGIN NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION
    NOBYPASSRLS;
-- Only a superuser may name the SUPERUSER attribute (PostgreSQL 16+), even to turn it
-- off; managed services such as Neon run this file as a non-superuser owner, and a
-- role created by a non-superuser can never be a superuser anyway.
DO $$
BEGIN
    IF (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        ALTER ROLE vnmacro_logger NOSUPERUSER;
    END IF;
END
$$;
ALTER ROLE vnmacro_logger SET statement_timeout = '5s';
ALTER ROLE vnmacro_logger SET search_path = app;

-- Database: connect only (TEMP is already revoked from PUBLIC above).
DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM vnmacro_logger', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO vnmacro_logger', current_database());
END
$$;

-- Schema public: no access.
REVOKE ALL ON SCHEMA public FROM vnmacro_logger;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM vnmacro_logger;

-- Schemas rag and app (skipped when a schema does not exist yet).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'rag') THEN
        REVOKE ALL ON SCHEMA rag FROM vnmacro_logger;
        REVOKE ALL ON ALL TABLES IN SCHEMA rag FROM vnmacro_logger;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'app') THEN
        -- Nobody but the owner and the grants below.
        REVOKE ALL ON SCHEMA app FROM PUBLIC, vnmacro_reader, vnmacro_logger;
        REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC, vnmacro_reader, vnmacro_logger;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA app
            FROM PUBLIC, vnmacro_reader, vnmacro_logger;
        -- Logger: insert rows (no SELECT, so no INSERT ... RETURNING) and draw ids.
        GRANT USAGE ON SCHEMA app TO vnmacro_logger;
        GRANT INSERT ON app.query_log TO vnmacro_logger;
        EXECUTE format('GRANT USAGE ON SEQUENCE %s TO vnmacro_logger',
                       pg_get_serial_sequence('app.query_log', 'id'));
        GRANT INSERT ON app.feedback TO vnmacro_logger;
        EXECUTE format('GRANT USAGE ON SEQUENCE %s TO vnmacro_logger',
                       pg_get_serial_sequence('app.feedback', 'id'));
    ELSE
        RAISE NOTICE 'schema app does not exist: run sql/app_schema.sql, then apply again';
    END IF;
END
$$;
