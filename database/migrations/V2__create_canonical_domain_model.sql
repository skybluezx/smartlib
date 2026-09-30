SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

CREATE FUNCTION smartlib.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at = clock_timestamp();
    RETURN NEW;
END
$function$;

CREATE TABLE smartlib.source_system (
    source_system_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_-]{1,63}$'),
    name text NOT NULL CHECK (btrim(name) <> ''),
    owner_department text NOT NULL CHECK (btrim(owner_department) <> ''),
    source_type text NOT NULL CHECK (source_type IN ('database', 'api', 'file', 'repository', 'licensed_resource', 'manual')),
    authorization_state text NOT NULL DEFAULT 'pending' CHECK (authorization_state IN ('pending', 'approved', 'suspended', 'expired', 'rejected')),
    update_schedule text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    version bigint NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE smartlib.knowledge_object (
    object_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_type text NOT NULL CHECK (object_type IN ('person', 'organization', 'department', 'discipline', 'project', 'publication', 'dataset', 'patent', 'resource', 'event', 'concept', 'requirement')),
    canonical_name text NOT NULL CHECK (btrim(canonical_name) <> ''),
    description text,
    visibility text NOT NULL DEFAULT 'restricted' CHECK (visibility IN ('public', 'campus', 'restricted', 'private')),
    quality_state text NOT NULL DEFAULT 'unverified' CHECK (quality_state IN ('unverified', 'validated', 'warning', 'rejected')),
    review_state text NOT NULL DEFAULT 'pending' CHECK (review_state IN ('pending', 'approved', 'rejected', 'superseded')),
    valid_from timestamptz NOT NULL DEFAULT '-infinity',
    valid_to timestamptz NOT NULL DEFAULT 'infinity',
    system_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    system_to timestamptz NOT NULL DEFAULT 'infinity',
    version bigint NOT NULL DEFAULT 1 CHECK (version >= 1),
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(attributes) = 'object'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_object_valid_time CHECK (valid_from < valid_to),
    CONSTRAINT knowledge_object_system_time CHECK (system_from < system_to)
);

CREATE TABLE smartlib.source_reference (
    source_reference_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id uuid NOT NULL REFERENCES smartlib.knowledge_object(object_id),
    source_system_id uuid NOT NULL REFERENCES smartlib.source_system(source_system_id),
    external_id text NOT NULL CHECK (btrim(external_id) <> ''),
    source_version text,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload_checksum text CHECK (payload_checksum IS NULL OR payload_checksum ~ '^[A-Fa-f0-9]{64}$'),
    raw_object_uri text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    valid_from timestamptz NOT NULL DEFAULT '-infinity',
    valid_to timestamptz NOT NULL DEFAULT 'infinity',
    system_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    system_to timestamptz NOT NULL DEFAULT 'infinity',
    version bigint NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT source_reference_identity UNIQUE (source_system_id, external_id, version),
    CONSTRAINT source_reference_valid_time CHECK (valid_from < valid_to),
    CONSTRAINT source_reference_system_time CHECK (system_from < system_to)
);

CREATE TABLE smartlib.evidence_record (
    evidence_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_id uuid REFERENCES smartlib.knowledge_object(object_id),
    source_reference_id uuid REFERENCES smartlib.source_reference(source_reference_id),
    evidence_type text NOT NULL CHECK (evidence_type IN ('business_record', 'publication', 'dataset', 'contract', 'manual_review', 'model_output', 'user_contribution')),
    citation text NOT NULL CHECK (btrim(citation) <> ''),
    excerpt text,
    visibility text NOT NULL DEFAULT 'restricted' CHECK (visibility IN ('public', 'campus', 'restricted', 'private')),
    license_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    content_checksum text CHECK (content_checksum IS NULL OR content_checksum ~ '^[A-Fa-f0-9]{64}$'),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT evidence_has_origin CHECK (object_id IS NOT NULL OR source_reference_id IS NOT NULL)
);

CREATE TABLE smartlib.relation_assertion (
    relation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id uuid NOT NULL REFERENCES smartlib.knowledge_object(object_id),
    predicate text NOT NULL CHECK (predicate ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    object_id uuid REFERENCES smartlib.knowledge_object(object_id),
    literal_value jsonb,
    fact_class text NOT NULL CHECK (fact_class IN ('business_fact', 'literature_fact', 'vendor_record', 'statistical_analysis', 'algorithmic_inference', 'human_confirmed', 'user_contribution')),
    confidence numeric(5,4) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    visibility text NOT NULL DEFAULT 'restricted' CHECK (visibility IN ('public', 'campus', 'restricted', 'private')),
    license_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    review_state text NOT NULL DEFAULT 'pending' CHECK (review_state IN ('pending', 'approved', 'rejected', 'superseded')),
    model_version text,
    valid_from timestamptz NOT NULL DEFAULT '-infinity',
    valid_to timestamptz NOT NULL DEFAULT 'infinity',
    system_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    system_to timestamptz NOT NULL DEFAULT 'infinity',
    version bigint NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT relation_exactly_one_target CHECK ((object_id IS NOT NULL) <> (literal_value IS NOT NULL)),
    CONSTRAINT relation_valid_time CHECK (valid_from < valid_to),
    CONSTRAINT relation_system_time CHECK (system_from < system_to)
);

CREATE TABLE smartlib.relation_evidence (
    relation_id uuid NOT NULL REFERENCES smartlib.relation_assertion(relation_id),
    evidence_id uuid NOT NULL REFERENCES smartlib.evidence_record(evidence_id),
    added_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (relation_id, evidence_id)
);

CREATE TABLE smartlib.policy_tag (
    policy_tag_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    name text NOT NULL CHECK (btrim(name) <> ''),
    policy_kind text NOT NULL CHECK (policy_kind IN ('visibility', 'license', 'purpose', 'retention', 'export', 'model_use')),
    policy_version text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE smartlib.object_policy_tag (
    object_id uuid NOT NULL REFERENCES smartlib.knowledge_object(object_id),
    policy_tag_id uuid NOT NULL REFERENCES smartlib.policy_tag(policy_tag_id),
    assigned_by uuid NOT NULL,
    assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (object_id, policy_tag_id)
);

CREATE TABLE smartlib.async_job (
    job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type text NOT NULL CHECK (job_type ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'retry_wait')),
    progress numeric(5,4) NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    input jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(input) = 'object'),
    output jsonb CHECK (output IS NULL OR jsonb_typeof(output) = 'object'),
    failure_code text,
    failure_message text,
    requested_by uuid NOT NULL,
    trace_id text,
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT async_job_terminal_time CHECK (
        (state IN ('succeeded', 'failed', 'cancelled') AND finished_at IS NOT NULL)
        OR (state NOT IN ('succeeded', 'failed', 'cancelled'))
    )
);

CREATE TABLE smartlib.outbox_event (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type text NOT NULL,
    aggregate_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    event_version integer NOT NULL DEFAULT 1 CHECK (event_version >= 1),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    trace_id text,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error text
);

CREATE TABLE audit.audit_event (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_id uuid,
    action text NOT NULL CHECK (btrim(action) <> ''),
    resource_type text NOT NULL CHECK (btrim(resource_type) <> ''),
    resource_id text,
    decision text NOT NULL CHECK (decision IN ('allowed', 'denied', 'recorded')),
    policy_version text,
    trace_id text,
    request_id text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX knowledge_object_type_name_idx ON smartlib.knowledge_object (object_type, canonical_name);
CREATE INDEX knowledge_object_attributes_gin_idx ON smartlib.knowledge_object USING gin (attributes);
CREATE INDEX source_reference_object_idx ON smartlib.source_reference (object_id);
CREATE INDEX evidence_record_object_idx ON smartlib.evidence_record (object_id);
CREATE INDEX relation_assertion_subject_predicate_idx ON smartlib.relation_assertion (subject_id, predicate);
CREATE INDEX relation_assertion_object_idx ON smartlib.relation_assertion (object_id) WHERE object_id IS NOT NULL;
CREATE INDEX async_job_state_available_idx ON smartlib.async_job (state, available_at);
CREATE INDEX outbox_event_unpublished_idx ON smartlib.outbox_event (occurred_at) WHERE published_at IS NULL;
CREATE INDEX audit_event_actor_time_idx ON audit.audit_event (actor_id, occurred_at DESC);
CREATE INDEX audit_event_resource_idx ON audit.audit_event (resource_type, resource_id, occurred_at DESC);

CREATE TRIGGER source_system_updated_at
BEFORE UPDATE ON smartlib.source_system
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

CREATE TRIGGER knowledge_object_updated_at
BEFORE UPDATE ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

CREATE TRIGGER relation_assertion_updated_at
BEFORE UPDATE ON smartlib.relation_assertion
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

CREATE TRIGGER async_job_updated_at
BEFORE UPDATE ON smartlib.async_job
FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();

COMMENT ON TABLE smartlib.knowledge_object IS 'Canonical SmartLib knowledge objects with bitemporal boundaries';
COMMENT ON TABLE smartlib.relation_assertion IS 'Canonical facts, analyses, inferences and reviewed relations';
COMMENT ON TABLE smartlib.outbox_event IS 'Transactional events awaiting publication to derived projections';
COMMENT ON TABLE audit.audit_event IS 'Append-only security and business audit events';

RESET ROLE;
