SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

CREATE OR REPLACE FUNCTION smartlib.request_search_projection_rebuild(p_trace_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
DECLARE
    selected_object_count bigint;
    selected_stale_count bigint;
    selected_event_count bigint;
BEGIN
    IF p_trace_id IS NULL OR btrim(p_trace_id)='' THEN
        RAISE EXCEPTION 'trace id is required' USING ERRCODE='22023';
    END IF;
    IF EXISTS (SELECT 1 FROM smartlib.outbox_event WHERE trace_id=p_trace_id) THEN
        RAISE EXCEPTION 'trace id has already been used: %',p_trace_id USING ERRCODE='23505';
    END IF;

    SELECT count(*) INTO selected_object_count FROM smartlib.knowledge_object;
    SELECT count(*) INTO selected_stale_count
      FROM smartlib_projection.search_document document
     WHERE NOT EXISTS (
         SELECT 1 FROM smartlib.knowledge_object object
          WHERE object.object_id=document.object_id
     );

    INSERT INTO smartlib.outbox_event
        (aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
    SELECT 'knowledge_object',object_id,'knowledge.object.rebuild',version,
           jsonb_build_object('object_id',object_id,'version',version),p_trace_id
      FROM smartlib.knowledge_object
    UNION ALL
    SELECT 'knowledge_object',document.object_id,'knowledge.object.rebuild_delete',
           document.object_version,
           jsonb_build_object('object_id',document.object_id,'version',document.object_version),p_trace_id
      FROM smartlib_projection.search_document document
     WHERE NOT EXISTS (
         SELECT 1 FROM smartlib.knowledge_object object
          WHERE object.object_id=document.object_id
     );
    GET DIAGNOSTICS selected_event_count = ROW_COUNT;

    RETURN jsonb_build_object(
        'trace_id',p_trace_id,
        'authoritative_objects',selected_object_count,
        'stale_documents',selected_stale_count,
        'events_enqueued',selected_event_count
    );
END
$function$;

CREATE OR REPLACE FUNCTION smartlib.search_projection_rebuild_state()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
    SELECT jsonb_build_object(
        'authoritative_objects',(SELECT count(*) FROM smartlib.knowledge_object),
        'projection_documents',(SELECT count(*) FROM smartlib_projection.search_document),
        'stale_documents',(
            SELECT count(*) FROM smartlib_projection.search_document document
             WHERE NOT EXISTS (
                 SELECT 1 FROM smartlib.knowledge_object object
                  WHERE object.object_id=document.object_id
             )
        )
    )
$function$;

REVOKE ALL ON FUNCTION smartlib.request_search_projection_rebuild(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION smartlib.search_projection_rebuild_state() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.request_search_projection_rebuild(text)
    TO smartlib_app,smartlib_owner;
GRANT EXECUTE ON FUNCTION smartlib.search_projection_rebuild_state()
    TO smartlib_app,smartlib_owner,smartlib_readonly;

COMMENT ON FUNCTION smartlib.request_search_projection_rebuild(text) IS
    'Enqueue a complete rebuild from PostgreSQL authority plus deletion events for stale search documents.';
COMMENT ON FUNCTION smartlib.search_projection_rebuild_state() IS
    'RLS-independent aggregate state used to validate a complete search projection rebuild.';

RESET ROLE;
