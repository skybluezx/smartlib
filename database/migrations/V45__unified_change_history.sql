SET ROLE smartlib_owner;
-- Additive provenance only: no existing business rows or historical snapshots are rewritten.
CREATE TABLE smartlib.change_event (
 change_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 transaction_id bigint NOT NULL UNIQUE DEFAULT txid_current(),
 actor_id uuid, reason text, source_label text, trace_id text,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER change_event_append_only BEFORE UPDATE OR DELETE ON smartlib.change_event
 FOR EACH ROW EXECUTE FUNCTION smartlib.enforce_publication_revision_history();
ALTER TABLE smartlib.entity_revision ADD COLUMN change_id uuid REFERENCES smartlib.change_event(change_id);
ALTER TABLE smartlib.entity_revision ADD COLUMN submission_id uuid;
CREATE INDEX entity_revision_change_idx ON smartlib.entity_revision(change_id);
CREATE OR REPLACE FUNCTION smartlib.capture_entity_revision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE b jsonb; a jsonb; k uuid; change uuid;
BEGIN
 IF TG_OP<>'INSERT' THEN b=to_jsonb(OLD); END IF;
 IF TG_OP<>'DELETE' THEN a=to_jsonb(NEW); END IF;
 k=(COALESCE(a,b)->>TG_ARGV[0])::uuid;
 SELECT change_id INTO change FROM smartlib.change_event WHERE transaction_id=txid_current();
 IF change IS NULL THEN
  INSERT INTO smartlib.change_event(actor_id,reason,source_label,trace_id)
  VALUES(smartlib.current_actor_id(),nullif(current_setting('smartlib.change_reason',true),''),
   nullif(current_setting('smartlib.change_source',true),''),nullif(current_setting('smartlib.trace_id',true),''))
  RETURNING change_id INTO change;
 END IF;
 INSERT INTO smartlib.entity_revision(entity_table,entity_id,operation,before_value,after_value,actor_id,change_id,submission_id)
 VALUES(TG_TABLE_NAME,k,TG_OP,b,a,smartlib.current_actor_id(),change,
  nullif(current_setting('smartlib.submission_id',true),'')::uuid);
 RETURN COALESCE(NEW,OLD);
END $$;
CREATE TRIGGER source_reference_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.source_reference
 FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('source_reference_id');
CREATE TRIGGER source_system_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.source_system
 FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('source_system_id');
-- The complete composite key remains in both snapshots; entity_id groups links by relation.
CREATE TRIGGER relation_evidence_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.relation_evidence
 FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('relation_id');
CREATE TRIGGER fulltext_resource_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.publication_fulltext_resource
 FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('fulltext_resource_id');
REVOKE ALL ON smartlib.change_event FROM PUBLIC,smartlib_app,smartlib_readonly;

-- History contains previously removed data; reviewers only, with current AND historical visibility checks.
CREATE FUNCTION smartlib.read_object_history(target uuid, take integer DEFAULT 50, skip integer DEFAULT 0, selected_revision uuid DEFAULT NULL)
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
 WHERE (selected_revision IS NULL OR r.revision_id=selected_revision) AND (
  (r.entity_table='knowledge_object' AND r.entity_id=target)
  OR (r.entity_table IN ('organization_profile','person_profile','organization_name_variant',
    'person_name_variant','organization_identifier','person_identifier','source_reference','evidence_record')
    AND (r.before_value->>'object_id'=target::text OR r.after_value->>'object_id'=target::text))
  OR (r.entity_table IN ('publication_metadata','publication_authorship','publication_fulltext_resource')
    AND (r.before_value->>'publication_id'=target::text OR r.after_value->>'publication_id'=target::text))
  OR (r.entity_table='relation_assertion' AND EXISTS(SELECT 1 FROM jsonb_each_text(
    jsonb_build_object('s',COALESCE(r.after_value,r.before_value)->>'subject_id',
    'o',COALESCE(r.after_value,r.before_value)->>'object_id',
    'p',COALESCE(r.after_value,r.before_value)->>'context_object_id')) x WHERE x.value=target::text))
  OR (r.entity_table IN ('relation_evidence','publication_relation_provenance') AND EXISTS(
    SELECT 1 FROM smartlib.relation_assertion ra WHERE ra.relation_id=r.entity_id
    AND target IN (ra.subject_id,ra.object_id,ra.context_object_id)
    AND (ra.created_by=actor OR ra.visibility='public')))
 )
 AND (r.before_value IS NULL OR NOT r.before_value ? 'visibility' OR r.before_value->>'visibility'='public' OR r.before_value->>'created_by'=actor::text)
 AND (r.after_value IS NULL OR NOT r.after_value ? 'visibility' OR r.after_value->>'visibility'='public' OR r.after_value->>'created_by'=actor::text)
 ORDER BY r.recorded_at DESC,r.revision_id DESC LIMIT least(greatest(take,1),200) OFFSET greatest(skip,0);
END $$;
REVOKE ALL ON FUNCTION smartlib.read_object_history(uuid,integer,integer,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.read_object_history(uuid,integer,integer,uuid) TO smartlib_app,smartlib_readonly;
RESET ROLE;
