\set ON_ERROR_STOP on
BEGIN;
SET LOCAL smartlib.actor_id='00000000-0000-4000-8000-000000000001';
SET LOCAL smartlib.change_reason='Transaction-only incremental project regression';
DO $$
DECLARE p uuid; target uuid; field text; bad jsonb;
 actor uuid := '00000000-0000-4000-8000-000000000001';
BEGIN
 INSERT INTO smartlib.knowledge_object(object_type,canonical_name,attributes,created_by)
 VALUES('project','事务内占位项目测试','{"record_kind":"individual_grant"}',actor) RETURNING object_id INTO p;
 UPDATE smartlib.knowledge_object SET attributes=attributes ||
 '{"dataset_id":null,"dataset_version":null,"year":null,"funding_program_id":null,"principal_investigator_person_id":null}'::jsonb WHERE object_id=p;
 UPDATE smartlib.knowledge_object SET attributes=attributes || '{"year":2026,"dataset_id":"test","dataset_version":"v1"}'::jsonb WHERE object_id=p;
 SELECT object_id INTO target FROM smartlib.knowledge_object WHERE object_type='person' AND system_to='infinity' LIMIT 1;
 IF target IS NULL THEN
  INSERT INTO smartlib.knowledge_object(object_type,canonical_name,created_by) VALUES('person','事务内学者测试',actor) RETURNING object_id INTO target;
 END IF;
 UPDATE smartlib.knowledge_object SET attributes=attributes || jsonb_build_object('principal_investigator_person_id',target) WHERE object_id=p;
 FOREACH field IN ARRAY ARRAY['funding_program_id','principal_investigator_person_id'] LOOP
  BEGIN
   UPDATE smartlib.knowledge_object SET attributes=attributes || jsonb_build_object(field,gen_random_uuid()) WHERE object_id=p;
   RAISE EXCEPTION 'FAIL: nonexistent reference accepted';
  EXCEPTION WHEN check_violation THEN
   IF SQLERRM NOT LIKE 'invalid % reference' THEN RAISE; END IF;
  END;
  BEGIN
   UPDATE smartlib.knowledge_object SET attributes=attributes || jsonb_build_object(field,p) WHERE object_id=p;
   RAISE EXCEPTION 'FAIL: wrong-type reference accepted';
  EXCEPTION WHEN check_violation THEN
   IF SQLERRM NOT LIKE 'invalid % reference' THEN RAISE; END IF;
  END;
 END LOOP;
 FOREACH bad IN ARRAY ARRAY['{}'::jsonb,'{"record_kind":"unregistered"}'::jsonb] LOOP
  BEGIN
   INSERT INTO smartlib.knowledge_object(object_type,canonical_name,attributes,created_by) VALUES('project','非法分类测试',bad,actor);
   RAISE EXCEPTION 'FAIL: missing/unregistered subtype accepted';
  EXCEPTION WHEN check_violation THEN
   IF SQLERRM NOT LIKE 'registered record_kind is required%' AND SQLERRM NOT LIKE 'unregistered object attribute%' THEN RAISE; END IF;
  END;
 END LOOP;
 BEGIN
  UPDATE smartlib.knowledge_object SET attributes=attributes || '{"year":"unknown"}'::jsonb WHERE object_id=p;
  RAISE EXCEPTION 'FAIL: wrong year type accepted';
 EXCEPTION WHEN check_violation THEN
  IF SQLERRM NOT LIKE 'invalid JSON type%' THEN RAISE; END IF;
 END;
 BEGIN
  UPDATE smartlib.knowledge_object SET attributes=attributes || '{"invented_field":true}'::jsonb WHERE object_id=p;
  RAISE EXCEPTION 'FAIL: unregistered attribute accepted';
 EXCEPTION WHEN check_violation THEN
  IF SQLERRM NOT LIKE 'unregistered % attribute%' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'INCREMENTAL_PROJECT_OK: minimal creation, nulls, enrichment, valid person, invalid references, subtype and type guards';
END $$;
ROLLBACK;
