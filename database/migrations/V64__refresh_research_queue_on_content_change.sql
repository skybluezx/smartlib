SET ROLE smartlib_owner;
CREATE OR REPLACE FUNCTION smartlib.queue_research_classification() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND NEW.abstract IS NOT DISTINCT FROM OLD.abstract AND NEW.title IS NOT DISTINCT FROM OLD.title THEN RETURN NEW; END IF;
 INSERT INTO smartlib.review_task(issue_type,target_type,target_id,publication_id,object_id,reason_code,description,created_by)
 VALUES('RESEARCH_CLASSIFICATION','knowledge_object',NEW.publication_id,NEW.publication_id,NEW.publication_id,
 'research.new_content','新论文或内容更新，等待生成可审核分类建议',COALESCE(smartlib.current_actor_id(),NEW.created_by))
 ON CONFLICT (issue_type,target_type,target_id) WHERE state IN ('open','in_review')
 DO UPDATE SET machine_suggestion=CASE WHEN review_task.state='open' THEN '{}'::jsonb ELSE review_task.machine_suggestion END;
 RETURN NEW;
END $$;
RESET ROLE;
