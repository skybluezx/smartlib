SET ROLE smartlib_owner;

CREATE OR REPLACE FUNCTION smartlib_projection.acknowledge_graph_event(
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
    IF p_projection_name <> 'hugegraph_graph' THEN
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

COMMENT ON FUNCTION smartlib_projection.graph_delivery_json(uuid) IS
    'Build a product-neutral graph projection delivery from canonical objects and relations';

COMMENT ON FUNCTION smartlib_projection.graph_relation_json(uuid) IS
    'Build a graph-safe relation projection with aligned scalar evidence access arrays';

COMMENT ON FUNCTION smartlib_projection.acknowledge_graph_event(text, uuid) IS
    'Acknowledge delivery only for the active HugeGraph projection';

RESET ROLE;
