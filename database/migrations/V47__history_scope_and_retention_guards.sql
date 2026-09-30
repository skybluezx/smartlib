SET ROLE smartlib_owner;
DROP FUNCTION smartlib.read_object_history(uuid,integer,integer,uuid);
CREATE FUNCTION smartlib.read_object_history(target uuid, take integer DEFAULT 50, skip integer DEFAULT 0, selected_revision uuid DEFAULT NULL, entity_filter text DEFAULT NULL)
RETURNS SETOF jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE actor uuid:=smartlib.current_actor_id();
BEGIN
 IF NOT smartlib.actor_has_permission(actor,'change.decide') THEN
  RAISE EXCEPTION 'History requires review permission' USING ERRCODE='42501';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM smartlib.knowledge_object WHERE object_id=target
   AND (created_by=actor OR visibility='public')) THEN
  RAISE EXCEPTION 'History target unavailable' USING ERRCODE='42501';
 END IF;
 RETURN QUERY
 SELECT to_jsonb(r) || jsonb_build_object('change_context',to_jsonb(c))
 FROM smartlib.entity_revision r LEFT JOIN smartlib.change_event c USING(change_id)
 WHERE (entity_filter IS NULL OR r.entity_table=entity_filter) AND (selected_revision IS NULL OR r.revision_id=selected_revision) AND (
  (r.entity_table='knowledge_object' AND r.entity_id=target)
  OR (r.entity_table IN ('organization_profile','person_profile','organization_name_variant',
    'person_name_variant','organization_identifier','person_identifier','source_reference','evidence_record')
    AND (r.before_value->>'object_id'=target::text OR r.after_value->>'object_id'=target::text))
  OR (r.entity_table IN ('publication_metadata','publication_authorship','publication_fulltext_resource')
    AND (r.before_value->>'publication_id'=target::text OR r.after_value->>'publication_id'=target::text))
  OR (r.entity_table='relation_assertion' AND EXISTS(SELECT 1 FROM jsonb_each_text(
    jsonb_build_object('s',COALESCE(r.after_value,r.before_value)->>'subject_id',
    'o',COALESCE(r.after_value,r.before_value)->>'object_id',
    'p',COALESCE(r.after_value,r.before_value)->>'context_object_id',
    'old_s',r.before_value->>'subject_id','old_o',r.before_value->>'object_id','old_p',r.before_value->>'context_object_id')) x WHERE x.value=target::text))
  OR (r.entity_table IN ('relation_evidence','publication_relation_provenance') AND EXISTS(
    SELECT 1 FROM smartlib.relation_assertion ra WHERE ra.relation_id=r.entity_id
    AND target IN (ra.subject_id,ra.object_id,ra.context_object_id)
    AND (ra.created_by=actor OR ra.visibility='public')))
 )
 AND (r.before_value IS NULL OR NOT r.before_value ? 'visibility' OR r.before_value->>'visibility'='public' OR r.before_value->>'created_by'=actor::text)
 AND (r.after_value IS NULL OR NOT r.after_value ? 'visibility' OR r.after_value->>'visibility'='public' OR r.after_value->>'created_by'=actor::text)
 ORDER BY r.recorded_at DESC,r.revision_id DESC LIMIT least(greatest(take,1),200) OFFSET greatest(skip,0);
END $$;
REVOKE ALL ON FUNCTION smartlib.read_object_history(uuid,integer,integer,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.read_object_history(uuid,integer,integer,uuid,text) TO smartlib_app,smartlib_readonly;

CREATE TRIGGER entity_revision_no_truncate BEFORE TRUNCATE ON smartlib.entity_revision FOR EACH STATEMENT EXECUTE FUNCTION smartlib.enforce_publication_revision_history();
CREATE TRIGGER change_event_no_truncate BEFORE TRUNCATE ON smartlib.change_event FOR EACH STATEMENT EXECUTE FUNCTION smartlib.enforce_publication_revision_history();
CREATE TRIGGER audit_event_no_truncate BEFORE TRUNCATE ON audit.audit_event FOR EACH STATEMENT EXECUTE FUNCTION audit.reject_audit_mutation();
RESET ROLE;

