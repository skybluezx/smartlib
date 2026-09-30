SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

CREATE TABLE smartlib.governance_domain (
    governance_domain_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_-]{1,63}$'),
    name text NOT NULL CHECK (btrim(name) <> ''),
    description text,
    visibility text NOT NULL DEFAULT 'campus' CHECK (visibility IN ('public', 'campus', 'restricted', 'private')),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE smartlib.data_asset (
    data_asset_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    governance_domain_id uuid NOT NULL REFERENCES smartlib.governance_domain(governance_domain_id),
    source_system_id uuid NOT NULL REFERENCES smartlib.source_system(source_system_id),
    code text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_-]{1,63}$'),
    name text NOT NULL CHECK (btrim(name) <> ''),
    description text,
    asset_type text NOT NULL CHECK (asset_type IN ('database', 'dataset', 'api', 'file', 'repository', 'licensed_resource', 'knowledge_collection')),
    lifecycle_state text NOT NULL DEFAULT 'active' CHECK (lifecycle_state IN ('draft', 'active', 'paused', 'retired')),
    visibility text NOT NULL DEFAULT 'campus' CHECK (visibility IN ('public', 'campus', 'restricted', 'private')),
    synthetic boolean NOT NULL DEFAULT false,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE smartlib.data_asset_version (
    data_asset_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_asset_id uuid NOT NULL REFERENCES smartlib.data_asset(data_asset_id),
    version_number bigint NOT NULL CHECK (version_number >= 1),
    schema_version text NOT NULL CHECK (btrim(schema_version) <> ''),
    effective_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    checksum text CHECK (checksum IS NULL OR checksum ~ '^[A-Fa-f0-9]{64}$'),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (data_asset_id, version_number)
);

CREATE TABLE smartlib.data_schema_field (
    data_schema_field_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_asset_version_id uuid NOT NULL REFERENCES smartlib.data_asset_version(data_asset_version_id),
    field_path text NOT NULL CHECK (btrim(field_path) <> ''),
    data_type text NOT NULL CHECK (btrim(data_type) <> ''),
    nullable boolean NOT NULL DEFAULT true,
    classification text NOT NULL DEFAULT 'internal' CHECK (classification IN ('public', 'internal', 'sensitive', 'restricted')),
    description text,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (data_asset_version_id, field_path)
);

CREATE TABLE smartlib.data_contract (
    data_contract_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_asset_id uuid NOT NULL REFERENCES smartlib.data_asset(data_asset_id),
    code text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    name text NOT NULL CHECK (btrim(name) <> ''),
    owner_department text NOT NULL CHECK (btrim(owner_department) <> ''),
    contract_state text NOT NULL DEFAULT 'draft' CHECK (contract_state IN ('draft', 'active', 'breached', 'suspended', 'retired')),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE smartlib.data_contract_version (
    data_contract_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_contract_id uuid NOT NULL REFERENCES smartlib.data_contract(data_contract_id),
    version_number bigint NOT NULL CHECK (version_number >= 1),
    expectations jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(expectations) = 'object'),
    valid_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_to timestamptz NOT NULL DEFAULT 'infinity',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (data_contract_id, version_number),
    CHECK (valid_from < valid_to)
);

CREATE TABLE smartlib.license_grant (
    license_grant_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_asset_id uuid NOT NULL REFERENCES smartlib.data_asset(data_asset_id),
    license_name text NOT NULL CHECK (btrim(license_name) <> ''),
    license_reference text NOT NULL CHECK (btrim(license_reference) <> ''),
    authorization_state text NOT NULL DEFAULT 'pending' CHECK (authorization_state IN ('pending', 'approved', 'suspended', 'expired', 'rejected')),
    allowed_content text[] NOT NULL DEFAULT ARRAY[]::text[],
    allowed_purposes text[] NOT NULL DEFAULT ARRAY[]::text[],
    prohibited_purposes text[] NOT NULL DEFAULT ARRAY[]::text[],
    valid_from timestamptz,
    valid_to timestamptz,
    terms_metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(terms_metadata) = 'object'),
    synthetic boolean NOT NULL DEFAULT false,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from < valid_to)
);

CREATE TABLE smartlib.quality_rule (
    quality_rule_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_asset_id uuid NOT NULL REFERENCES smartlib.data_asset(data_asset_id),
    code text NOT NULL CHECK (code ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    name text NOT NULL CHECK (btrim(name) <> ''),
    rule_kind text NOT NULL CHECK (rule_kind IN ('completeness', 'uniqueness', 'validity', 'freshness', 'referential_integrity', 'custom')),
    severity text NOT NULL DEFAULT 'medium' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    rule_definition jsonb NOT NULL CHECK (jsonb_typeof(rule_definition) = 'object'),
    enabled boolean NOT NULL DEFAULT true,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (data_asset_id, code)
);

CREATE TABLE smartlib.quality_run (
    quality_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    quality_rule_id uuid NOT NULL REFERENCES smartlib.quality_rule(quality_rule_id),
    run_state text NOT NULL CHECK (run_state IN ('running', 'passed', 'failed', 'error')),
    observed_value numeric,
    expected_value numeric,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((run_state = 'running' AND finished_at IS NULL) OR run_state <> 'running')
);

CREATE TABLE smartlib.quality_issue (
    quality_issue_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_asset_id uuid NOT NULL REFERENCES smartlib.data_asset(data_asset_id),
    quality_run_id uuid REFERENCES smartlib.quality_run(quality_run_id),
    title text NOT NULL CHECK (btrim(title) <> ''),
    description text,
    severity text NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    issue_state text NOT NULL DEFAULT 'open' CHECK (issue_state IN ('open', 'acknowledged', 'resolved', 'wont_fix')),
    requires_human_confirmation boolean NOT NULL DEFAULT false,
    assigned_to uuid,
    resolution text,
    detected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    resolved_at timestamptz,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK ((issue_state = 'resolved' AND resolved_at IS NOT NULL) OR issue_state <> 'resolved')
);

CREATE TABLE smartlib.stewardship_assignment (
    stewardship_assignment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_asset_id uuid NOT NULL REFERENCES smartlib.data_asset(data_asset_id),
    steward_id uuid NOT NULL,
    responsibility text NOT NULL CHECK (responsibility IN ('owner', 'steward', 'license_reviewer', 'quality_reviewer')),
    valid_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_to timestamptz NOT NULL DEFAULT 'infinity',
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (valid_from < valid_to),
    UNIQUE (data_asset_id, steward_id, responsibility, valid_from)
);

CREATE TABLE smartlib.governance_change (
    governance_change_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_type text NOT NULL CHECK (btrim(resource_type) <> ''),
    resource_id uuid NOT NULL,
    change_type text NOT NULL CHECK (change_type IN ('created', 'updated', 'state_changed', 'reviewed', 'corrected')),
    before_state jsonb,
    after_state jsonb NOT NULL CHECK (jsonb_typeof(after_state) = 'object'),
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    trace_id text,
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX data_asset_domain_idx ON smartlib.data_asset (governance_domain_id);
CREATE INDEX data_asset_source_idx ON smartlib.data_asset (source_system_id);
CREATE INDEX license_grant_asset_state_idx ON smartlib.license_grant (data_asset_id, authorization_state, valid_to);
CREATE INDEX quality_issue_asset_state_idx ON smartlib.quality_issue (data_asset_id, issue_state, severity);
CREATE INDEX governance_change_resource_idx ON smartlib.governance_change (resource_type, resource_id, created_at DESC);

CREATE TRIGGER governance_domain_updated_at BEFORE UPDATE ON smartlib.governance_domain
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER data_asset_updated_at BEFORE UPDATE ON smartlib.data_asset
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER data_contract_updated_at BEFORE UPDATE ON smartlib.data_contract
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER license_grant_updated_at BEFORE UPDATE ON smartlib.license_grant
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER quality_rule_updated_at BEFORE UPDATE ON smartlib.quality_rule
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER quality_issue_updated_at BEFORE UPDATE ON smartlib.quality_issue
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

GRANT SELECT, INSERT, UPDATE ON smartlib.governance_domain, smartlib.data_asset,
    smartlib.data_contract, smartlib.license_grant, smartlib.quality_rule, smartlib.quality_issue
TO smartlib_app;
GRANT SELECT, INSERT ON smartlib.data_asset_version, smartlib.data_schema_field,
    smartlib.data_contract_version, smartlib.quality_run, smartlib.stewardship_assignment,
    smartlib.governance_change
TO smartlib_app;
GRANT SELECT ON smartlib.governance_domain, smartlib.data_asset, smartlib.data_asset_version,
    smartlib.data_schema_field, smartlib.data_contract, smartlib.data_contract_version,
    smartlib.license_grant, smartlib.quality_rule, smartlib.quality_run, smartlib.quality_issue,
    smartlib.stewardship_assignment, smartlib.governance_change
TO smartlib_readonly;

ALTER TABLE smartlib.governance_domain ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.data_asset ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.data_asset_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.data_schema_field ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.data_contract ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.data_contract_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.license_grant ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.quality_rule ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.quality_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.quality_issue ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.stewardship_assignment ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.governance_change ENABLE ROW LEVEL SECURITY;

CREATE POLICY governance_domain_read ON smartlib.governance_domain FOR SELECT TO smartlib_app, smartlib_readonly
USING (visibility IN ('public', 'campus') OR created_by = smartlib.current_actor_id());
CREATE POLICY governance_domain_write ON smartlib.governance_domain FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id()) WITH CHECK (created_by = smartlib.current_actor_id());
CREATE POLICY data_asset_read ON smartlib.data_asset FOR SELECT TO smartlib_app, smartlib_readonly
USING (visibility IN ('public', 'campus') OR created_by = smartlib.current_actor_id());
CREATE POLICY data_asset_write ON smartlib.data_asset FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id()) WITH CHECK (created_by = smartlib.current_actor_id());

CREATE FUNCTION smartlib.can_read_data_asset(p_data_asset_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY INVOKER PARALLEL SAFE AS $function$
    SELECT EXISTS (SELECT 1 FROM smartlib.data_asset a WHERE a.data_asset_id = p_data_asset_id)
$function$;
GRANT EXECUTE ON FUNCTION smartlib.can_read_data_asset(uuid) TO smartlib_app, smartlib_readonly;

CREATE POLICY data_asset_version_read ON smartlib.data_asset_version FOR SELECT TO smartlib_app, smartlib_readonly
USING (smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY data_asset_version_write ON smartlib.data_asset_version FOR INSERT TO smartlib_app
WITH CHECK (created_by = smartlib.current_actor_id() AND smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY data_schema_field_read ON smartlib.data_schema_field FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (SELECT 1 FROM smartlib.data_asset_version v WHERE v.data_asset_version_id = data_schema_field.data_asset_version_id));
CREATE POLICY data_schema_field_write ON smartlib.data_schema_field FOR INSERT TO smartlib_app
WITH CHECK (created_by = smartlib.current_actor_id() AND EXISTS (SELECT 1 FROM smartlib.data_asset_version v WHERE v.data_asset_version_id = data_schema_field.data_asset_version_id));
CREATE POLICY data_contract_read ON smartlib.data_contract FOR SELECT TO smartlib_app, smartlib_readonly
USING (smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY data_contract_write ON smartlib.data_contract FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id()) WITH CHECK (created_by = smartlib.current_actor_id() AND smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY data_contract_version_read ON smartlib.data_contract_version FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (SELECT 1 FROM smartlib.data_contract c WHERE c.data_contract_id = data_contract_version.data_contract_id));
CREATE POLICY data_contract_version_write ON smartlib.data_contract_version FOR INSERT TO smartlib_app
WITH CHECK (created_by = smartlib.current_actor_id() AND EXISTS (SELECT 1 FROM smartlib.data_contract c WHERE c.data_contract_id = data_contract_version.data_contract_id));
CREATE POLICY license_grant_read ON smartlib.license_grant FOR SELECT TO smartlib_app, smartlib_readonly
USING (smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY license_grant_write ON smartlib.license_grant FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id()) WITH CHECK (created_by = smartlib.current_actor_id() AND smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY quality_rule_read ON smartlib.quality_rule FOR SELECT TO smartlib_app, smartlib_readonly
USING (smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY quality_rule_write ON smartlib.quality_rule FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id()) WITH CHECK (created_by = smartlib.current_actor_id() AND smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY quality_run_read ON smartlib.quality_run FOR SELECT TO smartlib_app, smartlib_readonly
USING (EXISTS (SELECT 1 FROM smartlib.quality_rule r WHERE r.quality_rule_id = quality_run.quality_rule_id));
CREATE POLICY quality_run_write ON smartlib.quality_run FOR INSERT TO smartlib_app
WITH CHECK (created_by = smartlib.current_actor_id() AND EXISTS (SELECT 1 FROM smartlib.quality_rule r WHERE r.quality_rule_id = quality_run.quality_rule_id));
CREATE POLICY quality_issue_read ON smartlib.quality_issue FOR SELECT TO smartlib_app, smartlib_readonly
USING (smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY quality_issue_write ON smartlib.quality_issue FOR ALL TO smartlib_app
USING (created_by = smartlib.current_actor_id()) WITH CHECK (created_by = smartlib.current_actor_id() AND smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY stewardship_assignment_read ON smartlib.stewardship_assignment FOR SELECT TO smartlib_app, smartlib_readonly
USING (smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY stewardship_assignment_write ON smartlib.stewardship_assignment FOR INSERT TO smartlib_app
WITH CHECK (created_by = smartlib.current_actor_id() AND smartlib.can_read_data_asset(data_asset_id));
CREATE POLICY governance_change_read ON smartlib.governance_change FOR SELECT TO smartlib_app, smartlib_readonly
USING (created_by = smartlib.current_actor_id());
CREATE POLICY governance_change_write ON smartlib.governance_change FOR INSERT TO smartlib_app
WITH CHECK (created_by = smartlib.current_actor_id());

CREATE FUNCTION smartlib.list_actor_audit_events(p_limit integer DEFAULT 10)
RETURNS TABLE (
    event_id uuid, occurred_at timestamptz, action text, resource_type text,
    resource_id text, decision text, details jsonb
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = audit, smartlib, pg_catalog
AS $function$
    SELECT e.event_id, e.occurred_at, e.action, e.resource_type,
           e.resource_id, e.decision, e.details
      FROM audit.audit_event e
     WHERE e.actor_id = smartlib.current_actor_id()
     ORDER BY e.occurred_at DESC
     LIMIT LEAST(GREATEST(p_limit, 1), 100)
$function$;
REVOKE ALL ON FUNCTION smartlib.list_actor_audit_events(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.list_actor_audit_events(integer) TO smartlib_app, smartlib_readonly;

COMMENT ON TABLE smartlib.data_asset IS 'Governed SmartLib data or licensed-resource asset; synthetic is explicit';
COMMENT ON TABLE smartlib.license_grant IS 'Purpose-scoped authorization; unknown, inactive or expired never implies permission';
COMMENT ON TABLE smartlib.quality_issue IS 'Traceable data-quality issue requiring an explicit lifecycle';
COMMENT ON TABLE smartlib.governance_change IS 'Append-only governance correction and review history';

RESET ROLE;
