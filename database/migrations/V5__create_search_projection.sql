DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartlib_projection') THEN
        CREATE ROLE smartlib_projection NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END
$roles$;

DO $membership$
BEGIN
    EXECUTE format('GRANT smartlib_projection TO %I WITH ADMIN OPTION', current_user);
END
$membership$;

CREATE SCHEMA smartlib_projection AUTHORIZATION smartlib_owner;

SET ROLE smartlib_owner;
REVOKE ALL ON SCHEMA smartlib_projection FROM PUBLIC;
GRANT USAGE ON SCHEMA smartlib_projection TO smartlib_app, smartlib_readonly, smartlib_projection;

COMMENT ON SCHEMA smartlib_projection IS
    'Rebuildable serving projections derived from SmartLib canonical state and Outbox events';

CREATE TABLE smartlib_projection.search_document (
    object_id uuid PRIMARY KEY,
    object_type text NOT NULL,
    canonical_name text NOT NULL,
    aliases text[] NOT NULL DEFAULT ARRAY[]::text[],
    description text,
    visibility text NOT NULL CHECK (visibility IN ('public', 'campus', 'restricted', 'private')),
    created_by uuid NOT NULL,
    policy_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    object_version bigint NOT NULL CHECK (object_version >= 1),
    policy_version text NOT NULL,
    projection_version text NOT NULL,
    source_updated_at timestamptz NOT NULL,
    projected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    search_vector tsvector NOT NULL
);

CREATE TABLE smartlib_projection.event_receipt (
    projection_name text NOT NULL CHECK (projection_name ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    event_id uuid NOT NULL REFERENCES smartlib.outbox_event(event_id),
    processed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (projection_name, event_id)
);

CREATE TABLE smartlib_projection.projection_state (
    projection_name text PRIMARY KEY CHECK (projection_name ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    last_event_id uuid REFERENCES smartlib.outbox_event(event_id),
    last_occurred_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX search_document_lexical_gin_idx
    ON smartlib_projection.search_document USING gin (search_vector);
CREATE INDEX search_document_type_name_idx
    ON smartlib_projection.search_document (object_type, canonical_name, object_id);
CREATE INDEX search_document_visibility_owner_idx
    ON smartlib_projection.search_document (visibility, created_by);
CREATE INDEX event_receipt_processed_idx
    ON smartlib_projection.event_receipt (projection_name, processed_at DESC);

ALTER TABLE smartlib_projection.search_document ENABLE ROW LEVEL SECURITY;

CREATE POLICY search_document_read ON smartlib_projection.search_document
    FOR SELECT TO smartlib_app, smartlib_readonly
    USING (visibility = 'public' OR created_by = smartlib.current_actor_id());

CREATE FUNCTION smartlib_projection.document_json(p_object_id uuid)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib_projection
AS $function$
    SELECT jsonb_build_object(
        'object_id', object_id,
        'object_type', object_type,
        'canonical_name', canonical_name,
        'aliases', aliases,
        'description', description,
        'visibility', visibility,
        'created_by', created_by,
        'policy_tags', policy_tags,
        'object_version', object_version,
        'policy_version', policy_version,
        'projection_version', projection_version,
        'source_updated_at', source_updated_at,
        'projected_at', projected_at
    )
    FROM smartlib_projection.search_document
    WHERE object_id = p_object_id
$function$;

CREATE FUNCTION smartlib_projection.refresh_postgres_search_event(p_event_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
DECLARE
    selected_event smartlib.outbox_event%ROWTYPE;
    selected_object smartlib.knowledge_object%ROWTYPE;
    selected_aliases text[];
    selected_policy_tags text[];
    selected_policy_version text;
    result_document jsonb;
BEGIN
    SELECT * INTO selected_event
    FROM smartlib.outbox_event
    WHERE event_id = p_event_id
      AND aggregate_type = 'knowledge_object';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown knowledge object event %', p_event_id USING ERRCODE = '22023';
    END IF;

    SELECT * INTO selected_object
    FROM smartlib.knowledge_object
    WHERE object_id = selected_event.aggregate_id
      AND system_to = 'infinity'::timestamptz;

    IF FOUND THEN
        SELECT COALESCE(array_agg(alias_value ORDER BY alias_value), ARRAY[]::text[])
        INTO selected_aliases
        FROM jsonb_array_elements_text(
            CASE
                WHEN jsonb_typeof(selected_object.attributes -> 'aliases') = 'array'
                    THEN selected_object.attributes -> 'aliases'
                ELSE '[]'::jsonb
            END
        ) AS alias_value;

        SELECT
            COALESCE(array_agg(tag.code ORDER BY tag.code), ARRAY[]::text[]),
            COALESCE(string_agg(tag.code || '@' || tag.policy_version, ',' ORDER BY tag.code), 'none')
        INTO selected_policy_tags, selected_policy_version
        FROM smartlib.object_policy_tag AS assignment
        JOIN smartlib.policy_tag AS tag ON tag.policy_tag_id = assignment.policy_tag_id
        WHERE assignment.object_id = selected_object.object_id;

        INSERT INTO smartlib_projection.search_document (
            object_id, object_type, canonical_name, aliases, description, visibility,
            created_by, policy_tags, object_version, policy_version, projection_version,
            source_updated_at, projected_at, search_vector
        ) VALUES (
            selected_object.object_id,
            selected_object.object_type,
            selected_object.canonical_name,
            selected_aliases,
            selected_object.description,
            selected_object.visibility,
            selected_object.created_by,
            selected_policy_tags,
            selected_object.version,
            selected_policy_version,
            'search-document-v1',
            selected_object.updated_at,
            clock_timestamp(),
            setweight(to_tsvector('simple', selected_object.canonical_name), 'A') ||
            setweight(to_tsvector('simple', array_to_string(selected_aliases, ' ')), 'A') ||
            setweight(to_tsvector('simple', COALESCE(selected_object.description, '')), 'B')
        )
        ON CONFLICT (object_id) DO UPDATE SET
            object_type = EXCLUDED.object_type,
            canonical_name = EXCLUDED.canonical_name,
            aliases = EXCLUDED.aliases,
            description = EXCLUDED.description,
            visibility = EXCLUDED.visibility,
            created_by = EXCLUDED.created_by,
            policy_tags = EXCLUDED.policy_tags,
            object_version = EXCLUDED.object_version,
            policy_version = EXCLUDED.policy_version,
            projection_version = EXCLUDED.projection_version,
            source_updated_at = EXCLUDED.source_updated_at,
            projected_at = EXCLUDED.projected_at,
            search_vector = EXCLUDED.search_vector
        WHERE smartlib_projection.search_document.object_version <= EXCLUDED.object_version;

        SELECT smartlib_projection.document_json(selected_object.object_id) INTO result_document;
    ELSE
        DELETE FROM smartlib_projection.search_document
        WHERE object_id = selected_event.aggregate_id;
        result_document = jsonb_build_object(
            'operation', 'delete',
            'object_id', selected_event.aggregate_id,
            'projection_version', 'search-document-v1'
        );
    END IF;

    INSERT INTO smartlib_projection.event_receipt (projection_name, event_id)
    VALUES ('postgres_search', p_event_id)
    ON CONFLICT DO NOTHING;

    INSERT INTO smartlib_projection.projection_state (
        projection_name, last_event_id, last_occurred_at
    ) VALUES (
        'postgres_search', selected_event.event_id, selected_event.occurred_at
    )
    ON CONFLICT (projection_name) DO UPDATE SET
        last_event_id = CASE
            WHEN smartlib_projection.projection_state.last_occurred_at IS NULL
              OR EXCLUDED.last_occurred_at >= smartlib_projection.projection_state.last_occurred_at
            THEN EXCLUDED.last_event_id
            ELSE smartlib_projection.projection_state.last_event_id
        END,
        last_occurred_at = GREATEST(
            smartlib_projection.projection_state.last_occurred_at,
            EXCLUDED.last_occurred_at
        ),
        updated_at = clock_timestamp();

    RETURN jsonb_build_object(
        'operation', CASE WHEN result_document ? 'operation' THEN 'delete' ELSE 'upsert' END,
        'event_id', selected_event.event_id,
        'object_id', selected_event.aggregate_id,
        'document', CASE WHEN result_document ? 'operation' THEN NULL ELSE result_document END
    );
END
$function$;

CREATE FUNCTION smartlib_projection.pending_search_events(
    p_projection_name text,
    p_limit integer DEFAULT 100
)
RETURNS TABLE(event_id uuid, event_type text, object_id uuid, occurred_at timestamptz)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
    SELECT event.event_id, event.event_type, event.aggregate_id, event.occurred_at
    FROM smartlib.outbox_event AS event
    WHERE event.aggregate_type = 'knowledge_object'
      AND NOT EXISTS (
          SELECT 1
          FROM smartlib_projection.event_receipt AS receipt
          WHERE receipt.projection_name = p_projection_name
            AND receipt.event_id = event.event_id
      )
    ORDER BY event.occurred_at, event.event_id
    LIMIT LEAST(GREATEST(p_limit, 1), 1000)
$function$;

CREATE FUNCTION smartlib_projection.acknowledge_search_event(
    p_projection_name text,
    p_event_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
DECLARE
    selected_event smartlib.outbox_event%ROWTYPE;
BEGIN
    IF p_projection_name NOT IN ('opensearch_search') THEN
        RAISE EXCEPTION 'unsupported external projection %', p_projection_name USING ERRCODE = '22023';
    END IF;

    SELECT * INTO STRICT selected_event
    FROM smartlib.outbox_event
    WHERE event_id = p_event_id
      AND aggregate_type = 'knowledge_object';

    INSERT INTO smartlib_projection.event_receipt (projection_name, event_id)
    VALUES (p_projection_name, p_event_id)
    ON CONFLICT DO NOTHING;

    INSERT INTO smartlib_projection.projection_state (
        projection_name, last_event_id, last_occurred_at
    ) VALUES (
        p_projection_name, selected_event.event_id, selected_event.occurred_at
    )
    ON CONFLICT (projection_name) DO UPDATE SET
        last_event_id = CASE
            WHEN smartlib_projection.projection_state.last_occurred_at IS NULL
              OR EXCLUDED.last_occurred_at >= smartlib_projection.projection_state.last_occurred_at
            THEN EXCLUDED.last_event_id
            ELSE smartlib_projection.projection_state.last_event_id
        END,
        last_occurred_at = GREATEST(
            smartlib_projection.projection_state.last_occurred_at,
            EXCLUDED.last_occurred_at
        ),
        updated_at = clock_timestamp();
END
$function$;

REVOKE ALL ON ALL TABLES IN SCHEMA smartlib_projection FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA smartlib_projection FROM PUBLIC;

GRANT SELECT ON smartlib_projection.search_document TO smartlib_app, smartlib_readonly;
GRANT EXECUTE ON FUNCTION smartlib_projection.document_json(uuid) TO smartlib_projection;
GRANT EXECUTE ON FUNCTION smartlib_projection.refresh_postgres_search_event(uuid) TO smartlib_projection;
GRANT EXECUTE ON FUNCTION smartlib_projection.pending_search_events(text, integer) TO smartlib_projection;
GRANT EXECUTE ON FUNCTION smartlib_projection.acknowledge_search_event(text, uuid) TO smartlib_projection;

COMMENT ON TABLE smartlib_projection.search_document IS
    'Product-neutral, rebuildable search projection; not an authoritative knowledge store';
COMMENT ON TABLE smartlib_projection.event_receipt IS
    'Idempotency receipts for independently rebuildable projection consumers';
COMMENT ON FUNCTION smartlib_projection.refresh_postgres_search_event(uuid) IS
    'Refresh one PostgreSQL search projection document from an authoritative Outbox event';

RESET ROLE;
