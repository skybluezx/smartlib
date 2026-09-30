SET ROLE smartlib_owner;

CREATE FUNCTION smartlib_projection.pending_event_count(
    p_search_projection_name text,
    p_graph_projection_name text
)
RETURNS bigint
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
    SELECT count(*)
    FROM smartlib.outbox_event AS event
    WHERE (
        event.aggregate_type = 'knowledge_object'
        AND NOT EXISTS (
            SELECT 1
            FROM smartlib_projection.event_receipt AS receipt
            WHERE receipt.projection_name = p_search_projection_name
              AND receipt.event_id = event.event_id
        )
    ) OR (
        event.aggregate_type IN ('knowledge_object', 'relation_assertion')
        AND NOT EXISTS (
            SELECT 1
            FROM smartlib_projection.event_receipt AS receipt
            WHERE receipt.projection_name = p_graph_projection_name
              AND receipt.event_id = event.event_id
        )
    )
$function$;

REVOKE ALL ON FUNCTION smartlib_projection.pending_event_count(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib_projection.pending_event_count(text, text) TO smartlib_api;

COMMENT ON FUNCTION smartlib_projection.pending_event_count(text, text) IS
    'Count outbox events still missing a receipt from either active search or graph projection';

RESET ROLE;
