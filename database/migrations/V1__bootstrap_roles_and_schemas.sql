DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartlib_owner') THEN
        CREATE ROLE smartlib_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartlib_app') THEN
        CREATE ROLE smartlib_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartlib_readonly') THEN
        CREATE ROLE smartlib_readonly NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartlib_auditor') THEN
        CREATE ROLE smartlib_auditor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$roles$;

DO $membership$
BEGIN
    EXECUTE format('GRANT smartlib_owner TO %I WITH ADMIN OPTION', current_user);
END
$membership$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

DO $database_acl$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format(
        'GRANT CONNECT ON DATABASE %I TO smartlib_owner, smartlib_app, smartlib_readonly, smartlib_auditor',
        current_database()
    );
END
$database_acl$;

CREATE SCHEMA smartlib AUTHORIZATION smartlib_owner;
CREATE SCHEMA audit AUTHORIZATION smartlib_owner;

REVOKE ALL ON SCHEMA smartlib, audit FROM PUBLIC;
GRANT USAGE ON SCHEMA smartlib TO smartlib_app, smartlib_readonly;
GRANT USAGE ON SCHEMA audit TO smartlib_app, smartlib_auditor;

COMMENT ON SCHEMA smartlib IS 'SmartLib canonical platform state';
COMMENT ON SCHEMA audit IS 'Append-only SmartLib audit events';
