SET ROLE smartlib_owner;
-- SQL analyses use the same relation + endpoint admission as graph_relation_json.
CREATE VIEW smartlib.analysis_relation WITH (security_invoker=true) AS
SELECT r.* FROM smartlib.relation_assertion r
JOIN smartlib.knowledge_object s ON s.object_id=r.subject_id
JOIN smartlib.knowledge_object t ON t.object_id=r.object_id
WHERE r.system_to='infinity' AND s.system_to='infinity' AND t.system_to='infinity'
  AND smartlib.analysis_state_eligible(r.review_state)
  AND smartlib.analysis_state_eligible(s.review_state)
  AND smartlib.analysis_state_eligible(t.review_state);
GRANT SELECT ON smartlib.analysis_relation TO smartlib_app,smartlib_readonly;
CREATE TABLE smartlib.saved_analysis (
    analysis_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 80),
    kind text NOT NULL CHECK (kind IN ('template','snapshot')),
    definition jsonb NOT NULL,
    result jsonb,
    result_hash text,
    publication_count integer,
    object_ids uuid[] NOT NULL DEFAULT '{}',
    metric_release_ids uuid[] NOT NULL DEFAULT '{}',
    provenance jsonb NOT NULL DEFAULT '{}',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((kind='template' AND result IS NULL) OR
           (kind='snapshot' AND result IS NOT NULL AND result_hash IS NOT NULL))
);
ALTER TABLE smartlib.saved_analysis ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.saved_analysis FORCE ROW LEVEL SECURITY;
CREATE POLICY saved_analysis_read ON smartlib.saved_analysis
FOR SELECT TO smartlib_app,smartlib_readonly USING (
    created_by=smartlib.current_actor_id()
    AND NOT EXISTS (SELECT 1 FROM unnest(object_ids) AS required(id)
        WHERE NOT EXISTS (SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=required.id))
    AND NOT EXISTS (SELECT 1 FROM unnest(metric_release_ids) AS required(id)
        WHERE NOT EXISTS (SELECT 1 FROM smartlib.publication_metric_release r
                          WHERE r.release_id=required.id))
);
CREATE POLICY saved_analysis_insert ON smartlib.saved_analysis
FOR INSERT TO smartlib_app WITH CHECK(created_by=smartlib.current_actor_id());
-- No UPDATE/DELETE grants: historical results and their provenance are immutable.
GRANT SELECT,INSERT ON smartlib.saved_analysis TO smartlib_app;
GRANT SELECT ON smartlib.saved_analysis TO smartlib_readonly;
CREATE INDEX saved_analysis_owner_date ON smartlib.saved_analysis(created_by,created_at DESC);
RESET ROLE;
