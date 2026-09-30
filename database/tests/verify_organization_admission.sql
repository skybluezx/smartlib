\set ON_ERROR_STOP on
BEGIN;
SELECT set_config('smartlib.actor_id','00000000-0000-4000-8000-000000000001',true);
DO $$
DECLARE ev uuid; d uuid; actor uuid := '00000000-0000-4000-8000-000000000001';
BEGIN
 BEGIN
 INSERT INTO smartlib.knowledge_object(object_type,canonical_name,attributes,created_by)
 VALUES('organization','unresolved affiliation','{"source":"test","identity_resolution_status":"reviewed_source_label"}',actor);
 RAISE EXCEPTION 'FAIL: raw affiliation admitted';
 EXCEPTION WHEN check_violation THEN
 IF SQLERRM NOT LIKE 'Organization requires%' THEN RAISE; END IF;
 END;
 BEGIN
 INSERT INTO smartlib.knowledge_object(object_type,canonical_name,attributes,created_by)
 VALUES('organization','forged decision','{"source":"test","identity_resolution_status":"confirmed","entity_decision_id":"fake"}',actor);
 RAISE EXCEPTION 'FAIL: forged decision admitted';
 EXCEPTION WHEN check_violation THEN
 IF SQLERRM NOT LIKE 'Organization requires%' THEN RAISE; END IF;
 END;
 SELECT evidence_id INTO ev FROM smartlib.evidence_record WHERE evidence_kind='author_affiliation' LIMIT 1;
 BEGIN
 PERFORM smartlib.confirm_organization_entity('Invalid evidence',ev,'Raw affiliation alone');
 RAISE EXCEPTION 'FAIL: affiliation accepted as identity';
 EXCEPTION WHEN check_violation THEN
 IF SQLERRM NOT LIKE 'Confirmed organization_identity%' THEN RAISE; END IF;
 END;
 INSERT INTO smartlib.evidence_record(object_id,evidence_type,evidence_kind,verification_state,citation,excerpt,created_by)
 SELECT object_id,'manual_review','organization_identity','confirmed','transaction-only test','Independent institution decision',actor
 FROM smartlib.knowledge_object WHERE object_type='publication' LIMIT 1 RETURNING evidence_id INTO ev;
 d := smartlib.confirm_organization_entity('Admission regression test',ev,'Identity reviewed separately from affiliation extraction');
 BEGIN
 INSERT INTO smartlib.knowledge_object(object_type,canonical_name,attributes,created_by)
 VALUES('organization','Wrong name',jsonb_build_object('source','test','identity_resolution_status','confirmed','entity_decision_id',d),actor);
 RAISE EXCEPTION 'FAIL: wrong name admitted';
 EXCEPTION WHEN check_violation THEN
 IF SQLERRM NOT LIKE 'Organization requires%' THEN RAISE; END IF;
 END;
 INSERT INTO smartlib.knowledge_object(object_type,canonical_name,attributes,created_by)
 VALUES('organization','Admission regression test',jsonb_build_object('source','test','identity_resolution_status','confirmed','entity_decision_id',d),actor);
 BEGIN
 INSERT INTO smartlib.knowledge_object(object_type,canonical_name,attributes,created_by)
 VALUES('organization','Admission regression test',jsonb_build_object('source','test','identity_resolution_status','confirmed','entity_decision_id',d),actor);
 RAISE EXCEPTION 'FAIL: decision reused';
 EXCEPTION WHEN unique_violation THEN NULL;
 END;
 PERFORM set_config('smartlib.actor_id','',true);
 BEGIN
 PERFORM smartlib.confirm_organization_entity('Unauthorized',ev,'No reviewer');
 RAISE EXCEPTION 'FAIL: unauthorized confirmation';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
 RAISE NOTICE 'ORGANIZATION_ADMISSION_OK: raw, forged, wrong evidence/name, reuse, permission, positive';
END $$;
ROLLBACK;
