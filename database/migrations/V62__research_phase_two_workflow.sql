SET ROLE smartlib_owner;
INSERT INTO smartlib.attribute_definition(entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
SELECT 'object','project','*',k,ARRAY[t],false,'经审核的项目权威资料，不从代表作推断。','research-phase2-v1'
FROM (VALUES ('official_research_summary','string'),('official_nsfc_codes','array'),('official_nsfc_version','string'),('official_research_source','string')) f(k,t)
ON CONFLICT DO NOTHING;

CREATE TRIGGER research_review_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.review_task
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('review_task_id');

CREATE FUNCTION smartlib.queue_research_classification() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND NEW.abstract IS NOT DISTINCT FROM OLD.abstract AND NEW.title IS NOT DISTINCT FROM OLD.title THEN RETURN NEW; END IF;
 INSERT INTO smartlib.review_task(issue_type,target_type,target_id,publication_id,object_id,reason_code,description,created_by)
 VALUES('RESEARCH_CLASSIFICATION','knowledge_object',NEW.publication_id,NEW.publication_id,NEW.publication_id,
 'research.new_content','新论文或内容更新，等待生成可审核分类建议',COALESCE(smartlib.current_actor_id(),NEW.created_by))
 ON CONFLICT (issue_type,target_type,target_id) WHERE state IN ('open','in_review') DO NOTHING;
 RETURN NEW;
END $$;
CREATE TRIGGER research_publication_queue AFTER INSERT OR UPDATE OF abstract,title ON smartlib.publication_metadata
FOR EACH ROW EXECUTE FUNCTION smartlib.queue_research_classification();
RESET ROLE;
