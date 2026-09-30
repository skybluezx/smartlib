SET ROLE smartlib_owner;

DROP POLICY relation_evidence_read ON smartlib.relation_evidence;
DROP POLICY relation_evidence_write ON smartlib.relation_evidence;

CREATE POLICY relation_evidence_read ON smartlib.relation_evidence
    FOR SELECT TO smartlib_app, smartlib_readonly
    USING (
        EXISTS (
            SELECT 1 FROM smartlib.relation_assertion AS relation
            WHERE relation.relation_id = relation_evidence.relation_id
        )
        AND EXISTS (
            SELECT 1 FROM smartlib.evidence_record AS evidence
            WHERE evidence.evidence_id = relation_evidence.evidence_id
        )
    );

CREATE POLICY relation_evidence_write ON smartlib.relation_evidence
    FOR ALL TO smartlib_app
    USING (
        EXISTS (
            SELECT 1 FROM smartlib.relation_assertion AS relation
            WHERE relation.relation_id = relation_evidence.relation_id
              AND relation.created_by = smartlib.current_actor_id()
        )
        AND EXISTS (
            SELECT 1 FROM smartlib.evidence_record AS evidence
            WHERE evidence.evidence_id = relation_evidence.evidence_id
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM smartlib.relation_assertion AS relation
            WHERE relation.relation_id = relation_evidence.relation_id
              AND relation.created_by = smartlib.current_actor_id()
        )
        AND EXISTS (
            SELECT 1 FROM smartlib.evidence_record AS evidence
            WHERE evidence.evidence_id = relation_evidence.evidence_id
        )
    );

CREATE FUNCTION smartlib_projection.graph_node_json(p_object_id uuid)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
    SELECT jsonb_build_object(
        'object_id', object_id,
        'object_type', object_type,
        'canonical_name', canonical_name,
        'description', description,
        'visibility', visibility,
        'created_by', created_by,
        'object_version', version,
        'projection_version', 'graph-projection-v1'
    )
    FROM smartlib.knowledge_object
    WHERE object_id = p_object_id
      AND system_to = 'infinity'::timestamptz
$function$;

CREATE FUNCTION smartlib_projection.graph_relation_json(p_relation_id uuid)
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
        'predicate', relation.predicate,
        'fact_class', relation.fact_class,
        'confidence', relation.confidence,
        'review_state', relation.review_state,
        'visibility', relation.visibility,
        'created_by', relation.created_by,
        'relation_version', relation.version,
        'projection_version', 'graph-projection-v1',
        'evidence_refs', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'evidence_id', evidence.evidence_id,
                'visibility', evidence.visibility,
                'created_by', evidence.created_by
            ) ORDER BY evidence.evidence_id)
            FROM smartlib.relation_evidence AS link
            JOIN smartlib.evidence_record AS evidence ON evidence.evidence_id = link.evidence_id
            WHERE link.relation_id = relation.relation_id
        ), '[]'::jsonb)
    )
    FROM smartlib.relation_assertion AS relation
    WHERE relation.relation_id = p_relation_id
      AND relation.object_id IS NOT NULL
      AND relation.review_state IN ('pending', 'approved')
      AND relation.system_to = 'infinity'::timestamptz
$function$;

CREATE FUNCTION smartlib_projection.graph_delivery_json(p_event_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
DECLARE
    selected_event smartlib.outbox_event%ROWTYPE;
    node_document jsonb;
    relation_document jsonb;
    subject_document jsonb;
    object_document jsonb;
BEGIN
    SELECT * INTO STRICT selected_event FROM smartlib.outbox_event WHERE event_id = p_event_id;
    IF selected_event.aggregate_type = 'knowledge_object' THEN
        SELECT smartlib_projection.graph_node_json(selected_event.aggregate_id) INTO node_document;
        RETURN jsonb_build_object(
            'operation', CASE WHEN node_document IS NULL THEN 'delete' ELSE 'upsert' END,
            'entity_kind', 'node',
            'event_id', selected_event.event_id,
            'object_id', selected_event.aggregate_id,
            'document', node_document
        );
    ELSIF selected_event.aggregate_type = 'relation_assertion' THEN
        SELECT smartlib_projection.graph_relation_json(selected_event.aggregate_id)
        INTO relation_document;
        IF relation_document IS NULL THEN
            RETURN jsonb_build_object(
                'operation', 'delete', 'entity_kind', 'relation',
                'event_id', selected_event.event_id,
                'relation_id', selected_event.aggregate_id
            );
        END IF;
        SELECT smartlib_projection.graph_node_json((relation_document ->> 'subject_id')::uuid)
        INTO subject_document;
        SELECT smartlib_projection.graph_node_json((relation_document ->> 'object_id')::uuid)
        INTO object_document;
        IF subject_document IS NULL OR object_document IS NULL THEN
            RAISE EXCEPTION 'relation % has unavailable endpoint', selected_event.aggregate_id;
        END IF;
        RETURN jsonb_build_object(
            'operation', 'upsert', 'entity_kind', 'relation',
            'event_id', selected_event.event_id,
            'relation_id', selected_event.aggregate_id,
            'nodes', jsonb_build_array(subject_document, object_document),
            'document', relation_document
        );
    END IF;
    RAISE EXCEPTION 'unsupported graph event aggregate %', selected_event.aggregate_type
        USING ERRCODE = '22023';
END
$function$;

CREATE FUNCTION smartlib_projection.pending_graph_events(
    p_projection_name text,
    p_limit integer DEFAULT 100
)
RETURNS TABLE(event_id uuid, event_type text, aggregate_type text, aggregate_id uuid,
              occurred_at timestamptz)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
    SELECT event.event_id, event.event_type, event.aggregate_type, event.aggregate_id,
           event.occurred_at
    FROM smartlib.outbox_event AS event
    WHERE event.aggregate_type IN ('knowledge_object', 'relation_assertion')
      AND NOT EXISTS (
          SELECT 1 FROM smartlib_projection.event_receipt AS receipt
          WHERE receipt.projection_name = p_projection_name
            AND receipt.event_id = event.event_id
      )
    ORDER BY event.occurred_at, event.event_id
    LIMIT LEAST(GREATEST(p_limit, 1), 1000)
$function$;

CREATE FUNCTION smartlib_projection.acknowledge_graph_event(
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
    IF p_projection_name <> 'neo4j_graph' THEN
        RAISE EXCEPTION 'unsupported graph projection %', p_projection_name USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT selected_event
    FROM smartlib.outbox_event
    WHERE event_id = p_event_id
      AND aggregate_type IN ('knowledge_object', 'relation_assertion');
    INSERT INTO smartlib_projection.event_receipt (projection_name, event_id)
    VALUES (p_projection_name, p_event_id)
    ON CONFLICT DO NOTHING;
    INSERT INTO smartlib_projection.projection_state (
        projection_name, last_event_id, last_occurred_at
    ) VALUES (p_projection_name, selected_event.event_id, selected_event.occurred_at)
    ON CONFLICT (projection_name) DO UPDATE SET
        last_event_id = CASE
            WHEN smartlib_projection.projection_state.last_occurred_at IS NULL
              OR EXCLUDED.last_occurred_at >= smartlib_projection.projection_state.last_occurred_at
            THEN EXCLUDED.last_event_id ELSE smartlib_projection.projection_state.last_event_id END,
        last_occurred_at = GREATEST(
            smartlib_projection.projection_state.last_occurred_at, EXCLUDED.last_occurred_at),
        updated_at = clock_timestamp();
END
$function$;

REVOKE ALL ON FUNCTION smartlib_projection.graph_node_json(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION smartlib_projection.graph_relation_json(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION smartlib_projection.graph_delivery_json(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION smartlib_projection.pending_graph_events(text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION smartlib_projection.acknowledge_graph_event(text, uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION smartlib_projection.graph_node_json(uuid) TO smartlib_projection;
GRANT EXECUTE ON FUNCTION smartlib_projection.graph_relation_json(uuid) TO smartlib_projection;
GRANT EXECUTE ON FUNCTION smartlib_projection.graph_delivery_json(uuid) TO smartlib_projection;
GRANT EXECUTE ON FUNCTION smartlib_projection.pending_graph_events(text, integer) TO smartlib_projection;
GRANT EXECUTE ON FUNCTION smartlib_projection.acknowledge_graph_event(text, uuid) TO smartlib_projection;

COMMENT ON FUNCTION smartlib_projection.graph_delivery_json(uuid) IS
    'Build a product-neutral Neo4j projection delivery from canonical objects and relations';

RESET ROLE;
