SET ROLE smartlib_owner;
SET search_path = smartlib, smartlib_projection, pg_catalog;

-- InCites is the first-version authority for publication funding analysis.
-- Full-text extraction remains governed source evidence, but candidate objects
-- and relations must stay pending and outside the graph projection.
UPDATE smartlib.knowledge_object
   SET quality_state = 'warning',
       review_state = 'pending',
       attributes = attributes || jsonb_build_object(
           'analysis_enabled', false,
           'governance_state', 'pending_fulltext_verification'
       ),
       version = smartlib.knowledge_object.version + 1,
       updated_at = clock_timestamp()
 WHERE attributes ->> 'record_kind' IN
       ('funding_program_candidate', 'individual_grant_candidate')
   AND (review_state <> 'pending'
        OR quality_state <> 'warning'
        OR attributes ->> 'analysis_enabled' IS DISTINCT FROM 'false');

UPDATE smartlib.relation_assertion AS relation
   SET review_state = 'pending',
       attributes = relation.attributes || jsonb_build_object(
           'source_authority', 'publication_fulltext',
           'analysis_enabled', false,
           'governance_state', 'pending_fulltext_verification'
       ),
       version = relation.version + 1,
       updated_at = clock_timestamp()
  FROM smartlib.knowledge_object AS target
 WHERE target.object_id = relation.object_id
   AND target.attributes ->> 'record_kind' IN
       ('funding_program_candidate', 'individual_grant_candidate')
   AND (relation.review_state <> 'pending'
        OR relation.attributes ->> 'analysis_enabled' IS DISTINCT FROM 'false');

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
        'attributes', relation.attributes,
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
    JOIN smartlib.knowledge_object AS target ON target.object_id = relation.object_id
    WHERE relation.relation_id = p_relation_id
      AND relation.object_id IS NOT NULL
      AND relation.review_state IN ('pending', 'approved')
      AND relation.system_to = 'infinity'::timestamptz
      AND coalesce(target.attributes ->> 'record_kind', '') NOT IN
          ('funding_program_candidate', 'individual_grant_candidate')
$function$;

-- Re-emit every full-text candidate relation. Under the projection contract
-- above each event becomes a delete delivery, removing any historic edge from
-- HugeGraph while leaving the canonical record in PostgreSQL.
INSERT INTO smartlib.outbox_event
    (event_id, aggregate_type, aggregate_id, event_type, event_version, payload, trace_id)
SELECT md5('funding-authority-v1:' || relation.relation_id::text)::uuid,
       'relation_assertion', relation.relation_id,
       'knowledge.relation.updated', relation.version,
       jsonb_build_object('relation_id', relation.relation_id, 'version', relation.version),
       'funding-authority-v1'
  FROM smartlib.relation_assertion AS relation
  JOIN smartlib.knowledge_object AS target ON target.object_id = relation.object_id
 WHERE target.attributes ->> 'record_kind' IN
       ('funding_program_candidate', 'individual_grant_candidate')
ON CONFLICT (event_id) DO NOTHING;

COMMENT ON FUNCTION smartlib_projection.graph_relation_json(uuid) IS
    'Builds a HugeGraph relation document while excluding pending full-text funding candidates';

RESET ROLE;
