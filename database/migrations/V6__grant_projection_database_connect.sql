DO $database_acl$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO smartlib_projection', current_database());
END
$database_acl$;

COMMENT ON ROLE smartlib_projection IS
    'Least-privilege runtime role for Outbox-driven serving projections; direct canonical and projection table writes remain denied';
