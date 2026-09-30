SET ROLE smartlib_owner;
SET search_path = smartlib, smartlib_projection, pg_catalog;

-- One policy function is shared by PostgreSQL analytics, the PostgreSQL graph
-- baseline and the HugeGraph projection contract.  The first version includes
-- both pending and approved records.  Tightening the policy later therefore
-- requires changing one function and replaying the projection, rather than
-- editing every analytical query independently.
CREATE OR REPLACE FUNCTION smartlib.analysis_state_eligible(p_review_state text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $function$
    SELECT COALESCE(p_review_state IN ('pending', 'approved'), false)
$function$;

COMMENT ON FUNCTION smartlib.analysis_state_eligible(text) IS
    'Shared v1 analysis and graph admission policy: pending and approved participate; rejected and superseded do not';

GRANT EXECUTE ON FUNCTION smartlib.analysis_state_eligible(text)
    TO smartlib_app, smartlib_readonly, smartlib_projection;

CREATE OR REPLACE FUNCTION smartlib_projection.graph_node_json(p_object_id uuid)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
    SELECT jsonb_build_object(
        'object_id', object_id,
        'object_type', object_type,
        'canonical_name', canonical_name,
        'description', description,
        'visibility', visibility,
        'created_by', created_by,
        'object_version', version,
        'projection_version', 'graph-projection-v4-analysis-policy'
    )
      FROM smartlib.knowledge_object
     WHERE object_id = p_object_id
       AND smartlib.analysis_state_eligible(review_state)
       AND system_to = 'infinity'::timestamptz
$function$;

CREATE OR REPLACE FUNCTION smartlib_projection.graph_relation_json(p_relation_id uuid)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
    SELECT jsonb_build_object(
        'relation_id', relation.relation_id,
        'subject_id', relation.subject_id,
        'object_id', relation.object_id,
        'context_object_id', relation.context_object_id,
        'predicate', relation.predicate,
        'fact_class', relation.fact_class,
        'confidence', relation.confidence,
        'review_state', relation.review_state,
        'visibility', relation.visibility,
        'created_by', relation.created_by,
        'relation_version', relation.version,
        'projection_version', 'graph-projection-v4-analysis-policy',
        'attributes', relation.attributes,
        'evidence_ids_all', COALESCE((
            SELECT jsonb_agg(evidence.evidence_id ORDER BY evidence.evidence_id)
              FROM smartlib.relation_evidence link
              JOIN smartlib.evidence_record evidence
                ON evidence.evidence_id = link.evidence_id
             WHERE link.relation_id = relation.relation_id
        ), '[]'::jsonb),
        'evidence_visibilities', COALESCE((
            SELECT jsonb_agg(evidence.visibility ORDER BY evidence.evidence_id)
              FROM smartlib.relation_evidence link
              JOIN smartlib.evidence_record evidence
                ON evidence.evidence_id = link.evidence_id
             WHERE link.relation_id = relation.relation_id
        ), '[]'::jsonb),
        'evidence_created_by', COALESCE((
            SELECT jsonb_agg(evidence.created_by ORDER BY evidence.evidence_id)
              FROM smartlib.relation_evidence link
              JOIN smartlib.evidence_record evidence
                ON evidence.evidence_id = link.evidence_id
             WHERE link.relation_id = relation.relation_id
        ), '[]'::jsonb)
    )
      FROM smartlib.relation_assertion relation
      JOIN smartlib.knowledge_object subject
        ON subject.object_id = relation.subject_id
       AND subject.system_to = 'infinity'::timestamptz
       AND smartlib.analysis_state_eligible(subject.review_state)
      JOIN smartlib.knowledge_object target
        ON target.object_id = relation.object_id
       AND target.system_to = 'infinity'::timestamptz
       AND smartlib.analysis_state_eligible(target.review_state)
     WHERE relation.relation_id = p_relation_id
       AND relation.object_id IS NOT NULL
       AND smartlib.analysis_state_eligible(relation.review_state)
       AND relation.system_to = 'infinity'::timestamptz
$function$;

-- Re-evaluate every current record against the shared policy.  This is also the
-- replay pattern required by a future policy change.
INSERT INTO smartlib.outbox_event
    (event_id, aggregate_type, aggregate_id, event_type, event_version, payload, trace_id)
SELECT md5('analysis-eligibility-v1:object:' || object_id::text)::uuid,
       'knowledge_object', object_id, 'knowledge.object.analysis-eligibility.changed',
       version, jsonb_build_object('object_id', object_id, 'version', version),
       'analysis-eligibility-v1'
  FROM smartlib.knowledge_object
 WHERE system_to = 'infinity'::timestamptz
ON CONFLICT (event_id) DO NOTHING;

INSERT INTO smartlib.outbox_event
    (event_id, aggregate_type, aggregate_id, event_type, event_version, payload, trace_id)
SELECT md5('analysis-eligibility-v1:relation:' || relation_id::text)::uuid,
       'relation_assertion', relation_id, 'knowledge.relation.analysis-eligibility.changed',
       version, jsonb_build_object('relation_id', relation_id, 'version', version),
       'analysis-eligibility-v1'
  FROM smartlib.relation_assertion
 WHERE system_to = 'infinity'::timestamptz
ON CONFLICT (event_id) DO NOTHING;

COMMENT ON FUNCTION smartlib_projection.graph_node_json(uuid) IS
    'Builds HugeGraph nodes using the shared SmartLib analysis-state policy';
COMMENT ON FUNCTION smartlib_projection.graph_relation_json(uuid) IS
    'Builds HugeGraph edges only when the relation and both endpoints satisfy the shared analysis-state policy';

RESET ROLE;
