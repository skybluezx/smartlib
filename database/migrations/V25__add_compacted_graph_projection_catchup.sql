SET ROLE smartlib_owner;

CREATE FUNCTION smartlib_projection.pending_graph_event_groups(
    p_projection_name text,
    p_limit integer DEFAULT 600
)
RETURNS TABLE(aggregate_type text, aggregate_id uuid, event_ids uuid[])
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
    WITH pending AS (
        SELECT event.event_id,event.aggregate_type,event.aggregate_id,event.occurred_at
          FROM smartlib.outbox_event event
         WHERE event.aggregate_type IN ('knowledge_object','relation_assertion')
           AND NOT EXISTS (
               SELECT 1 FROM smartlib_projection.event_receipt receipt
                WHERE receipt.projection_name=p_projection_name
                  AND receipt.event_id=event.event_id)
    ), selected AS (
        SELECT pending.aggregate_type,pending.aggregate_id,max(pending.occurred_at) AS latest
          FROM pending
         GROUP BY pending.aggregate_type,pending.aggregate_id
         ORDER BY max(pending.occurred_at),pending.aggregate_type,pending.aggregate_id
         LIMIT LEAST(GREATEST(p_limit,1),1000)
    )
    SELECT selected.aggregate_type,selected.aggregate_id,
           array_agg(pending.event_id ORDER BY pending.occurred_at DESC)
      FROM selected JOIN pending USING(aggregate_type,aggregate_id)
     GROUP BY selected.aggregate_type,selected.aggregate_id,selected.latest
     ORDER BY selected.latest,selected.aggregate_type,selected.aggregate_id
$function$;

CREATE FUNCTION smartlib_projection.acknowledge_graph_events(
    p_projection_name text,
    p_event_ids uuid[]
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
DECLARE
    selected_event_id uuid;
BEGIN
    FOREACH selected_event_id IN ARRAY p_event_ids LOOP
        PERFORM smartlib_projection.acknowledge_graph_event(
            p_projection_name, selected_event_id
        );
    END LOOP;
END
$function$;

REVOKE ALL ON FUNCTION smartlib_projection.pending_graph_event_groups(text,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION smartlib_projection.acknowledge_graph_events(text,uuid[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib_projection.pending_graph_event_groups(text,integer)
    TO smartlib_projection;
GRANT EXECUTE ON FUNCTION smartlib_projection.acknowledge_graph_events(text,uuid[])
    TO smartlib_projection;

COMMENT ON FUNCTION smartlib_projection.pending_graph_event_groups(text,integer) IS
    'Groups pending events by aggregate so controlled catch-up writes each current graph state once.';

RESET ROLE;
