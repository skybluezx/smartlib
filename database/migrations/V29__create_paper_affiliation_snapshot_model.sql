SET ROLE smartlib_owner;
SET search_path = smartlib, audit, pg_catalog;

ALTER TABLE smartlib.evidence_record
    ADD COLUMN evidence_kind text NOT NULL DEFAULT 'general'
        CHECK (evidence_kind ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    ADD COLUMN fulltext_resource_id uuid
        REFERENCES smartlib.publication_fulltext_resource(fulltext_resource_id),
    ADD COLUMN page_number integer CHECK (page_number IS NULL OR page_number >= 1),
    ADD COLUMN evidence_locator jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(evidence_locator) = 'object'),
    ADD COLUMN verification_state text NOT NULL DEFAULT 'extracted'
        CHECK (verification_state IN
               ('extracted', 'needs_review', 'confirmed', 'rejected', 'superseded'));

ALTER TABLE smartlib.relation_assertion
    ADD COLUMN context_object_id uuid REFERENCES smartlib.knowledge_object(object_id),
    ADD COLUMN source_publication_authorship_id uuid
        REFERENCES smartlib.publication_authorship(publication_authorship_id);

CREATE INDEX evidence_record_kind_state_idx
    ON smartlib.evidence_record (evidence_kind, verification_state, created_at DESC);
CREATE INDEX evidence_record_fulltext_idx
    ON smartlib.evidence_record (fulltext_resource_id)
    WHERE fulltext_resource_id IS NOT NULL;
CREATE INDEX relation_assertion_context_idx
    ON smartlib.relation_assertion (context_object_id, predicate)
    WHERE context_object_id IS NOT NULL;
CREATE INDEX relation_assertion_authorship_idx
    ON smartlib.relation_assertion (source_publication_authorship_id)
    WHERE source_publication_authorship_id IS NOT NULL;
CREATE UNIQUE INDEX person_affiliation_publication_snapshot_idx
    ON smartlib.relation_assertion
       (subject_id, object_id, context_object_id, source_publication_authorship_id)
    WHERE predicate = 'person.affiliated_with'
      AND object_id IS NOT NULL
      AND review_state IN ('pending', 'approved')
      AND system_to = 'infinity'::timestamptz;

CREATE FUNCTION smartlib.validate_author_affiliation_evidence()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
BEGIN
    IF NEW.evidence_kind <> 'author_affiliation' THEN
        RETURN NEW;
    END IF;
    IF NEW.object_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM smartlib.knowledge_object publication
         WHERE publication.object_id = NEW.object_id
           AND publication.object_type = 'publication'
           AND publication.system_to = 'infinity'::timestamptz
    ) THEN
        RAISE EXCEPTION 'author affiliation evidence must reference an active publication'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.fulltext_resource_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM smartlib.publication_fulltext_resource fulltext
         WHERE fulltext.fulltext_resource_id = NEW.fulltext_resource_id
           AND fulltext.publication_id = NEW.object_id
    ) THEN
        RAISE EXCEPTION 'author affiliation evidence must reference full text of the same publication'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.excerpt IS NULL OR btrim(NEW.excerpt) = '' THEN
        RAISE EXCEPTION 'author affiliation evidence must retain the raw PDF excerpt'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.verification_state = 'confirmed' AND NEW.page_number IS NULL THEN
        RAISE EXCEPTION 'confirmed author affiliation evidence requires a PDF page number'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER evidence_record_author_affiliation_guard
BEFORE INSERT OR UPDATE ON smartlib.evidence_record
FOR EACH ROW EXECUTE FUNCTION smartlib.validate_author_affiliation_evidence();

CREATE FUNCTION smartlib.validate_person_affiliation_snapshot(p_relation_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
DECLARE
    selected_relation smartlib.relation_assertion%ROWTYPE;
BEGIN
    SELECT * INTO selected_relation
      FROM smartlib.relation_assertion
     WHERE relation_id = p_relation_id;
    IF NOT FOUND OR selected_relation.predicate <> 'person.affiliated_with'
       OR selected_relation.review_state <> 'approved'
       OR selected_relation.system_to <> 'infinity'::timestamptz THEN
        RETURN;
    END IF;
    IF selected_relation.object_id IS NULL
       OR selected_relation.context_object_id IS NULL
       OR selected_relation.source_publication_authorship_id IS NULL THEN
        RAISE EXCEPTION 'approved person affiliation requires organization, publication context and authorship'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM smartlib.knowledge_object person,
               smartlib.knowledge_object organization,
               smartlib.knowledge_object publication
         WHERE person.object_id = selected_relation.subject_id
           AND person.object_type = 'person'
           AND person.system_to = 'infinity'::timestamptz
           AND organization.object_id = selected_relation.object_id
           AND organization.object_type = 'organization'
           AND organization.system_to = 'infinity'::timestamptz
           AND publication.object_id = selected_relation.context_object_id
           AND publication.object_type = 'publication'
           AND publication.system_to = 'infinity'::timestamptz
    ) THEN
        RAISE EXCEPTION 'approved person affiliation endpoints must be active person, organization and publication objects'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM smartlib.publication_authorship authorship
         WHERE authorship.publication_authorship_id =
               selected_relation.source_publication_authorship_id
           AND authorship.publication_id = selected_relation.context_object_id
           AND authorship.person_object_id = selected_relation.subject_id
           AND authorship.verification_status <> 'rejected'
    ) THEN
        RAISE EXCEPTION 'affiliation snapshot authorship must match its person and publication'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM smartlib.relation_evidence link
          JOIN smartlib.evidence_record evidence
            ON evidence.evidence_id = link.evidence_id
          JOIN smartlib.publication_fulltext_resource fulltext
            ON fulltext.fulltext_resource_id = evidence.fulltext_resource_id
         WHERE link.relation_id = selected_relation.relation_id
           AND evidence.evidence_kind = 'author_affiliation'
           AND evidence.verification_state = 'confirmed'
           AND evidence.object_id = selected_relation.context_object_id
           AND fulltext.publication_id = selected_relation.context_object_id
    ) THEN
        RAISE EXCEPTION 'approved affiliation snapshot requires confirmed PDF affiliation evidence'
            USING ERRCODE = '23514';
    END IF;
END
$function$;

CREATE FUNCTION smartlib.enforce_person_affiliation_snapshot()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
BEGIN
    PERFORM smartlib.validate_person_affiliation_snapshot(NEW.relation_id);
    RETURN NEW;
END
$function$;

CREATE CONSTRAINT TRIGGER relation_assertion_affiliation_snapshot_guard
AFTER INSERT OR UPDATE ON smartlib.relation_assertion
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION smartlib.enforce_person_affiliation_snapshot();

CREATE FUNCTION smartlib.enforce_affiliation_evidence_link()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM smartlib.validate_person_affiliation_snapshot(OLD.relation_id);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        PERFORM smartlib.validate_person_affiliation_snapshot(NEW.relation_id);
    END IF;
    RETURN COALESCE(NEW, OLD);
END
$function$;

CREATE CONSTRAINT TRIGGER relation_evidence_affiliation_snapshot_guard
AFTER INSERT OR UPDATE OR DELETE ON smartlib.relation_evidence
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION smartlib.enforce_affiliation_evidence_link();

CREATE TABLE smartlib.review_task (
    review_task_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_type text NOT NULL CHECK (issue_type ~ '^[A-Z][A-Z0-9_]{2,127}$'),
    target_type text NOT NULL CHECK (target_type IN
        ('evidence', 'relation', 'knowledge_object', 'publication_authorship')),
    target_id uuid NOT NULL,
    publication_id uuid REFERENCES smartlib.knowledge_object(object_id),
    publication_authorship_id uuid
        REFERENCES smartlib.publication_authorship(publication_authorship_id),
    evidence_id uuid REFERENCES smartlib.evidence_record(evidence_id),
    relation_id uuid REFERENCES smartlib.relation_assertion(relation_id),
    object_id uuid REFERENCES smartlib.knowledge_object(object_id),
    candidate_object_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
    reason_code text NOT NULL CHECK (reason_code ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    description text,
    machine_suggestion jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(machine_suggestion) = 'object'),
    confidence numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    state text NOT NULL DEFAULT 'open'
        CHECK (state IN ('open', 'in_review', 'resolved', 'rejected', 'cancelled')),
    decision jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(decision) = 'object'),
    assigned_to uuid,
    reviewed_by uuid,
    reviewed_at timestamptz,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (target_type = 'evidence' AND evidence_id = target_id
             AND relation_id IS NULL AND object_id IS NULL)
        OR (target_type = 'relation' AND relation_id = target_id
             AND evidence_id IS NULL AND object_id IS NULL)
        OR (target_type = 'knowledge_object' AND object_id = target_id
             AND evidence_id IS NULL AND relation_id IS NULL)
        OR (target_type = 'publication_authorship'
             AND publication_authorship_id = target_id
             AND evidence_id IS NULL AND relation_id IS NULL AND object_id IS NULL)
    ),
    CHECK (
        (state IN ('resolved', 'rejected') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
        OR state NOT IN ('resolved', 'rejected')
    )
);

CREATE UNIQUE INDEX review_task_open_target_idx
    ON smartlib.review_task (issue_type, target_type, target_id)
    WHERE state IN ('open', 'in_review');
CREATE INDEX review_task_queue_idx
    ON smartlib.review_task (state, issue_type, created_at);
CREATE INDEX review_task_publication_idx
    ON smartlib.review_task (publication_id, state)
    WHERE publication_id IS NOT NULL;

CREATE TRIGGER review_task_updated_at
BEFORE UPDATE ON smartlib.review_task
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

GRANT SELECT, INSERT, UPDATE ON smartlib.review_task TO smartlib_app;
GRANT SELECT ON smartlib.review_task TO smartlib_readonly;
ALTER TABLE smartlib.review_task ENABLE ROW LEVEL SECURITY;
CREATE POLICY review_task_read ON smartlib.review_task
FOR SELECT TO smartlib_app, smartlib_readonly
USING (
    created_by = smartlib.current_actor_id()
    OR assigned_to = smartlib.current_actor_id()
    OR reviewed_by = smartlib.current_actor_id()
);
CREATE POLICY review_task_write ON smartlib.review_task
FOR ALL TO smartlib_app
USING (
    created_by = smartlib.current_actor_id()
    OR assigned_to = smartlib.current_actor_id()
)
WITH CHECK (
    created_by = smartlib.current_actor_id()
    OR assigned_to = smartlib.current_actor_id()
);

WITH selected AS (
    SELECT authorship.publication_authorship_id,
           authorship.publication_id,
           authorship.author_order,
           authorship.author_name_raw,
           authorship.affiliation_raw,
           authorship.affiliation_evidence,
           authorship.created_by,
           fulltext.fulltext_resource_id,
           ('00000000-0000-4000-8000-' || substr(
               md5('paper-affiliation-evidence-v1:' || authorship.publication_authorship_id::text),
               13, 12
           ))::uuid AS evidence_id
      FROM smartlib.publication_authorship authorship
      JOIN LATERAL (
          SELECT resource.fulltext_resource_id
            FROM smartlib.publication_fulltext_resource resource
           WHERE resource.publication_id = authorship.publication_id
             AND resource.extraction_state = 'extracted'
           ORDER BY resource.updated_at DESC
           LIMIT 1
      ) fulltext ON true
     WHERE NULLIF(btrim(authorship.affiliation_raw), '') IS NOT NULL
       AND authorship.verification_status <> 'rejected'
)
INSERT INTO smartlib.evidence_record (
    evidence_id, object_id, evidence_type, evidence_kind, fulltext_resource_id,
    citation, excerpt, visibility, license_tags, metadata, evidence_locator,
    verification_state, created_by
)
SELECT evidence_id, publication_id, 'publication', 'author_affiliation', fulltext_resource_id,
       '论文全文作者署名机构原文（历史数据待逐页复核）', affiliation_raw,
       'restricted', ARRAY['local-fulltext'],
       jsonb_build_object(
           'publication_authorship_id', publication_authorship_id,
           'author_order', author_order,
           'author_name_raw', author_name_raw,
           'legacy_affiliation_evidence', affiliation_evidence,
           'legacy_backfill', true,
           'requires_pdf_recheck', true
       ),
       jsonb_build_object('locator_state', 'missing_page_locator'),
       'needs_review', created_by
  FROM selected
ON CONFLICT (evidence_id) DO NOTHING;

INSERT INTO smartlib.review_task (
    review_task_id, issue_type, target_type, target_id, publication_id,
    publication_authorship_id, evidence_id, reason_code, description,
    machine_suggestion, created_by
)
SELECT ('00000000-0000-4000-8001-' || substr(
           md5('paper-affiliation-review-v1:' || evidence.evidence_id::text), 13, 12
       ))::uuid,
       'PDF_AFFILIATION_RECHECK_REQUIRED', 'evidence', evidence.evidence_id,
       evidence.object_id,
       (evidence.metadata ->> 'publication_authorship_id')::uuid,
       evidence.evidence_id,
       'legacy_affiliation_without_page_locator',
       '历史 affiliation 原文已保留；需回到论文 PDF 核对作者标记、原文页码并确认规范机构。',
       jsonb_build_object('raw_affiliation', evidence.excerpt),
       evidence.created_by
  FROM smartlib.evidence_record evidence
 WHERE evidence.evidence_kind = 'author_affiliation'
   AND evidence.verification_state = 'needs_review'
   AND evidence.metadata @> '{"legacy_backfill": true}'::jsonb
ON CONFLICT (review_task_id) DO NOTHING;

COMMENT ON COLUMN smartlib.evidence_record.evidence_kind IS
    'Semantic evidence subtype; author_affiliation stores an atomic PDF affiliation occurrence.';
COMMENT ON COLUMN smartlib.evidence_record.evidence_locator IS
    'Machine-readable PDF location such as text span, marker and bounding box.';
COMMENT ON COLUMN smartlib.relation_assertion.context_object_id IS
    'Occurrence context. For person.affiliated_with this must be the source publication.';
COMMENT ON COLUMN smartlib.relation_assertion.source_publication_authorship_id IS
    'Exact paper authorship row represented by this occurrence-level relation.';
COMMENT ON COLUMN smartlib.publication_authorship.affiliation_organization_ids IS
    'Deprecated authority field. Derived/cache only; approved paper-scoped relation_assertion rows are authoritative.';
COMMENT ON TABLE smartlib.review_task IS
    'Generic instance-level queue for unresolved evidence, identity and relationship decisions.';

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
        'source_publication_authorship_id', relation.source_publication_authorship_id,
        'predicate', relation.predicate,
        'fact_class', relation.fact_class,
        'confidence', relation.confidence,
        'review_state', relation.review_state,
        'visibility', relation.visibility,
        'created_by', relation.created_by,
        'relation_version', relation.version,
        'projection_version', 'graph-projection-v2-paper-snapshot',
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
     WHERE relation.relation_id = p_relation_id
       AND relation.object_id IS NOT NULL
       AND relation.review_state IN ('pending', 'approved')
       AND relation.system_to = 'infinity'::timestamptz
$function$;

RESET ROLE;
