SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

CREATE TABLE smartlib.publication_import_batch (
    import_batch_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system_id uuid NOT NULL REFERENCES smartlib.source_system(source_system_id),
    dataset_version text NOT NULL UNIQUE CHECK (btrim(dataset_version) <> ''),
    source_file_uri text NOT NULL CHECK (btrim(source_file_uri) <> ''),
    source_file_checksum text NOT NULL CHECK (source_file_checksum ~ '^[A-Fa-f0-9]{64}$'),
    source_sheet text NOT NULL CHECK (btrim(source_sheet) <> ''),
    expected_item_count integer NOT NULL CHECK (expected_item_count >= 0),
    batch_state text NOT NULL DEFAULT 'created'
        CHECK (batch_state IN ('created', 'imported', 'verifying', 'completed', 'failed', 'cancelled')),
    verification_rule_version text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE smartlib.publication_import_item (
    import_item_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_batch_id uuid NOT NULL REFERENCES smartlib.publication_import_batch(import_batch_id),
    source_sheet text NOT NULL CHECK (btrim(source_sheet) <> ''),
    source_row_number integer NOT NULL CHECK (source_row_number >= 1),
    representative_work_number text,
    awardee_name_raw text,
    raw_payload jsonb NOT NULL CHECK (jsonb_typeof(raw_payload) = 'object'),
    normalized_payload jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(normalized_payload) = 'object'),
    row_checksum text NOT NULL CHECK (row_checksum ~ '^[A-Fa-f0-9]{64}$'),
    verification_state text NOT NULL DEFAULT 'pending'
        CHECK (verification_state IN (
            'pending', 'normalized', 'auto_verified', 'manual_review',
            'human_verified', 'corrected', 'rejected', 'superseded'
        )),
    matched_publication_id uuid REFERENCES smartlib.knowledge_object(object_id),
    duplicate_of_item_id uuid REFERENCES smartlib.publication_import_item(import_item_id),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (import_batch_id, source_sheet, source_row_number),
    CHECK (duplicate_of_item_id IS NULL OR duplicate_of_item_id <> import_item_id),
    CHECK (verification_state <> 'superseded' OR duplicate_of_item_id IS NOT NULL)
);

CREATE TABLE smartlib.publication_metadata (
    publication_id uuid PRIMARY KEY REFERENCES smartlib.knowledge_object(object_id),
    title text NOT NULL CHECK (btrim(title) <> ''),
    subtitle text,
    abstract text,
    journal_name text,
    journal_abbreviation text,
    issn text,
    eissn text,
    publication_year integer CHECK (publication_year BETWEEN 1500 AND 2200),
    published_online_at date,
    published_print_at date,
    volume text,
    issue text,
    pages text,
    article_number text,
    publication_type text,
    language_code text CHECK (language_code IS NULL OR language_code ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),
    publication_status text NOT NULL DEFAULT 'unknown'
        CHECK (publication_status IN ('unknown', 'preprint', 'early_access', 'published', 'corrected', 'retracted')),
    metadata_version bigint NOT NULL DEFAULT 1 CHECK (metadata_version >= 1),
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(attributes) = 'object'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE smartlib.publication_identifier (
    publication_identifier_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id uuid NOT NULL REFERENCES smartlib.knowledge_object(object_id),
    identifier_type text NOT NULL CHECK (identifier_type ~ '^[a-z][a-z0-9_.-]{1,63}$'),
    raw_value text NOT NULL CHECK (btrim(raw_value) <> ''),
    normalized_value text NOT NULL CHECK (btrim(normalized_value) <> ''),
    is_primary boolean NOT NULL DEFAULT false,
    verification_status text NOT NULL DEFAULT 'pending'
        CHECK (verification_status IN ('pending', 'matched', 'conflict', 'corrected', 'rejected')),
    source_reference_id uuid REFERENCES smartlib.source_reference(source_reference_id),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE UNIQUE INDEX publication_identifier_active_identity_idx
    ON smartlib.publication_identifier (identifier_type, lower(normalized_value))
    WHERE verification_status <> 'rejected';
CREATE UNIQUE INDEX publication_identifier_primary_kind_idx
    ON smartlib.publication_identifier (publication_id, identifier_type)
    WHERE is_primary AND verification_status <> 'rejected';

CREATE TABLE smartlib.publication_authorship (
    publication_authorship_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id uuid NOT NULL REFERENCES smartlib.knowledge_object(object_id),
    author_order integer NOT NULL CHECK (author_order >= 1),
    author_name_raw text NOT NULL CHECK (btrim(author_name_raw) <> ''),
    author_name_normalized text NOT NULL CHECK (btrim(author_name_normalized) <> ''),
    given_name text,
    family_name text,
    orcid text CHECK (orcid IS NULL OR orcid ~ '^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$'),
    affiliation_raw text,
    is_first_author boolean NOT NULL DEFAULT false,
    is_co_first_author boolean NOT NULL DEFAULT false,
    is_corresponding_author boolean NOT NULL DEFAULT false,
    person_object_id uuid REFERENCES smartlib.knowledge_object(object_id),
    match_status text NOT NULL DEFAULT 'unmatched'
        CHECK (match_status IN ('unmatched', 'candidate', 'matched', 'ambiguous', 'rejected')),
    verification_status text NOT NULL DEFAULT 'pending'
        CHECK (verification_status IN ('pending', 'matched', 'conflict', 'corrected', 'rejected')),
    source_reference_id uuid REFERENCES smartlib.source_reference(source_reference_id),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (publication_id, author_order),
    CHECK (person_object_id IS NULL OR match_status IN ('candidate', 'matched', 'ambiguous'))
);

CREATE TABLE smartlib.publication_field_verification (
    field_verification_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_item_id uuid NOT NULL REFERENCES smartlib.publication_import_item(import_item_id),
    publication_id uuid REFERENCES smartlib.knowledge_object(object_id),
    field_name text NOT NULL CHECK (field_name ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    source_value jsonb,
    normalized_source_value jsonb,
    candidate_value jsonb,
    candidate_source_code text,
    candidate_external_id text,
    match_score numeric(5,4) CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 1)),
    verification_status text NOT NULL DEFAULT 'pending'
        CHECK (verification_status IN ('pending', 'matched', 'conflict', 'corrected', 'rejected')),
    difference_type text,
    decision_reason text,
    source_reference_id uuid REFERENCES smartlib.source_reference(source_reference_id),
    comparison_details jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(comparison_details) = 'object'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE NULLS NOT DISTINCT (
        import_item_id, field_name, candidate_source_code, candidate_external_id
    )
);

CREATE TABLE smartlib.publication_verification_decision (
    verification_decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_item_id uuid NOT NULL REFERENCES smartlib.publication_import_item(import_item_id),
    publication_id uuid REFERENCES smartlib.knowledge_object(object_id),
    decision text NOT NULL
        CHECK (decision IN ('auto_verified', 'human_verified', 'corrected', 'rejected', 'superseded')),
    decision_reason text NOT NULL CHECK (btrim(decision_reason) <> ''),
    decision_method text NOT NULL CHECK (decision_method IN ('rule', 'human')),
    rule_version text,
    evidence_summary jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(evidence_summary) = 'object'),
    is_current boolean NOT NULL DEFAULT true,
    decided_by uuid NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        decision IN ('rejected', 'superseded')
        OR publication_id IS NOT NULL
    ),
    CHECK (decision_method <> 'rule' OR decision <> 'human_verified')
);

CREATE UNIQUE INDEX publication_verification_current_decision_idx
    ON smartlib.publication_verification_decision (import_item_id)
    WHERE is_current;

CREATE INDEX publication_import_item_state_idx
    ON smartlib.publication_import_item (import_batch_id, verification_state, source_row_number);
CREATE INDEX publication_import_item_publication_idx
    ON smartlib.publication_import_item (matched_publication_id)
    WHERE matched_publication_id IS NOT NULL;
CREATE INDEX publication_metadata_journal_year_idx
    ON smartlib.publication_metadata (journal_name, publication_year);
CREATE INDEX publication_authorship_person_idx
    ON smartlib.publication_authorship (person_object_id, verification_status)
    WHERE person_object_id IS NOT NULL;
CREATE INDEX publication_field_verification_queue_idx
    ON smartlib.publication_field_verification (verification_status, import_item_id);

CREATE FUNCTION smartlib.assert_knowledge_object_type()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
DECLARE
    selected_object_id uuid;
    expected_type text := TG_ARGV[1];
BEGIN
    selected_object_id := NULLIF(to_jsonb(NEW) ->> TG_ARGV[0], '')::uuid;
    IF selected_object_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM smartlib.knowledge_object
        WHERE object_id = selected_object_id
          AND object_type = expected_type
          AND system_to = 'infinity'::timestamptz
    ) THEN
        RAISE EXCEPTION '% must reference an active % knowledge object, got %',
            TG_ARGV[0], expected_type, selected_object_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER publication_import_item_publication_type
BEFORE INSERT OR UPDATE OF matched_publication_id ON smartlib.publication_import_item
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type('matched_publication_id', 'publication');
CREATE TRIGGER publication_metadata_publication_type
BEFORE INSERT OR UPDATE OF publication_id ON smartlib.publication_metadata
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type('publication_id', 'publication');
CREATE TRIGGER publication_identifier_publication_type
BEFORE INSERT OR UPDATE OF publication_id ON smartlib.publication_identifier
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type('publication_id', 'publication');
CREATE TRIGGER publication_authorship_publication_type
BEFORE INSERT OR UPDATE OF publication_id ON smartlib.publication_authorship
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type('publication_id', 'publication');
CREATE TRIGGER publication_authorship_person_type
BEFORE INSERT OR UPDATE OF person_object_id ON smartlib.publication_authorship
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type('person_object_id', 'person');
CREATE TRIGGER publication_field_verification_publication_type
BEFORE INSERT OR UPDATE OF publication_id ON smartlib.publication_field_verification
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type('publication_id', 'publication');
CREATE TRIGGER publication_verification_decision_publication_type
BEFORE INSERT OR UPDATE OF publication_id ON smartlib.publication_verification_decision
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type('publication_id', 'publication');

CREATE TRIGGER publication_import_batch_updated_at
BEFORE UPDATE ON smartlib.publication_import_batch
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER publication_import_item_updated_at
BEFORE UPDATE ON smartlib.publication_import_item
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER publication_metadata_updated_at
BEFORE UPDATE ON smartlib.publication_metadata
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER publication_identifier_updated_at
BEFORE UPDATE ON smartlib.publication_identifier
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER publication_authorship_updated_at
BEFORE UPDATE ON smartlib.publication_authorship
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER publication_field_verification_updated_at
BEFORE UPDATE ON smartlib.publication_field_verification
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

CREATE FUNCTION smartlib.enforce_publication_decision_history()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'publication verification decisions are append-only'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.is_current
       AND NOT NEW.is_current
       AND (to_jsonb(NEW) - 'is_current') = (to_jsonb(OLD) - 'is_current') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'publication verification decisions are immutable except current retirement'
        USING ERRCODE = '55000';
END
$function$;

CREATE TRIGGER publication_verification_decision_history
BEFORE UPDATE OR DELETE ON smartlib.publication_verification_decision
FOR EACH ROW EXECUTE FUNCTION smartlib.enforce_publication_decision_history();

GRANT SELECT, INSERT, UPDATE ON
    smartlib.publication_import_batch,
    smartlib.publication_import_item,
    smartlib.publication_metadata,
    smartlib.publication_identifier,
    smartlib.publication_authorship,
    smartlib.publication_field_verification,
    smartlib.publication_verification_decision
TO smartlib_app;

GRANT SELECT ON
    smartlib.publication_import_batch,
    smartlib.publication_import_item,
    smartlib.publication_metadata,
    smartlib.publication_identifier,
    smartlib.publication_authorship,
    smartlib.publication_field_verification,
    smartlib.publication_verification_decision
TO smartlib_readonly;

ALTER TABLE smartlib.publication_import_batch ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_import_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_identifier ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_authorship ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_field_verification ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_verification_decision ENABLE ROW LEVEL SECURITY;

CREATE POLICY publication_import_batch_read ON smartlib.publication_import_batch
FOR SELECT TO smartlib_app, smartlib_readonly
USING (created_by = smartlib.current_actor_id());
CREATE POLICY publication_import_batch_write ON smartlib.publication_import_batch
FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (created_by = smartlib.current_actor_id());

CREATE POLICY publication_import_item_read ON smartlib.publication_import_item
FOR SELECT TO smartlib_app, smartlib_readonly
USING (created_by = smartlib.current_actor_id());
CREATE POLICY publication_import_item_write ON smartlib.publication_import_item
FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (
    created_by = smartlib.current_actor_id()
    AND EXISTS (
        SELECT 1 FROM smartlib.publication_import_batch batch
        WHERE batch.import_batch_id = publication_import_item.import_batch_id
          AND batch.created_by = smartlib.current_actor_id()
    )
);

CREATE POLICY publication_metadata_read ON smartlib.publication_metadata
FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (
    SELECT 1 FROM smartlib.knowledge_object object
    WHERE object.object_id = publication_metadata.publication_id
));
CREATE POLICY publication_metadata_write ON smartlib.publication_metadata
FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (
    created_by = smartlib.current_actor_id()
    AND EXISTS (
        SELECT 1 FROM smartlib.knowledge_object object
        WHERE object.object_id = publication_metadata.publication_id
          AND object.created_by = smartlib.current_actor_id()
    )
);

CREATE POLICY publication_identifier_read ON smartlib.publication_identifier
FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (
    SELECT 1 FROM smartlib.knowledge_object object
    WHERE object.object_id = publication_identifier.publication_id
));
CREATE POLICY publication_identifier_write ON smartlib.publication_identifier
FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (
    created_by = smartlib.current_actor_id()
    AND EXISTS (
        SELECT 1 FROM smartlib.knowledge_object object
        WHERE object.object_id = publication_identifier.publication_id
          AND object.created_by = smartlib.current_actor_id()
    )
);

CREATE POLICY publication_authorship_read ON smartlib.publication_authorship
FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (
    SELECT 1 FROM smartlib.knowledge_object object
    WHERE object.object_id = publication_authorship.publication_id
));
CREATE POLICY publication_authorship_write ON smartlib.publication_authorship
FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (
    created_by = smartlib.current_actor_id()
    AND EXISTS (
        SELECT 1 FROM smartlib.knowledge_object object
        WHERE object.object_id = publication_authorship.publication_id
          AND object.created_by = smartlib.current_actor_id()
    )
);

CREATE POLICY publication_field_verification_read ON smartlib.publication_field_verification
FOR SELECT TO smartlib_app, smartlib_readonly
USING (created_by = smartlib.current_actor_id());
CREATE POLICY publication_field_verification_write ON smartlib.publication_field_verification
FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (
    created_by = smartlib.current_actor_id()
    AND EXISTS (
        SELECT 1 FROM smartlib.publication_import_item item
        WHERE item.import_item_id = publication_field_verification.import_item_id
          AND item.created_by = smartlib.current_actor_id()
    )
);

CREATE POLICY publication_verification_decision_read ON smartlib.publication_verification_decision
FOR SELECT TO smartlib_app, smartlib_readonly
USING (created_by = smartlib.current_actor_id());
CREATE POLICY publication_verification_decision_write ON smartlib.publication_verification_decision
FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (
    created_by = smartlib.current_actor_id()
    AND decided_by = smartlib.current_actor_id()
    AND EXISTS (
        SELECT 1 FROM smartlib.publication_import_item item
        WHERE item.import_item_id = publication_verification_decision.import_item_id
          AND item.created_by = smartlib.current_actor_id()
    )
);

COMMENT ON TABLE smartlib.publication_import_batch IS
    'Versioned, controlled import batch for publication rows awaiting verification';
COMMENT ON TABLE smartlib.publication_import_item IS
    'Immutable source-row identity plus normalized and verification workflow state';
COMMENT ON TABLE smartlib.publication_metadata IS
    'Canonical structured bibliographic metadata for publication knowledge objects';
COMMENT ON TABLE smartlib.publication_identifier IS
    'Normalized DOI, PMID, PMCID, WoS and other publication identifiers';
COMMENT ON TABLE smartlib.publication_authorship IS
    'Ordered canonical author list with optional verified SmartLib person linkage';
COMMENT ON TABLE smartlib.publication_field_verification IS
    'Field-level comparison between source values and external verification candidates';
COMMENT ON TABLE smartlib.publication_verification_decision IS
    'Append-oriented automatic or human publication verification decisions';

RESET ROLE;
