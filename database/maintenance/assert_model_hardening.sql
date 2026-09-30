\set ON_ERROR_STOP on
BEGIN;
SET LOCAL ROLE smartlib_owner;
DO $$
DECLARE a smartlib.publication_authorship%ROWTYPE; j smartlib.journal_identity%ROWTYPE;
    p uuid; old_evidence bigint; new_evidence bigint;
BEGIN
    SELECT s.* INTO STRICT a FROM smartlib.publication_authorship s
    WHERE s.person_object_id IS NOT NULL AND s.match_status='matched'
      AND s.verification_status IN ('matched','corrected')
      AND (SELECT count(*) FROM smartlib.publication_authorship x
           WHERE x.publication_id=s.publication_id AND x.person_object_id=s.person_object_id)=1 LIMIT 1;
    SELECT * INTO STRICT j FROM smartlib.journal_identity WHERE knowledge_object_id IS NOT NULL LIMIT 1;
    SELECT object_id INTO STRICT p FROM smartlib.knowledge_object WHERE object_type='project' LIMIT 1;
    BEGIN
        UPDATE smartlib.knowledge_object SET attributes='{}' WHERE object_id=p;
        RAISE EXCEPTION 'FAIL: missing record kind accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    BEGIN
        UPDATE smartlib.relation_assertion SET attributes=attributes||'{"author_order":999,"roles":["made_up_role"]}'
        WHERE predicate='person.authored' AND subject_id=a.person_object_id AND object_id=a.publication_id;
        RAISE EXCEPTION 'FAIL: role drift accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    SELECT count(*) INTO old_evidence FROM smartlib.relation_evidence e JOIN smartlib.relation_assertion r USING(relation_id)
    WHERE r.predicate='person.authored' AND r.subject_id=a.person_object_id AND r.object_id=a.publication_id;
    UPDATE smartlib.publication_authorship SET match_status='ambiguous',verification_status='conflict'
    WHERE publication_authorship_id=a.publication_authorship_id;
    IF EXISTS(SELECT 1 FROM smartlib.relation_assertion WHERE predicate='person.authored'
        AND subject_id=a.person_object_id AND object_id=a.publication_id AND review_state='approved') THEN
        RAISE EXCEPTION 'FAIL: conflict remains approved';
    END IF;
    UPDATE smartlib.publication_authorship SET verification_status='rejected'
    WHERE publication_authorship_id=a.publication_authorship_id;
    SELECT count(*) INTO new_evidence FROM smartlib.relation_evidence e JOIN smartlib.relation_assertion r USING(relation_id)
    WHERE r.predicate='person.authored' AND r.subject_id=a.person_object_id AND r.object_id=a.publication_id;
    IF old_evidence<>new_evidence THEN RAISE EXCEPTION 'FAIL: evidence lost on retirement'; END IF;
    UPDATE smartlib.publication_authorship SET match_status=a.match_status,verification_status=a.verification_status
    WHERE publication_authorship_id=a.publication_authorship_id;
    IF NOT EXISTS(SELECT 1 FROM smartlib.authorship_relation_sync_state WHERE publication_id=a.publication_id
        AND person_object_id=a.person_object_id AND sync_state='synchronized') THEN
        RAISE EXCEPTION 'FAIL: reactivation not synchronized'; END IF;
    BEGIN
        UPDATE smartlib.journal_identity SET canonical_title=canonical_title||' probe' WHERE journal_id=j.journal_id;
        UPDATE smartlib.knowledge_object SET canonical_name='BAD TITLE' WHERE object_id=j.knowledge_object_id;
        RAISE EXCEPTION 'FAIL: journal bypass accepted';
    EXCEPTION WHEN check_violation THEN NULL; END;
    UPDATE smartlib.publication_metadata SET title=title||' probe' WHERE publication_id=a.publication_id;
    IF EXISTS(SELECT 1 FROM smartlib.publication_metadata m JOIN smartlib.knowledge_object o ON o.object_id=m.publication_id
        WHERE m.publication_id=a.publication_id AND m.title IS DISTINCT FROM o.canonical_name) THEN
        RAISE EXCEPTION 'FAIL: publication title drift'; END IF;
    BEGIN
        UPDATE smartlib.knowledge_object SET object_type='concept',attributes='{}' WHERE object_id=a.person_object_id;
        RAISE EXCEPTION 'FAIL: endpoint type changed';
    EXCEPTION WHEN check_violation THEN NULL; END;
    RAISE NOTICE 'PASS: model hardening, retirement evidence preservation and reactivation';
END $$;
ROLLBACK;
