CREATE TABLE smartlib.publication_verification_layer (
    layer_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_item_id uuid NOT NULL REFERENCES smartlib.publication_import_item(import_item_id),
    layer_code text NOT NULL
        CHECK (layer_code IN ('identity', 'attribution', 'enrichment')),
    layer_status text NOT NULL DEFAULT 'pending'
        CHECK (layer_status IN ('pending', 'passed', 'conflict', 'incomplete', 'not_applicable')),
    is_blocking boolean NOT NULL,
    check_count integer NOT NULL DEFAULT 0 CHECK (check_count >= 0),
    passed_count integer NOT NULL DEFAULT 0 CHECK (passed_count >= 0),
    conflict_count integer NOT NULL DEFAULT 0 CHECK (conflict_count >= 0),
    missing_count integer NOT NULL DEFAULT 0 CHECK (missing_count >= 0),
    rule_version text NOT NULL CHECK (btrim(rule_version) <> ''),
    evidence_summary jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(evidence_summary) = 'object'),
    evaluated_at timestamptz,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (import_item_id, layer_code),
    CHECK (passed_count + conflict_count + missing_count <= check_count)
);

CREATE TABLE smartlib.publication_verification_check (
    check_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    layer_id uuid NOT NULL REFERENCES smartlib.publication_verification_layer(layer_id)
        ON DELETE CASCADE,
    check_code text NOT NULL CHECK (check_code ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    check_label text NOT NULL CHECK (btrim(check_label) <> ''),
    check_status text NOT NULL DEFAULT 'pending'
        CHECK (check_status IN ('pending', 'passed', 'conflict', 'missing', 'not_applicable')),
    severity text NOT NULL
        CHECK (severity IN ('blocking', 'warning', 'info')),
    source_value jsonb,
    authoritative_value jsonb,
    evidence_sources jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(evidence_sources) = 'array'),
    details jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(details) = 'object'),
    decision_reason text,
    decided_by uuid,
    decided_at timestamptz,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (layer_id, check_code)
);

CREATE INDEX publication_verification_layer_queue_idx
    ON smartlib.publication_verification_layer (layer_code, layer_status, is_blocking);
CREATE INDEX publication_verification_check_status_idx
    ON smartlib.publication_verification_check (check_status, severity);

CREATE TRIGGER publication_verification_layer_updated_at
BEFORE UPDATE ON smartlib.publication_verification_layer
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

CREATE TRIGGER publication_verification_check_updated_at
BEFORE UPDATE ON smartlib.publication_verification_check
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

ALTER TABLE smartlib.publication_verification_layer ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_verification_check ENABLE ROW LEVEL SECURITY;

CREATE POLICY publication_verification_layer_read
ON smartlib.publication_verification_layer FOR SELECT
TO smartlib_app, smartlib_readonly
USING (true);

CREATE POLICY publication_verification_layer_write
ON smartlib.publication_verification_layer FOR ALL
TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (created_by = smartlib.current_actor_id());

CREATE POLICY publication_verification_check_read
ON smartlib.publication_verification_check FOR SELECT
TO smartlib_app, smartlib_readonly
USING (
    EXISTS (
        SELECT 1
        FROM smartlib.publication_verification_layer AS layer
        WHERE layer.layer_id = publication_verification_check.layer_id
    )
);

CREATE POLICY publication_verification_check_write
ON smartlib.publication_verification_check FOR ALL
TO smartlib_app
USING (created_by = smartlib.current_actor_id())
WITH CHECK (created_by = smartlib.current_actor_id());

GRANT SELECT, INSERT, UPDATE, DELETE
ON smartlib.publication_verification_layer, smartlib.publication_verification_check
TO smartlib_app;
GRANT SELECT
ON smartlib.publication_verification_layer, smartlib.publication_verification_check
TO smartlib_readonly;

COMMENT ON TABLE smartlib.publication_verification_layer IS
    'Three-layer publication verification rollup: identity, scholar attribution and enrichment';
COMMENT ON TABLE smartlib.publication_verification_check IS
    'Inspectable check-level evidence and outcomes for each publication verification layer';
