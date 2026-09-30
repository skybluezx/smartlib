SET ROLE smartlib_owner;
SET search_path = smartlib, audit, pg_catalog;

ALTER TABLE smartlib.publication_authorship
    ADD COLUMN is_co_corresponding_author boolean NOT NULL DEFAULT false,
    ADD COLUMN role_source text NOT NULL DEFAULT 'bibliographic_order'
        CHECK (role_source IN ('bibliographic_order', 'fulltext', 'metadata', 'manual_review')),
    ADD COLUMN role_evidence jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(role_evidence) = 'object'),
    ADD COLUMN affiliation_source text
        CHECK (affiliation_source IS NULL OR affiliation_source IN
               ('fulltext', 'metadata', 'manual_review')),
    ADD COLUMN affiliation_evidence jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(affiliation_evidence) = 'object');

ALTER TABLE smartlib.relation_assertion
    ADD COLUMN attributes jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(attributes) = 'object');

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
    WHERE relation.relation_id = p_relation_id
      AND relation.object_id IS NOT NULL
      AND relation.review_state IN ('pending', 'approved')
      AND relation.system_to = 'infinity'::timestamptz
$function$;

COMMENT ON COLUMN smartlib.publication_authorship.role_evidence IS
    'Versioned evidence showing whether each author role came from order, explicit fulltext text, metadata or review.';
COMMENT ON COLUMN smartlib.publication_authorship.affiliation_evidence IS
    'Raw affiliation strings, marker mapping and extraction confidence retained for later identity review.';
COMMENT ON COLUMN smartlib.relation_assertion.attributes IS
    'Predicate-specific structured properties such as author order, authorship roles and affiliation evidence.';

RESET ROLE;
