SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

-- Journal metrics are governed, versioned evidence. They are not mutable
-- columns on publication_metadata and they never imply a person-level score.
CREATE TABLE smartlib.journal_identity (
    journal_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_title text NOT NULL CHECK (btrim(canonical_title) <> ''),
    normalized_title text NOT NULL CHECK (btrim(normalized_title) <> ''),
    issn text CHECK (issn IS NULL OR issn ~ '^[0-9]{4}-[0-9]{3}[0-9X]$'),
    eissn text CHECK (eissn IS NULL OR eissn ~ '^[0-9]{4}-[0-9]{3}[0-9X]$'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE UNIQUE INDEX journal_identity_issn_idx ON smartlib.journal_identity (issn)
WHERE issn IS NOT NULL;
CREATE UNIQUE INDEX journal_identity_eissn_idx ON smartlib.journal_identity (eissn)
WHERE eissn IS NOT NULL;
CREATE INDEX journal_identity_normalized_title_idx
    ON smartlib.journal_identity (lower(normalized_title));

CREATE TABLE smartlib.journal_metric_release (
    release_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_asset_version_id uuid NOT NULL UNIQUE
        REFERENCES smartlib.data_asset_version(data_asset_version_id),
    metric_system text NOT NULL
        CHECK (metric_system IN ('jcr', 'cas_partition')),
    edition_year integer NOT NULL CHECK (edition_year BETWEEN 1900 AND 2200),
    metric_year integer NOT NULL CHECK (metric_year BETWEEN 1900 AND 2200),
    release_label text NOT NULL CHECK (btrim(release_label) <> ''),
    publisher_name text NOT NULL CHECK (btrim(publisher_name) <> ''),
    source_uri text NOT NULL CHECK (btrim(source_uri) <> ''),
    source_sheet text NOT NULL CHECK (btrim(source_sheet) <> ''),
    source_file_checksum text NOT NULL
        CHECK (source_file_checksum ~ '^[A-Fa-f0-9]{64}$'),
    expected_record_count integer NOT NULL CHECK (expected_record_count >= 0),
    authority_status text NOT NULL DEFAULT 'unverified'
        CHECK (authority_status IN ('unverified', 'verified', 'rejected')),
    release_state text NOT NULL DEFAULT 'staged'
        CHECK (release_state IN ('staged', 'validated', 'published', 'rejected', 'superseded')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    verified_by uuid,
    verified_at timestamptz,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (metric_year <= edition_year),
    CHECK (
        release_state <> 'published'
        OR (authority_status = 'verified' AND verified_by IS NOT NULL AND verified_at IS NOT NULL)
    ),
    UNIQUE (metric_system, edition_year, source_file_checksum)
);

CREATE UNIQUE INDEX journal_metric_one_published_edition_idx
    ON smartlib.journal_metric_release (metric_system, edition_year)
    WHERE release_state = 'published';

-- One row here is one row in the governed source file. This matters because
-- some redistributed workbooks collapse several categories into one row,
-- while other editions provide one journal-category row.
CREATE TABLE smartlib.journal_metric_record (
    record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    release_id uuid NOT NULL REFERENCES smartlib.journal_metric_release(release_id),
    journal_id uuid NOT NULL REFERENCES smartlib.journal_identity(journal_id),
    source_row_number integer NOT NULL CHECK (source_row_number >= 1),
    record_granularity text NOT NULL
        CHECK (record_granularity IN ('journal', 'journal_category')),
    total_citations bigint CHECK (total_citations IS NULL OR total_citations >= 0),
    impact_factor numeric CHECK (impact_factor IS NULL OR impact_factor >= 0),
    impact_factor_is_upper_bound boolean NOT NULL DEFAULT false,
    quartile text CHECK (quartile IS NULL OR quartile IN ('Q1', 'Q2', 'Q3', 'Q4')),
    previous_quartile text
        CHECK (previous_quartile IS NULL OR previous_quartile IN ('Q1', 'Q2', 'Q3', 'Q4')),
    rank_position integer CHECK (rank_position IS NULL OR rank_position >= 1),
    rank_total integer CHECK (rank_total IS NULL OR rank_total >= 1),
    raw_payload jsonb NOT NULL CHECK (jsonb_typeof(raw_payload) = 'object'),
    row_checksum text NOT NULL CHECK (row_checksum ~ '^[A-Fa-f0-9]{64}$'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (release_id, source_row_number),
    CHECK (rank_position IS NULL OR rank_total IS NULL OR rank_position <= rank_total)
);

CREATE TABLE smartlib.journal_metric_record_category (
    record_category_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id uuid NOT NULL REFERENCES smartlib.journal_metric_record(record_id),
    category_order integer NOT NULL CHECK (category_order >= 1),
    category_name text NOT NULL CHECK (btrim(category_name) <> ''),
    citation_indexes text[] NOT NULL DEFAULT ARRAY[]::text[],
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (record_id, category_order),
    UNIQUE (record_id, category_name)
);

-- A publication-to-metric link is an auditable interpretation. It does not
-- rewrite publication_metadata, and all category records remain available.
CREATE TABLE smartlib.publication_journal_metric_match (
    match_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id uuid NOT NULL REFERENCES smartlib.knowledge_object(object_id),
    record_id uuid NOT NULL REFERENCES smartlib.journal_metric_record(record_id),
    match_basis text NOT NULL CHECK (match_basis IN ('issn', 'eissn', 'title', 'manual')),
    match_state text NOT NULL DEFAULT 'candidate'
        CHECK (match_state IN ('candidate', 'matched', 'review_required', 'rejected')),
    confidence numeric(5,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    year_policy text NOT NULL
        CHECK (year_policy IN ('publication_year', 'latest_available', 'manual')),
    decision_reason text,
    decided_by uuid,
    decided_at timestamptz,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (publication_id, record_id),
    CHECK (
        match_state NOT IN ('matched', 'rejected')
        OR (decided_by IS NOT NULL AND decided_at IS NOT NULL AND btrim(decision_reason) <> '')
    )
);

CREATE INDEX journal_metric_release_state_idx
    ON smartlib.journal_metric_release (metric_system, edition_year DESC, release_state);
CREATE INDEX journal_metric_record_journal_idx
    ON smartlib.journal_metric_record (journal_id, release_id);
CREATE INDEX journal_metric_record_quartile_idx
    ON smartlib.journal_metric_record (release_id, quartile);
CREATE INDEX journal_metric_category_name_idx
    ON smartlib.journal_metric_record_category (lower(category_name));
CREATE INDEX publication_journal_metric_match_publication_idx
    ON smartlib.publication_journal_metric_match (publication_id, match_state);

CREATE TRIGGER journal_identity_updated_at BEFORE UPDATE ON smartlib.journal_identity
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER publication_journal_metric_match_updated_at
BEFORE UPDATE ON smartlib.publication_journal_metric_match
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

CREATE FUNCTION smartlib.prevent_published_journal_metric_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    selected_release_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'journal_metric_record' THEN
        selected_release_id := OLD.release_id;
    ELSE
        SELECT record.release_id INTO selected_release_id
          FROM smartlib.journal_metric_record record
         WHERE record.record_id = OLD.record_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM smartlib.journal_metric_release release
         WHERE release.release_id = selected_release_id
           AND release.release_state = 'published'
    ) THEN
        RAISE EXCEPTION 'published journal metric records are immutable';
    END IF;
    RETURN OLD;
END
$function$;

CREATE TRIGGER journal_metric_record_immutable
BEFORE UPDATE OR DELETE ON smartlib.journal_metric_record
FOR EACH ROW EXECUTE FUNCTION smartlib.prevent_published_journal_metric_mutation();
CREATE TRIGGER journal_metric_category_immutable
BEFORE UPDATE OR DELETE ON smartlib.journal_metric_record_category
FOR EACH ROW EXECUTE FUNCTION smartlib.prevent_published_journal_metric_mutation();

INSERT INTO smartlib.access_permission (code, name, risk_level) VALUES
    ('journal_metric.read', '查看期刊权威指标', 'read'),
    ('journal_metric.import', '导入期刊指标暂存版本', 'high'),
    ('journal_metric.publish', '发布期刊权威指标版本', 'high'),
    ('journal_metric.match', '关联论文与期刊指标', 'normal');

INSERT INTO smartlib.access_role_permission (role_id, permission_id)
SELECT role.role_id, permission.permission_id
  FROM smartlib.access_role role
 CROSS JOIN smartlib.access_permission permission
 WHERE permission.code LIKE 'journal_metric.%'
   AND (
       role.code = 'knowledge_admin'
       OR (role.code = 'publication_reviewer'
           AND permission.code IN ('journal_metric.read', 'journal_metric.match'))
       OR (role.code = 'system_observer' AND permission.code = 'journal_metric.read')
   );

GRANT SELECT, INSERT, UPDATE ON smartlib.journal_identity TO smartlib_app;
GRANT SELECT, INSERT ON smartlib.journal_metric_release,
    smartlib.journal_metric_record, smartlib.journal_metric_record_category
TO smartlib_app;
GRANT SELECT, INSERT, UPDATE ON smartlib.publication_journal_metric_match TO smartlib_app;
GRANT SELECT ON smartlib.journal_identity, smartlib.journal_metric_release,
    smartlib.journal_metric_record, smartlib.journal_metric_record_category,
    smartlib.publication_journal_metric_match
TO smartlib_readonly;

ALTER TABLE smartlib.journal_identity ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.journal_metric_release ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.journal_metric_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.journal_metric_record_category ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_journal_metric_match ENABLE ROW LEVEL SECURITY;

CREATE POLICY journal_identity_read ON smartlib.journal_identity
FOR SELECT TO smartlib_app, smartlib_readonly
USING (smartlib.actor_has_permission(smartlib.current_actor_id(), 'journal_metric.read'));
CREATE POLICY journal_identity_write ON smartlib.journal_identity
FOR ALL TO smartlib_app
USING (smartlib.actor_has_permission(smartlib.current_actor_id(), 'journal_metric.import'))
WITH CHECK (smartlib.actor_has_permission(smartlib.current_actor_id(), 'journal_metric.import'));

CREATE POLICY journal_metric_release_read ON smartlib.journal_metric_release
FOR SELECT TO smartlib_app, smartlib_readonly
USING (
    smartlib.actor_has_permission(smartlib.current_actor_id(), 'journal_metric.read')
    AND EXISTS (
        SELECT 1 FROM smartlib.data_asset_version version
         WHERE version.data_asset_version_id = journal_metric_release.data_asset_version_id
           AND smartlib.can_read_data_asset(version.data_asset_id)
    )
);
CREATE POLICY journal_metric_release_insert ON smartlib.journal_metric_release
FOR INSERT TO smartlib_app
WITH CHECK (
    created_by = smartlib.current_actor_id()
    AND authority_status = 'unverified'
    AND release_state = 'staged'
    AND smartlib.actor_has_permission(smartlib.current_actor_id(), 'journal_metric.import')
);

CREATE POLICY journal_metric_record_read ON smartlib.journal_metric_record
FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (
    SELECT 1 FROM smartlib.journal_metric_release release
     WHERE release.release_id = journal_metric_record.release_id
));
CREATE POLICY journal_metric_record_insert ON smartlib.journal_metric_record
FOR INSERT TO smartlib_app
WITH CHECK (
    created_by = smartlib.current_actor_id()
    AND smartlib.actor_has_permission(smartlib.current_actor_id(), 'journal_metric.import')
    AND EXISTS (
        SELECT 1 FROM smartlib.journal_metric_release release
         WHERE release.release_id = journal_metric_record.release_id
           AND release.release_state = 'staged'
    )
);

CREATE POLICY journal_metric_category_read ON smartlib.journal_metric_record_category
FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (
    SELECT 1 FROM smartlib.journal_metric_record record
     WHERE record.record_id = journal_metric_record_category.record_id
));
CREATE POLICY journal_metric_category_insert ON smartlib.journal_metric_record_category
FOR INSERT TO smartlib_app
WITH CHECK (
    created_by = smartlib.current_actor_id()
    AND smartlib.actor_has_permission(smartlib.current_actor_id(), 'journal_metric.import')
    AND EXISTS (
        SELECT 1
          FROM smartlib.journal_metric_record record
          JOIN smartlib.journal_metric_release release ON release.release_id = record.release_id
         WHERE record.record_id = journal_metric_record_category.record_id
           AND release.release_state = 'staged'
    )
);

CREATE POLICY publication_journal_metric_match_read
ON smartlib.publication_journal_metric_match
FOR SELECT TO smartlib_app, smartlib_readonly
USING (
    smartlib.actor_has_permission(smartlib.current_actor_id(), 'journal_metric.read')
    AND EXISTS (
        SELECT 1 FROM smartlib.knowledge_object object
         WHERE object.object_id = publication_journal_metric_match.publication_id
    )
);
CREATE POLICY publication_journal_metric_match_write
ON smartlib.publication_journal_metric_match
FOR ALL TO smartlib_app
USING (smartlib.actor_has_permission(smartlib.current_actor_id(), 'journal_metric.match'))
WITH CHECK (
    created_by = smartlib.current_actor_id()
    AND smartlib.actor_has_permission(smartlib.current_actor_id(), 'journal_metric.match')
    AND EXISTS (
        SELECT 1
          FROM smartlib.journal_metric_record record
          JOIN smartlib.journal_metric_release release ON release.release_id = record.release_id
         WHERE record.record_id = publication_journal_metric_match.record_id
           AND release.release_state = 'published'
    )
);

CREATE FUNCTION smartlib.publish_journal_metric_release(selected_release_id uuid)
RETURNS smartlib.journal_metric_release
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = smartlib, pg_catalog
AS $function$
DECLARE
    selected_release smartlib.journal_metric_release;
    actual_record_count integer;
BEGIN
    IF NOT smartlib.actor_has_permission(
        smartlib.current_actor_id(), 'journal_metric.publish'
    ) THEN
        RAISE EXCEPTION 'journal metric publish permission required';
    END IF;

    SELECT release.* INTO selected_release
      FROM smartlib.journal_metric_release release
     WHERE release.release_id = selected_release_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'journal metric release not found';
    END IF;
    IF selected_release.release_state NOT IN ('staged', 'validated') THEN
        RAISE EXCEPTION 'only staged or validated journal metric releases can be published';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM smartlib.data_asset_version version
          JOIN smartlib.data_asset asset ON asset.data_asset_id = version.data_asset_id
          JOIN smartlib.source_system source ON source.source_system_id = asset.source_system_id
          JOIN smartlib.license_grant license ON license.data_asset_id = asset.data_asset_id
         WHERE version.data_asset_version_id = selected_release.data_asset_version_id
           AND source.authorization_state = 'approved'
           AND license.authorization_state = 'approved'
           AND (license.valid_from IS NULL OR license.valid_from <= clock_timestamp())
           AND (license.valid_to IS NULL OR license.valid_to > clock_timestamp())
           AND 'publication_governance' = ANY(license.allowed_purposes)
    ) THEN
        RAISE EXCEPTION 'approved source and effective publication_governance license required';
    END IF;

    SELECT count(*) INTO actual_record_count
      FROM smartlib.journal_metric_record record
     WHERE record.release_id = selected_release_id;
    IF actual_record_count <> selected_release.expected_record_count THEN
        RAISE EXCEPTION 'journal metric record count mismatch: expected %, actual %',
            selected_release.expected_record_count, actual_record_count;
    END IF;

    UPDATE smartlib.journal_metric_release
       SET authority_status = 'verified', release_state = 'published',
           verified_by = smartlib.current_actor_id(), verified_at = clock_timestamp()
     WHERE release_id = selected_release_id
     RETURNING * INTO selected_release;
    RETURN selected_release;
END
$function$;

REVOKE ALL ON FUNCTION smartlib.publish_journal_metric_release(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.publish_journal_metric_release(uuid) TO smartlib_app;

COMMENT ON TABLE smartlib.journal_metric_release IS
    'Versioned journal-indicator release governed by data asset, source authority and license state';
COMMENT ON TABLE smartlib.journal_metric_record IS
    'Immutable source-row metric evidence; JCR and CAS partitions remain distinct metric systems';
COMMENT ON TABLE smartlib.publication_journal_metric_match IS
    'Auditable publication-to-journal-metric interpretation without rewriting bibliographic metadata';
COMMENT ON FUNCTION smartlib.publish_journal_metric_release(uuid) IS
    'Fail-closed publication gate requiring approved source, effective purpose license and exact row reconciliation';

RESET ROLE;
