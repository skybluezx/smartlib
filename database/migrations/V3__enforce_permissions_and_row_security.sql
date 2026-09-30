SET ROLE smartlib_owner;

CREATE FUNCTION smartlib.current_actor_id()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $function$
    SELECT nullif(current_setting('smartlib.actor_id', true), '')::uuid
$function$;

REVOKE ALL ON ALL TABLES IN SCHEMA smartlib, audit FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA smartlib FROM PUBLIC;

GRANT EXECUTE ON FUNCTION smartlib.current_actor_id() TO smartlib_app, smartlib_readonly;

GRANT SELECT, INSERT, UPDATE ON
    smartlib.source_system,
    smartlib.knowledge_object,
    smartlib.source_reference,
    smartlib.evidence_record,
    smartlib.relation_assertion,
    smartlib.relation_evidence,
    smartlib.policy_tag,
    smartlib.object_policy_tag,
    smartlib.async_job,
    smartlib.outbox_event
TO smartlib_app;

GRANT SELECT ON
    smartlib.source_system,
    smartlib.knowledge_object,
    smartlib.source_reference,
    smartlib.evidence_record,
    smartlib.relation_assertion,
    smartlib.relation_evidence,
    smartlib.policy_tag,
    smartlib.object_policy_tag,
    smartlib.async_job
TO smartlib_readonly;

GRANT INSERT ON audit.audit_event TO smartlib_app;
GRANT SELECT ON audit.audit_event TO smartlib_auditor;

ALTER TABLE smartlib.knowledge_object ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.source_reference ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.evidence_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.relation_assertion ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.relation_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.object_policy_tag ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.async_job ENABLE ROW LEVEL SECURITY;

CREATE POLICY knowledge_object_read ON smartlib.knowledge_object
    FOR SELECT TO smartlib_app, smartlib_readonly
    USING (visibility = 'public' OR created_by = smartlib.current_actor_id());

CREATE POLICY knowledge_object_write ON smartlib.knowledge_object
    FOR ALL TO smartlib_app
    USING (created_by = smartlib.current_actor_id())
    WITH CHECK (created_by = smartlib.current_actor_id());

CREATE POLICY source_reference_read ON smartlib.source_reference
    FOR SELECT TO smartlib_app, smartlib_readonly
    USING (EXISTS (
        SELECT 1 FROM smartlib.knowledge_object AS ko
        WHERE ko.object_id = source_reference.object_id
    ));

CREATE POLICY source_reference_write ON smartlib.source_reference
    FOR ALL TO smartlib_app
    USING (EXISTS (
        SELECT 1 FROM smartlib.knowledge_object AS ko
        WHERE ko.object_id = source_reference.object_id
          AND ko.created_by = smartlib.current_actor_id()
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM smartlib.knowledge_object AS ko
        WHERE ko.object_id = source_reference.object_id
          AND ko.created_by = smartlib.current_actor_id()
    ));

CREATE POLICY evidence_record_read ON smartlib.evidence_record
    FOR SELECT TO smartlib_app, smartlib_readonly
    USING (visibility = 'public' OR created_by = smartlib.current_actor_id());

CREATE POLICY evidence_record_write ON smartlib.evidence_record
    FOR ALL TO smartlib_app
    USING (created_by = smartlib.current_actor_id())
    WITH CHECK (created_by = smartlib.current_actor_id());

CREATE POLICY relation_assertion_read ON smartlib.relation_assertion
    FOR SELECT TO smartlib_app, smartlib_readonly
    USING (visibility = 'public' OR created_by = smartlib.current_actor_id());

CREATE POLICY relation_assertion_write ON smartlib.relation_assertion
    FOR ALL TO smartlib_app
    USING (created_by = smartlib.current_actor_id())
    WITH CHECK (created_by = smartlib.current_actor_id());

CREATE POLICY relation_evidence_read ON smartlib.relation_evidence
    FOR SELECT TO smartlib_app, smartlib_readonly
    USING (EXISTS (
        SELECT 1 FROM smartlib.relation_assertion AS relation
        WHERE relation.relation_id = relation_evidence.relation_id
    ));

CREATE POLICY relation_evidence_write ON smartlib.relation_evidence
    FOR ALL TO smartlib_app
    USING (EXISTS (
        SELECT 1 FROM smartlib.relation_assertion AS relation
        WHERE relation.relation_id = relation_evidence.relation_id
          AND relation.created_by = smartlib.current_actor_id()
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM smartlib.relation_assertion AS relation
        WHERE relation.relation_id = relation_evidence.relation_id
          AND relation.created_by = smartlib.current_actor_id()
    ));

CREATE POLICY object_policy_tag_read ON smartlib.object_policy_tag
    FOR SELECT TO smartlib_app, smartlib_readonly
    USING (EXISTS (
        SELECT 1 FROM smartlib.knowledge_object AS ko
        WHERE ko.object_id = object_policy_tag.object_id
    ));

CREATE POLICY object_policy_tag_write ON smartlib.object_policy_tag
    FOR ALL TO smartlib_app
    USING (assigned_by = smartlib.current_actor_id())
    WITH CHECK (
        assigned_by = smartlib.current_actor_id()
        AND EXISTS (
            SELECT 1 FROM smartlib.knowledge_object AS ko
            WHERE ko.object_id = object_policy_tag.object_id
              AND ko.created_by = smartlib.current_actor_id()
        )
    );

CREATE POLICY async_job_read ON smartlib.async_job
    FOR SELECT TO smartlib_app, smartlib_readonly
    USING (requested_by = smartlib.current_actor_id());

CREATE POLICY async_job_write ON smartlib.async_job
    FOR ALL TO smartlib_app
    USING (requested_by = smartlib.current_actor_id())
    WITH CHECK (requested_by = smartlib.current_actor_id());

RESET ROLE;
