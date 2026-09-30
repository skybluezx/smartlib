SET ROLE smartlib_owner;
ALTER TABLE smartlib.publication_supplement RENAME TO change_submission;
ALTER TABLE smartlib.change_submission RENAME COLUMN supplement_id TO submission_id;
ALTER TABLE smartlib.change_submission RENAME COLUMN publication_id TO context_object_id;
ALTER TABLE smartlib.change_submission RENAME COLUMN base_metadata_version TO base_version;
ALTER TABLE smartlib.change_submission RENAME COLUMN target_metadata_version TO applied_version;
ALTER TABLE smartlib.change_submission ADD COLUMN workflow_key text NOT NULL DEFAULT 'publication';
ALTER TABLE smartlib.change_submission DROP CONSTRAINT publication_supplement_source_kind_check;
ALTER TABLE smartlib.change_submission ADD CONSTRAINT change_source_kind_check
 CHECK(source_kind IN ('metadata','fulltext','funding','lifecycle','identifier','manual','api','file','connector'));
ALTER TABLE smartlib.publication_change_candidate RENAME TO change_proposal;
ALTER TABLE smartlib.change_proposal RENAME COLUMN candidate_id TO proposal_id;
ALTER TABLE smartlib.change_proposal RENAME COLUMN supplement_id TO submission_id;
ALTER TABLE smartlib.change_proposal DROP CONSTRAINT publication_change_candidate_supplement_id_field_path_key;
ALTER TABLE smartlib.change_proposal ADD COLUMN target_object_id uuid REFERENCES smartlib.knowledge_object(object_id);
ALTER TABLE smartlib.change_proposal ADD COLUMN target_relation_id uuid REFERENCES smartlib.relation_assertion(relation_id);
ALTER TABLE smartlib.change_proposal ADD COLUMN base_version bigint;
ALTER TABLE smartlib.change_proposal ADD COLUMN application_state text NOT NULL DEFAULT 'pending'
 CHECK(application_state IN ('pending','applied','not_applicable','conflict'));
ALTER TABLE smartlib.change_proposal ADD COLUMN applied_at timestamptz;
ALTER TABLE smartlib.change_proposal DISABLE TRIGGER publication_change_candidate_updated_at;
UPDATE smartlib.change_proposal p SET target_object_id=s.context_object_id,base_version=s.base_version,
 application_state=CASE WHEN p.status IN ('auto_applied','accepted') THEN 'applied'
 WHEN p.status='rejected' THEN 'not_applicable' ELSE 'pending' END,
 applied_at=CASE WHEN p.status IN ('auto_applied','accepted') THEN COALESCE(p.decided_at,p.updated_at) END
FROM smartlib.change_submission s WHERE s.submission_id=p.submission_id;
ALTER TABLE smartlib.change_proposal ENABLE TRIGGER publication_change_candidate_updated_at;
ALTER TABLE smartlib.change_proposal ADD CONSTRAINT change_target_check CHECK(num_nonnulls(target_object_id,target_relation_id)=1);
ALTER TABLE smartlib.change_proposal ADD CONSTRAINT change_base_version_check CHECK(base_version>=1);
ALTER TABLE smartlib.change_proposal ALTER COLUMN base_version SET NOT NULL;
CREATE UNIQUE INDEX change_proposal_object_field ON smartlib.change_proposal(submission_id,target_object_id,field_path)
 WHERE target_object_id IS NOT NULL;
CREATE UNIQUE INDEX change_proposal_relation_field ON smartlib.change_proposal(submission_id,target_relation_id,field_path)
 WHERE target_relation_id IS NOT NULL;
ALTER TABLE smartlib.publication_fulltext_resource RENAME COLUMN supplement_id TO submission_id;
ALTER TABLE smartlib.publication_metadata_revision RENAME COLUMN supplement_id TO submission_id;
-- Populate publication proposal targets at the domain boundary; generic writers provide explicit targets.
CREATE FUNCTION smartlib.initialize_change_proposal() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,smartlib AS $$
DECLARE s smartlib.change_submission%ROWTYPE;
BEGIN
 SELECT * INTO STRICT s FROM smartlib.change_submission WHERE submission_id=NEW.submission_id;
 IF s.workflow_key='publication' THEN
  NEW.target_object_id:=s.context_object_id;
  NEW.base_version:=COALESCE(NEW.base_version,s.applied_version,s.base_version);
 END IF;
 IF s.workflow_key='publication' AND NEW.status IN ('accepted','auto_applied') THEN
  NEW.application_state:='applied'; NEW.applied_at:=COALESCE(NEW.applied_at,clock_timestamp());
 ELSIF NEW.status='rejected' THEN NEW.application_state:='not_applicable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER initialize_change_proposal BEFORE INSERT OR UPDATE OF status ON smartlib.change_proposal
FOR EACH ROW EXECUTE FUNCTION smartlib.initialize_change_proposal();
CREATE TRIGGER change_submission_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.change_submission
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('submission_id');
CREATE TRIGGER change_proposal_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.change_proposal
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('proposal_id');
-- Existing domain permissions remain domain permissions; general changes receive their own grants.
INSERT INTO smartlib.access_permission(permission_id,code,name,risk_level)
VALUES(gen_random_uuid(),'change.submit','提交对象变更','normal'),
      (gen_random_uuid(),'change.decide','审核并应用对象变更','high');
INSERT INTO smartlib.access_role_permission(role_id,permission_id)
SELECT DISTINCT rp.role_id,n.permission_id FROM smartlib.access_role_permission rp
JOIN smartlib.access_permission old ON old.permission_id=rp.permission_id
JOIN smartlib.access_permission n ON n.code=CASE old.code
 WHEN 'publication_supplement.submit' THEN 'change.submit' ELSE 'change.decide' END
WHERE old.code IN ('publication_supplement.submit','publication_supplement.decide');
ALTER TRIGGER publication_supplement_updated_at ON smartlib.change_submission RENAME TO change_submission_updated_at;
ALTER TRIGGER publication_change_candidate_updated_at ON smartlib.change_proposal RENAME TO change_proposal_updated_at;
DROP POLICY publication_supplement_read ON smartlib.change_submission;
CREATE POLICY change_submission_read ON smartlib.change_submission FOR SELECT TO smartlib_app,smartlib_readonly
USING ((workflow_key='publication' AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=context_object_id))
 OR created_by=smartlib.current_actor_id() OR smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide'));
ALTER POLICY publication_supplement_write ON smartlib.change_submission RENAME TO change_submission_write;
ALTER POLICY publication_change_candidate_read ON smartlib.change_proposal RENAME TO change_proposal_read;
ALTER POLICY publication_change_candidate_write ON smartlib.change_proposal RENAME TO change_proposal_write;
ALTER TABLE smartlib.change_submission ADD CONSTRAINT change_workflow_check CHECK(workflow_key IN ('publication','entity'));
ALTER POLICY change_submission_write ON smartlib.change_submission
USING(created_by=smartlib.current_actor_id() OR smartlib.actor_has_permission(smartlib.current_actor_id(),
 CASE workflow_key WHEN 'entity' THEN 'change.decide' ELSE 'publication_supplement.decide' END))
WITH CHECK(created_by=smartlib.current_actor_id() OR smartlib.actor_has_permission(smartlib.current_actor_id(),
 CASE workflow_key WHEN 'entity' THEN 'change.decide' ELSE 'publication_supplement.decide' END));
ALTER POLICY change_proposal_write ON smartlib.change_proposal
USING(created_by=smartlib.current_actor_id() OR EXISTS(SELECT 1 FROM smartlib.change_submission s
 WHERE s.submission_id=change_proposal.submission_id AND smartlib.actor_has_permission(smartlib.current_actor_id(),
 CASE s.workflow_key WHEN 'entity' THEN 'change.decide' ELSE 'publication_supplement.decide' END)))
WITH CHECK(created_by=smartlib.current_actor_id() OR EXISTS(SELECT 1 FROM smartlib.change_submission s
 WHERE s.submission_id=change_proposal.submission_id AND smartlib.actor_has_permission(smartlib.current_actor_id(),
 CASE s.workflow_key WHEN 'entity' THEN 'change.decide' ELSE 'publication_supplement.decide' END)));
RESET ROLE;
