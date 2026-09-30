\set ON_ERROR_STOP on
BEGIN;
SET LOCAL ROLE smartlib_owner;
SELECT set_config('smartlib.actor_id','00000000-0000-4000-8000-000000000001',true);
DO $$ DECLARE a uuid='00000000-0000-4000-8000-000000000001'; p uuid=gen_random_uuid();
 person uuid=gen_random_uuid(); s1 uuid=gen_random_uuid(); s2 uuid=gen_random_uuid(); r uuid;
BEGIN
 INSERT INTO smartlib.knowledge_object(object_id,object_type,canonical_name,created_by)
 VALUES(p,'publication','refactor test publication',a),(person,'person','refactor test person',a);
 INSERT INTO smartlib.publication_authorship(publication_authorship_id,publication_id,author_order,author_name_raw,author_name_normalized,
 person_object_id,match_status,verification_status,created_by) VALUES(s1,p,2,'test','test',person,'matched','matched',a);
 SET CONSTRAINTS ALL IMMEDIATE; SET CONSTRAINTS ALL DEFERRED;
 SELECT relation_id INTO r FROM smartlib.relation_assertion WHERE subject_id=person AND object_id=p AND predicate='person.authored';
 IF smartlib.publication_relation_authorship(r) IS DISTINCT FROM s1 THEN RAISE EXCEPTION 'missing provenance'; END IF;
 INSERT INTO smartlib.publication_authorship(publication_authorship_id,publication_id,author_order,author_name_raw,author_name_normalized,
 person_object_id,match_status,verification_status,created_by) VALUES(s2,p,1,'test','test',person,'matched','matched',a);
 SET CONSTRAINTS ALL IMMEDIATE; SET CONSTRAINTS ALL DEFERRED;
 IF smartlib.publication_relation_authorship(r) IS DISTINCT FROM s2 THEN RAISE EXCEPTION 'canonical source not updated'; END IF;
 BEGIN
 DELETE FROM smartlib.publication_relation_provenance WHERE relation_id=r;
 SET CONSTRAINTS ALL IMMEDIATE;
 RAISE EXCEPTION 'missing provenance accepted';
 EXCEPTION WHEN check_violation THEN NULL; END;
 DELETE FROM smartlib.publication_authorship WHERE publication_authorship_id=s2;
 SET CONSTRAINTS ALL IMMEDIATE; SET CONSTRAINTS ALL DEFERRED;
 IF smartlib.publication_relation_authorship(r) IS DISTINCT FROM s1 THEN RAISE EXCEPTION 'canonical source deletion not repaired'; END IF;
 UPDATE smartlib.publication_authorship SET verification_status='rejected' WHERE publication_authorship_id=s1;
 SET CONSTRAINTS ALL IMMEDIATE; SET CONSTRAINTS ALL DEFERRED;
 IF (SELECT review_state FROM smartlib.relation_assertion WHERE relation_id=r)<>'superseded' THEN RAISE EXCEPTION 'authority retirement failed'; END IF;
 UPDATE smartlib.publication_authorship SET verification_status='matched' WHERE publication_authorship_id=s1;
 SET CONSTRAINTS ALL IMMEDIATE; SET CONSTRAINTS ALL DEFERRED;
 IF (SELECT review_state FROM smartlib.relation_assertion WHERE relation_id=r)<>'approved' THEN RAISE EXCEPTION 'authority restoration failed'; END IF;
 DELETE FROM smartlib.publication_authorship WHERE publication_authorship_id=s1;
 SET CONSTRAINTS ALL IMMEDIATE; SET CONSTRAINTS ALL DEFERRED;
 IF EXISTS(SELECT 1 FROM smartlib.authorship_relation_sync_state WHERE publication_id=p AND sync_state<>'synchronized') THEN
 RAISE EXCEPTION 'authority drift'; END IF;
END $$;
ROLLBACK;
SELECT 'MODEL_REFACTOR_AUTHORITY_OK';
BEGIN;
SET LOCAL ROLE smartlib_owner;
SELECT set_config('smartlib.actor_id','00000000-0000-4000-8000-000000000001',true);
DO $$ DECLARE actor uuid='00000000-0000-4000-8000-000000000001'; pub uuid; pdf uuid;
 person uuid=gen_random_uuid(); org uuid=gen_random_uuid(); s uuid=gen_random_uuid(); r uuid=gen_random_uuid(); e uuid=gen_random_uuid();
BEGIN
 SELECT publication_id,fulltext_resource_id INTO pub,pdf FROM smartlib.publication_fulltext_resource LIMIT 1;
 INSERT INTO smartlib.knowledge_object(object_id,object_type,canonical_name,created_by,attributes)
 VALUES(person,'person','Affiliation fixture',actor,'{}'),(org,'organization','Affiliation test institution',actor,'{"identity_resolution_status":"confirmed","source":"fulltext"}');
 INSERT INTO smartlib.publication_authorship(publication_authorship_id,publication_id,author_order,author_name_raw,
 author_name_normalized,person_object_id,match_status,verification_status,created_by)
 VALUES(s,pub,999,'test','test',person,'matched','matched',actor);
 INSERT INTO smartlib.relation_assertion(relation_id,subject_id,predicate,object_id,context_object_id,fact_class,review_state,created_by,attributes)
 VALUES(r,person,'person.affiliated_with',org,pub,'literature_fact','approved',actor,'{"source":"fulltext","rule_version":"fixture"}');
 INSERT INTO smartlib.publication_relation_provenance VALUES(r,s,clock_timestamp());
 INSERT INTO smartlib.evidence_record(evidence_id,object_id,evidence_type,evidence_kind,fulltext_resource_id,page_number,
 verification_state,citation,excerpt,created_by) VALUES(e,pub,'publication','author_affiliation',pdf,1,'confirmed','Fixture only','test affiliation',actor);
 INSERT INTO smartlib.relation_evidence(relation_id,evidence_id) VALUES(r,e);
 SET CONSTRAINTS ALL IMMEDIATE; SET CONSTRAINTS ALL DEFERRED;
 BEGIN
 UPDATE smartlib.publication_authorship SET verification_status='rejected' WHERE publication_authorship_id=s;
 SET CONSTRAINTS ALL IMMEDIATE;
 RAISE EXCEPTION 'invalidated affiliation authority accepted';
 EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN
 DELETE FROM smartlib.publication_relation_provenance WHERE relation_id=r;
 SET CONSTRAINTS ALL IMMEDIATE;
 RAISE EXCEPTION 'approved affiliation without source accepted';
 EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN
 INSERT INTO smartlib.relation_assertion(subject_id,predicate,object_id,context_object_id,fact_class,review_state,created_by,attributes)
 VALUES(person,'person.affiliated_with',org,pub,'literature_fact','pending',actor,'{"source":"fulltext","rule_version":"fixture"}') RETURNING relation_id INTO r;
 INSERT INTO smartlib.publication_relation_provenance(relation_id,publication_authorship_id) VALUES(r,s);
 SET CONSTRAINTS ALL IMMEDIATE;
 RAISE EXCEPTION 'duplicate affiliation snapshot accepted';
 EXCEPTION WHEN unique_violation THEN NULL; END;
END $$;
ROLLBACK;
SELECT 'MODEL_REFACTOR_AFFILIATION_OK';
