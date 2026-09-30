SET ROLE smartlib_owner;
CREATE TABLE smartlib.research_planning_record (
 record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 kind text NOT NULL CHECK(kind IN ('application','action','review')),
 payload jsonb NOT NULL,
 created_by uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 object_ids uuid[] NOT NULL DEFAULT '{}',
 snapshot_id uuid REFERENCES smartlib.saved_analysis(analysis_id),
 parent_id uuid REFERENCES smartlib.research_planning_record(record_id),
 supersedes_id uuid UNIQUE REFERENCES smartlib.research_planning_record(record_id)
);
CREATE UNIQUE INDEX research_application_reference ON smartlib.research_planning_record
(created_by,(payload->>'reference')) WHERE kind='application' AND supersedes_id IS NULL;
ALTER TABLE smartlib.research_planning_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.research_planning_record FORCE ROW LEVEL SECURITY;
CREATE POLICY planning_read ON smartlib.research_planning_record FOR SELECT
TO smartlib_app,smartlib_readonly USING (
 created_by=smartlib.current_actor_id()
 AND NOT EXISTS (SELECT 1 FROM unnest(object_ids) x(id)
   WHERE NOT EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=x.id))
 AND (snapshot_id IS NULL OR EXISTS(SELECT 1 FROM smartlib.saved_analysis s WHERE s.analysis_id=snapshot_id))
);
CREATE POLICY planning_insert ON smartlib.research_planning_record FOR INSERT
TO smartlib_app WITH CHECK(created_by=smartlib.current_actor_id());
GRANT SELECT,INSERT ON smartlib.research_planning_record TO smartlib_app;
GRANT SELECT ON smartlib.research_planning_record TO smartlib_readonly;
RESET ROLE;
