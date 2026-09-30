SET ROLE smartlib_owner;
-- Existing change reviewers may handle only research tasks whose target object is visible.
-- No permissions are granted to a new role or anonymous caller.
CREATE POLICY research_task_reviewer_read ON smartlib.review_task FOR SELECT TO smartlib_app
USING (issue_type IN ('RESEARCH_CLASSIFICATION','RESEARCH_PROJECT')
 AND smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object k WHERE k.object_id=review_task.object_id));
CREATE POLICY research_task_reviewer_update ON smartlib.review_task FOR UPDATE TO smartlib_app
USING (issue_type IN ('RESEARCH_CLASSIFICATION','RESEARCH_PROJECT')
 AND smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object k WHERE k.object_id=review_task.object_id))
WITH CHECK (issue_type IN ('RESEARCH_CLASSIFICATION','RESEARCH_PROJECT')
 AND smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object k WHERE k.object_id=review_task.object_id));
RESET ROLE;
