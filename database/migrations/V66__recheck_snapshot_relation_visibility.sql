SET ROLE smartlib_owner;
DROP POLICY saved_analysis_read ON smartlib.saved_analysis;
CREATE POLICY saved_analysis_read ON smartlib.saved_analysis
FOR SELECT TO smartlib_app,smartlib_readonly USING (
    created_by=smartlib.current_actor_id()
    AND NOT EXISTS (SELECT 1 FROM unnest(object_ids) AS required(id)
        WHERE NOT EXISTS (SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=required.id))
    AND NOT EXISTS (SELECT 1 FROM unnest(metric_release_ids) AS required(id)
        WHERE NOT EXISTS (SELECT 1 FROM smartlib.publication_metric_release r
                          WHERE r.release_id=required.id))
    AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(coalesce(provenance->'relation_versions','[]'::jsonb)) item
        WHERE NOT EXISTS (SELECT 1 FROM smartlib.relation_assertion r
                          WHERE r.relation_id=(item->>'relation_id')::uuid)
    )
);
RESET ROLE;
