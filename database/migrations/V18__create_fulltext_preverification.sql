SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

CREATE TABLE smartlib.publication_fulltext_preverification (
    preverification_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_item_id uuid NOT NULL REFERENCES smartlib.publication_import_item(import_item_id),
    content_checksum text NOT NULL CHECK (content_checksum ~ '^[A-Fa-f0-9]{64}$'),
    source_path text NOT NULL CHECK (btrim(source_path) <> ''),
    file_name text NOT NULL CHECK (btrim(file_name) <> ''),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    page_count integer CHECK (page_count IS NULL OR page_count >= 0),
    text_length bigint CHECK (text_length IS NULL OR text_length >= 0),
    extraction_method text,
    match_confidence text NOT NULL
        CHECK (match_confidence IN ('confirmed', 'confirmed_duplicates', 'probable', 'ambiguous', 'possible')),
    match_score numeric(5,4) NOT NULL CHECK (match_score BETWEEN 0 AND 1),
    preverification_status text NOT NULL
        CHECK (preverification_status IN ('ready', 'review_required', 'conflict', 'applied', 'superseded')),
    proposed_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(proposed_metadata) = 'object'),
    proposed_identifiers jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(proposed_identifiers) = 'object'),
    checks jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(checks) = 'array'),
    shared_source_rows jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(shared_source_rows) = 'array'),
    rule_version text NOT NULL CHECK (btrim(rule_version) <> ''),
    evaluated_at timestamptz NOT NULL,
    applied_at timestamptz,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (import_item_id, content_checksum)
);

CREATE INDEX publication_fulltext_preverification_queue_idx
    ON smartlib.publication_fulltext_preverification (preverification_status, evaluated_at DESC);
CREATE INDEX publication_fulltext_preverification_checksum_idx
    ON smartlib.publication_fulltext_preverification (content_checksum);

CREATE TRIGGER publication_fulltext_preverification_updated_at
BEFORE UPDATE ON smartlib.publication_fulltext_preverification
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

ALTER TABLE smartlib.publication_fulltext_preverification ENABLE ROW LEVEL SECURITY;

CREATE POLICY publication_fulltext_preverification_read
ON smartlib.publication_fulltext_preverification FOR SELECT
TO smartlib_app, smartlib_readonly
USING (true);

CREATE POLICY publication_fulltext_preverification_write
ON smartlib.publication_fulltext_preverification FOR ALL
TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (created_by = smartlib.current_actor_id());

GRANT SELECT, INSERT, UPDATE, DELETE
ON smartlib.publication_fulltext_preverification TO smartlib_app;
GRANT SELECT ON smartlib.publication_fulltext_preverification TO smartlib_readonly;

COMMENT ON TABLE smartlib.publication_fulltext_preverification IS
    'Pre-ingestion identity and attribution evidence extracted from a local full-text file';

RESET ROLE;
