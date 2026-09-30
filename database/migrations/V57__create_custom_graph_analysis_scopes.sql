SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

CREATE TABLE smartlib.custom_graph_analysis_scope (
    scope_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
    description text CHECK (description IS NULL OR length(description) <= 300),
    query_language text NOT NULL DEFAULT 'cypher' CHECK (query_language = 'cypher'),
    graph_query text NOT NULL CHECK (length(graph_query) BETWEEN 1 AND 4000),
    last_result_count integer CHECK (last_result_count IS NULL OR last_result_count >= 0),
    last_executed_at timestamptz,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE UNIQUE INDEX custom_graph_analysis_scope_owner_name
    ON smartlib.custom_graph_analysis_scope (created_by, lower(name));

CREATE TRIGGER custom_graph_analysis_scope_updated_at
BEFORE UPDATE ON smartlib.custom_graph_analysis_scope
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

ALTER TABLE smartlib.custom_graph_analysis_scope ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.custom_graph_analysis_scope FORCE ROW LEVEL SECURITY;

CREATE POLICY custom_graph_analysis_scope_read
ON smartlib.custom_graph_analysis_scope FOR SELECT TO smartlib_app, smartlib_readonly
USING (created_by = smartlib.current_actor_id());

CREATE POLICY custom_graph_analysis_scope_write
ON smartlib.custom_graph_analysis_scope FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (created_by = smartlib.current_actor_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON smartlib.custom_graph_analysis_scope TO smartlib_app;
GRANT SELECT ON smartlib.custom_graph_analysis_scope TO smartlib_readonly;

COMMENT ON TABLE smartlib.custom_graph_analysis_scope IS
    'Actor-owned reusable read-only HugeGraph Cypher scopes; results are rechecked against the shared PostgreSQL analysis admission policy.';

RESET ROLE;
