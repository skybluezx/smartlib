SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

CREATE TABLE smartlib.journal_name_variant (
    journal_name_variant_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_id uuid NOT NULL REFERENCES smartlib.journal_identity(journal_id) ON DELETE CASCADE,
    name text NOT NULL CHECK (btrim(name) <> ''),
    normalized_name text NOT NULL CHECK (btrim(normalized_name) <> ''),
    variant_type text NOT NULL CHECK (variant_type IN ('canonical','source','abbreviation','alternate')),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (journal_id,name)
);
CREATE INDEX journal_name_variant_normalized_idx
    ON smartlib.journal_name_variant(normalized_name);

CREATE TABLE smartlib.journal_name_variant_source (
    journal_name_variant_id uuid NOT NULL
        REFERENCES smartlib.journal_name_variant(journal_name_variant_id) ON DELETE CASCADE,
    source_reference_id uuid NOT NULL
        REFERENCES smartlib.source_reference(source_reference_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (journal_name_variant_id,source_reference_id)
);

CREATE TRIGGER journal_name_variant_updated_at BEFORE UPDATE ON smartlib.journal_name_variant
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER journal_name_variant_history AFTER INSERT OR UPDATE OR DELETE
ON smartlib.journal_name_variant FOR EACH ROW
EXECUTE FUNCTION smartlib.capture_entity_revision('journal_name_variant_id');

GRANT SELECT,INSERT,UPDATE,DELETE ON smartlib.journal_name_variant,
    smartlib.journal_name_variant_source TO smartlib_app;
GRANT SELECT ON smartlib.journal_name_variant,
    smartlib.journal_name_variant_source TO smartlib_readonly;

ALTER TABLE smartlib.journal_name_variant ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.journal_name_variant_source ENABLE ROW LEVEL SECURITY;
CREATE POLICY journal_name_variant_read ON smartlib.journal_name_variant
FOR SELECT TO smartlib_app,smartlib_readonly
USING (smartlib.actor_has_permission(smartlib.current_actor_id(),'journal_metric.read'));
CREATE POLICY journal_name_variant_write ON smartlib.journal_name_variant
FOR ALL TO smartlib_app
USING (smartlib.actor_has_permission(smartlib.current_actor_id(),'journal_metric.import'))
WITH CHECK (smartlib.actor_has_permission(smartlib.current_actor_id(),'journal_metric.import'));
CREATE POLICY journal_name_variant_source_read ON smartlib.journal_name_variant_source
FOR SELECT TO smartlib_app,smartlib_readonly USING (EXISTS (
    SELECT 1 FROM smartlib.journal_name_variant variant
    WHERE variant.journal_name_variant_id=journal_name_variant_source.journal_name_variant_id
));
CREATE POLICY journal_name_variant_source_write ON smartlib.journal_name_variant_source
FOR ALL TO smartlib_app USING (EXISTS (
    SELECT 1 FROM smartlib.journal_name_variant variant
    WHERE variant.journal_name_variant_id=journal_name_variant_source.journal_name_variant_id
)) WITH CHECK (EXISTS (
    SELECT 1 FROM smartlib.journal_name_variant variant
    WHERE variant.journal_name_variant_id=journal_name_variant_source.journal_name_variant_id
));

COMMENT ON TABLE smartlib.journal_name_variant IS
    'Searchable journal title aliases. normalized_name uses the Unicode-safe application rule.';
COMMENT ON TABLE smartlib.journal_name_variant_source IS
    'Many-to-many provenance links between journal aliases and bibliographic source records.';

RESET ROLE;
