SET ROLE smartlib_owner;
SET search_path = smartlib, audit, pg_catalog;

ALTER TABLE smartlib.publication_metadata
    ADD COLUMN identity_state text NOT NULL DEFAULT 'verified'
        CHECK (identity_state IN ('unverified', 'verified', 'review_required')),
    ADD COLUMN enrichment_state text NOT NULL DEFAULT 'partial'
        CHECK (enrichment_state IN ('empty', 'partial', 'complete', 'review_required')),
    ADD COLUMN fulltext_state text NOT NULL DEFAULT 'missing'
        CHECK (fulltext_state IN ('missing', 'registered', 'extracted', 'review_required')),
    ADD COLUMN last_enriched_at timestamptz;

CREATE TABLE smartlib.publication_supplement (
    supplement_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id uuid NOT NULL REFERENCES smartlib.knowledge_object(object_id),
    evidence_id uuid NOT NULL REFERENCES smartlib.evidence_record(evidence_id),
    source_kind text NOT NULL
        CHECK (source_kind IN ('metadata', 'fulltext', 'funding', 'lifecycle', 'identifier')),
    source_label text NOT NULL CHECK (btrim(source_label) <> ''),
    source_uri text,
    content_checksum text CHECK (
        content_checksum IS NULL OR content_checksum ~ '^[A-Fa-f0-9]{64}$'
    ),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
    status text NOT NULL
        CHECK (status IN ('received', 'auto_applied', 'needs_review', 'accepted', 'rejected')),
    impact text NOT NULL CHECK (impact IN ('additive', 'corrective', 'critical')),
    base_metadata_version bigint NOT NULL CHECK (base_metadata_version >= 1),
    target_metadata_version bigint CHECK (target_metadata_version >= base_metadata_version),
    decision_reason text,
    decided_by uuid,
    decided_at timestamptz,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE smartlib.publication_change_candidate (
    candidate_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    supplement_id uuid NOT NULL REFERENCES smartlib.publication_supplement(supplement_id)
        ON DELETE CASCADE,
    field_path text NOT NULL CHECK (field_path ~ '^[a-z][a-z0-9_.-]{1,255}$'),
    current_value jsonb,
    proposed_value jsonb,
    change_type text NOT NULL CHECK (change_type IN ('add', 'replace', 'confirm', 'relation_add')),
    risk_level text NOT NULL CHECK (risk_level IN ('safe', 'review', 'critical')),
    status text NOT NULL CHECK (status IN ('pending', 'auto_applied', 'accepted', 'rejected')),
    decision_reason text,
    decided_by uuid,
    decided_at timestamptz,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (supplement_id, field_path)
);

CREATE TABLE smartlib.publication_metadata_revision (
    revision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id uuid NOT NULL REFERENCES smartlib.knowledge_object(object_id),
    supplement_id uuid NOT NULL REFERENCES smartlib.publication_supplement(supplement_id),
    metadata_version bigint NOT NULL CHECK (metadata_version >= 1),
    snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    changed_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
    change_reason text NOT NULL CHECK (btrim(change_reason) <> ''),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (publication_id, metadata_version)
);

CREATE TABLE smartlib.publication_fulltext_resource (
    fulltext_resource_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id uuid NOT NULL REFERENCES smartlib.knowledge_object(object_id),
    supplement_id uuid NOT NULL REFERENCES smartlib.publication_supplement(supplement_id),
    file_name text NOT NULL CHECK (btrim(file_name) <> ''),
    storage_uri text NOT NULL CHECK (btrim(storage_uri) <> ''),
    content_checksum text NOT NULL CHECK (content_checksum ~ '^[A-Fa-f0-9]{64}$'),
    mime_type text NOT NULL CHECK (btrim(mime_type) <> ''),
    size_bytes bigint CHECK (size_bytes IS NULL OR size_bytes >= 0),
    license_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    extraction_state text NOT NULL DEFAULT 'registered'
        CHECK (extraction_state IN ('registered', 'extracting', 'extracted', 'failed')),
    extracted_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(extracted_metadata) = 'object'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (publication_id, content_checksum)
);

CREATE INDEX publication_supplement_publication_idx
    ON smartlib.publication_supplement (publication_id, created_at DESC);
CREATE UNIQUE INDEX publication_supplement_checksum_idx
    ON smartlib.publication_supplement (publication_id, source_kind, content_checksum)
    WHERE content_checksum IS NOT NULL;
CREATE INDEX publication_supplement_review_idx
    ON smartlib.publication_supplement (status, impact, created_at)
    WHERE status = 'needs_review';
CREATE INDEX publication_change_candidate_review_idx
    ON smartlib.publication_change_candidate (supplement_id, status, risk_level);
CREATE INDEX publication_fulltext_resource_publication_idx
    ON smartlib.publication_fulltext_resource (publication_id, created_at DESC);

CREATE TRIGGER publication_supplement_updated_at
BEFORE UPDATE ON smartlib.publication_supplement
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER publication_change_candidate_updated_at
BEFORE UPDATE ON smartlib.publication_change_candidate
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER publication_fulltext_resource_updated_at
BEFORE UPDATE ON smartlib.publication_fulltext_resource
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

CREATE FUNCTION smartlib.enforce_publication_revision_history()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'publication metadata revisions are append-only'
        USING ERRCODE = '55000';
END
$function$;

CREATE TRIGGER publication_metadata_revision_history
BEFORE UPDATE OR DELETE ON smartlib.publication_metadata_revision
FOR EACH ROW EXECUTE FUNCTION smartlib.enforce_publication_revision_history();

INSERT INTO smartlib.access_permission (code, name, risk_level) VALUES
    ('publication_supplement.read', '查看论文增量补充记录', 'read'),
    ('publication_supplement.submit', '提交论文增量信息', 'normal'),
    ('publication_supplement.decide', '处理论文增量信息冲突', 'high');

INSERT INTO smartlib.access_role_permission (role_id, permission_id)
SELECT role.role_id, permission.permission_id
  FROM smartlib.access_role role
 CROSS JOIN smartlib.access_permission permission
 WHERE permission.code LIKE 'publication_supplement.%'
   AND (
       role.code IN ('knowledge_admin', 'publication_reviewer')
   );

GRANT SELECT, INSERT, UPDATE ON
    smartlib.publication_supplement,
    smartlib.publication_change_candidate,
    smartlib.publication_fulltext_resource
TO smartlib_app;
GRANT SELECT, INSERT ON smartlib.publication_metadata_revision TO smartlib_app;
GRANT SELECT ON
    smartlib.publication_supplement,
    smartlib.publication_change_candidate,
    smartlib.publication_metadata_revision,
    smartlib.publication_fulltext_resource
TO smartlib_readonly;

ALTER TABLE smartlib.publication_supplement ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_change_candidate ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_metadata_revision ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_fulltext_resource ENABLE ROW LEVEL SECURITY;

CREATE POLICY publication_supplement_read ON smartlib.publication_supplement
FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (
    SELECT 1 FROM smartlib.knowledge_object object
     WHERE object.object_id = publication_supplement.publication_id
));
CREATE POLICY publication_supplement_write ON smartlib.publication_supplement
FOR ALL TO smartlib_app
USING (
    created_by = smartlib.current_actor_id()
    OR smartlib.actor_has_permission(
        smartlib.current_actor_id(), 'publication_supplement.decide'
    )
)
WITH CHECK (
    created_by = smartlib.current_actor_id()
    OR smartlib.actor_has_permission(
        smartlib.current_actor_id(), 'publication_supplement.decide'
    )
);

CREATE POLICY publication_change_candidate_read ON smartlib.publication_change_candidate
FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (
    SELECT 1 FROM smartlib.publication_supplement supplement
     WHERE supplement.supplement_id = publication_change_candidate.supplement_id
));
CREATE POLICY publication_change_candidate_write ON smartlib.publication_change_candidate
FOR ALL TO smartlib_app
USING (
    created_by = smartlib.current_actor_id()
    OR smartlib.actor_has_permission(
        smartlib.current_actor_id(), 'publication_supplement.decide'
    )
)
WITH CHECK (
    created_by = smartlib.current_actor_id()
    OR smartlib.actor_has_permission(
        smartlib.current_actor_id(), 'publication_supplement.decide'
    )
);

CREATE POLICY publication_metadata_revision_read ON smartlib.publication_metadata_revision
FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (
    SELECT 1 FROM smartlib.knowledge_object object
     WHERE object.object_id = publication_metadata_revision.publication_id
));
CREATE POLICY publication_metadata_revision_insert ON smartlib.publication_metadata_revision
FOR INSERT TO smartlib_app
WITH CHECK (created_by = smartlib.current_actor_id());

CREATE POLICY publication_fulltext_resource_read ON smartlib.publication_fulltext_resource
FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (
    SELECT 1 FROM smartlib.knowledge_object object
     WHERE object.object_id = publication_fulltext_resource.publication_id
));
CREATE POLICY publication_fulltext_resource_write ON smartlib.publication_fulltext_resource
FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (created_by = smartlib.current_actor_id());

-- Reviewers must be able to apply an accepted change to canonical records even
-- when the original import was created by another operator.
CREATE POLICY publication_supplement_object_update ON smartlib.knowledge_object
FOR UPDATE TO smartlib_app
USING (smartlib.actor_has_permission(
    smartlib.current_actor_id(), 'publication_supplement.decide'
))
WITH CHECK (smartlib.actor_has_permission(
    smartlib.current_actor_id(), 'publication_supplement.decide'
));
CREATE POLICY publication_supplement_metadata_update ON smartlib.publication_metadata
FOR UPDATE TO smartlib_app
USING (smartlib.actor_has_permission(
    smartlib.current_actor_id(), 'publication_supplement.decide'
))
WITH CHECK (smartlib.actor_has_permission(
    smartlib.current_actor_id(), 'publication_supplement.decide'
));
CREATE POLICY publication_supplement_identifier_write ON smartlib.publication_identifier
FOR ALL TO smartlib_app
USING (smartlib.actor_has_permission(
    smartlib.current_actor_id(), 'publication_supplement.decide'
))
WITH CHECK (smartlib.actor_has_permission(
    smartlib.current_actor_id(), 'publication_supplement.decide'
));
CREATE POLICY publication_supplement_relation_write ON smartlib.relation_assertion
FOR ALL TO smartlib_app
USING (smartlib.actor_has_permission(
    smartlib.current_actor_id(), 'publication_supplement.decide'
))
WITH CHECK (smartlib.actor_has_permission(
    smartlib.current_actor_id(), 'publication_supplement.decide'
));

COMMENT ON TABLE smartlib.publication_supplement IS
    'One append-oriented intake of later publication evidence and its review lifecycle';
COMMENT ON TABLE smartlib.publication_change_candidate IS
    'Field or relation changes derived from a supplement before canonical application';
COMMENT ON TABLE smartlib.publication_metadata_revision IS
    'Immutable snapshots created whenever accepted supplemental evidence changes canonical metadata';
COMMENT ON TABLE smartlib.publication_fulltext_resource IS
    'Controlled full-text resource registration with checksum, license and extraction provenance';

RESET ROLE;
