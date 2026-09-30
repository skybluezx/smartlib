SET ROLE smartlib_owner;

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
        'predicate', relation.predicate,
        'fact_class', relation.fact_class,
        'confidence', relation.confidence,
        'review_state', relation.review_state,
        'visibility', relation.visibility,
        'created_by', relation.created_by,
        'relation_version', relation.version,
        'projection_version', 'graph-projection-v1',
        'evidence_ids_all', COALESCE((
            SELECT jsonb_agg(evidence.evidence_id ORDER BY evidence.evidence_id)
            FROM smartlib.relation_evidence AS link
            JOIN smartlib.evidence_record AS evidence ON evidence.evidence_id = link.evidence_id
            WHERE link.relation_id = relation.relation_id
        ), '[]'::jsonb),
        'evidence_visibilities', COALESCE((
            SELECT jsonb_agg(evidence.visibility ORDER BY evidence.evidence_id)
            FROM smartlib.relation_evidence AS link
            JOIN smartlib.evidence_record AS evidence ON evidence.evidence_id = link.evidence_id
            WHERE link.relation_id = relation.relation_id
        ), '[]'::jsonb),
        'evidence_created_by', COALESCE((
            SELECT jsonb_agg(evidence.created_by ORDER BY evidence.evidence_id)
            FROM smartlib.relation_evidence AS link
            JOIN smartlib.evidence_record AS evidence ON evidence.evidence_id = link.evidence_id
            WHERE link.relation_id = relation.relation_id
        ), '[]'::jsonb)
    )
    FROM smartlib.relation_assertion AS relation
    WHERE relation.relation_id = p_relation_id
      AND relation.object_id IS NOT NULL
      AND relation.review_state IN ('pending', 'approved')
      AND relation.system_to = 'infinity'::timestamptz
$function$;

COMMENT ON FUNCTION smartlib_projection.graph_relation_json(uuid) IS
    'Build a Neo4j-safe relation projection with aligned scalar evidence access arrays';

RESET ROLE;
