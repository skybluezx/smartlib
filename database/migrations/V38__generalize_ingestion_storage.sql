SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

-- Keep original row identities, and therefore every historical reference.
CREATE TABLE smartlib.publication_intake_record (
 record_id uuid PRIMARY KEY REFERENCES smartlib.publication_import_item(import_item_id),
 verification_state text NOT NULL DEFAULT 'pending' CHECK (verification_state IN (
 'pending','normalized','auto_verified','manual_review','reverification_required',
 'verification_conflict','human_verified','corrected','rejected','superseded')),
 matched_publication_id uuid REFERENCES smartlib.knowledge_object(object_id),
 duplicate_of_item_id uuid REFERENCES smartlib.publication_intake_record(record_id),
 CHECK(duplicate_of_item_id IS NULL OR duplicate_of_item_id<>record_id),
 CHECK(verification_state<>'superseded' OR duplicate_of_item_id IS NOT NULL)
);
INSERT INTO smartlib.publication_intake_record
SELECT import_item_id,verification_state,matched_publication_id,duplicate_of_item_id FROM smartlib.publication_import_item;
CREATE TABLE smartlib.representative_work_submission (
 record_id uuid PRIMARY KEY REFERENCES smartlib.publication_intake_record(record_id),
 representative_work_number text,
 awardee_name_raw text,
 awardee_person_id uuid REFERENCES smartlib.knowledge_object(object_id)
);
INSERT INTO smartlib.representative_work_submission
SELECT import_item_id,representative_work_number,awardee_name_raw,awardee_person_id FROM smartlib.publication_import_item
WHERE representative_work_number IS NOT NULL OR awardee_name_raw IS NOT NULL OR awardee_person_id IS NOT NULL;

-- Publication verification history must reference the publication extension, not arbitrary input records.
DO $$ DECLARE c record; BEGIN
 FOR c IN SELECT conrelid::regclass AS tbl,conname,pg_get_constraintdef(oid) AS def
 FROM pg_constraint WHERE contype='f' AND confrelid='smartlib.publication_import_item'::regclass
 AND conrelid NOT IN ('smartlib.publication_import_item'::regclass,'smartlib.publication_intake_record'::regclass) LOOP
 EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',c.tbl,c.conname);
 EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s',c.tbl,c.conname,
 replace(c.def,'REFERENCES publication_import_item(import_item_id)','REFERENCES publication_intake_record(record_id)'));
 END LOOP;
END $$;
DROP TRIGGER publication_import_item_publication_type ON smartlib.publication_import_item;
DROP TRIGGER publication_import_item_awardee_type ON smartlib.publication_import_item;
ALTER TABLE smartlib.publication_import_item DROP COLUMN verification_state,
 DROP COLUMN matched_publication_id,DROP COLUMN duplicate_of_item_id,
 DROP COLUMN representative_work_number,DROP COLUMN awardee_name_raw,DROP COLUMN awardee_person_id;
ALTER TABLE smartlib.publication_import_batch RENAME TO ingestion_batch;
ALTER TABLE smartlib.ingestion_batch RENAME COLUMN import_batch_id TO batch_id;
ALTER TABLE smartlib.ingestion_batch RENAME COLUMN source_file_uri TO source_uri;
ALTER TABLE smartlib.ingestion_batch RENAME COLUMN source_file_checksum TO source_checksum;
ALTER TABLE smartlib.ingestion_batch RENAME COLUMN verification_rule_version TO processing_rule_version;
ALTER TABLE smartlib.ingestion_batch ALTER COLUMN source_uri DROP NOT NULL,
 ALTER COLUMN source_checksum DROP NOT NULL,
 ADD COLUMN source_kind text NOT NULL DEFAULT 'file' CHECK(source_kind IN ('file','api','manual','connector','stream')),
 ADD COLUMN pipeline_key text NOT NULL DEFAULT 'publication' CHECK(btrim(pipeline_key)<>''),
 ADD COLUMN source_locator jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(source_locator)='object');
ALTER TABLE smartlib.ingestion_batch DISABLE TRIGGER publication_import_batch_updated_at;
UPDATE smartlib.ingestion_batch SET source_locator=jsonb_build_object('sheet',source_sheet);
ALTER TABLE smartlib.ingestion_batch DROP COLUMN source_sheet;
ALTER TABLE smartlib.ingestion_batch ENABLE TRIGGER publication_import_batch_updated_at;
ALTER TABLE smartlib.ingestion_batch ALTER COLUMN pipeline_key DROP DEFAULT;

ALTER TABLE smartlib.publication_import_item RENAME TO ingestion_record;
ALTER TABLE smartlib.ingestion_record RENAME COLUMN import_item_id TO record_id;
ALTER TABLE smartlib.ingestion_record RENAME COLUMN import_batch_id TO batch_id;
ALTER TABLE smartlib.ingestion_record RENAME COLUMN row_checksum TO payload_checksum;
ALTER TABLE smartlib.ingestion_record ADD COLUMN source_locator jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(source_locator)='object'),
 ADD COLUMN source_record_key text,
 ADD COLUMN record_kind text NOT NULL DEFAULT 'publication' CHECK(btrim(record_kind)<>''),
 ADD COLUMN processing_state text NOT NULL DEFAULT 'received' CHECK(processing_state IN ('received','processing','processed','failed','cancelled'));
ALTER TABLE smartlib.ingestion_record DISABLE TRIGGER publication_import_item_updated_at;
UPDATE smartlib.ingestion_record SET source_locator=jsonb_build_object('sheet',source_sheet,'row',source_row_number),
 source_record_key=jsonb_build_array(source_sheet,source_row_number)::text;
ALTER TABLE smartlib.ingestion_record ALTER COLUMN source_record_key SET NOT NULL,
 ADD CHECK(btrim(source_record_key)<>''), ADD UNIQUE(batch_id,source_record_key),
 DROP COLUMN source_sheet,DROP COLUMN source_row_number;
ALTER TABLE smartlib.ingestion_record ALTER COLUMN record_kind DROP DEFAULT;
ALTER TABLE smartlib.ingestion_record ENABLE TRIGGER publication_import_item_updated_at;
CREATE INDEX ingestion_record_kind_state_idx ON smartlib.ingestion_record(record_kind,processing_state);
CREATE INDEX publication_intake_state_idx ON smartlib.publication_intake_record(verification_state);
CREATE INDEX publication_intake_match_idx ON smartlib.publication_intake_record(matched_publication_id);
CREATE INDEX representative_work_awardee_idx ON smartlib.representative_work_submission(awardee_person_id);
CREATE TRIGGER publication_intake_publication_type BEFORE INSERT OR UPDATE ON smartlib.publication_intake_record
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type('matched_publication_id','publication');
CREATE TRIGGER representative_work_person_type BEFORE INSERT OR UPDATE ON smartlib.representative_work_submission
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type('awardee_person_id','person');

-- A single input may produce several knowledge objects; matching is not automatically approval.
CREATE TABLE smartlib.ingestion_record_object (
 record_id uuid NOT NULL REFERENCES smartlib.ingestion_record(record_id),
 object_id uuid NOT NULL REFERENCES smartlib.knowledge_object(object_id),
 output_role text NOT NULL CHECK(btrim(output_role)<>''),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(record_id,object_id,output_role)
);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['publication_intake_record','representative_work_submission','ingestion_record_object'] LOOP
 EXECUTE format('ALTER TABLE smartlib.%I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('CREATE POLICY input_owner_read ON smartlib.%I FOR SELECT TO smartlib_app,smartlib_readonly USING (EXISTS (SELECT 1 FROM smartlib.ingestion_record r WHERE r.record_id=%I.record_id))',t,t);
 EXECUTE format('CREATE POLICY input_owner_write ON smartlib.%I FOR ALL TO smartlib_app USING (EXISTS (SELECT 1 FROM smartlib.ingestion_record r WHERE r.record_id=%I.record_id AND r.created_by=smartlib.current_actor_id())) WITH CHECK (EXISTS (SELECT 1 FROM smartlib.ingestion_record r WHERE r.record_id=%I.record_id AND r.created_by=smartlib.current_actor_id()))',t,t,t);
 EXECUTE format('GRANT SELECT,INSERT,UPDATE ON smartlib.%I TO smartlib_app',t);
 EXECUTE format('GRANT SELECT ON smartlib.%I TO smartlib_readonly',t);
 END LOOP;
END $$;

-- Compatibility adapters are views, not a second copy of the imported data.
CREATE VIEW smartlib.publication_import_batch WITH(security_invoker=true) AS
SELECT batch_id AS import_batch_id,source_system_id,dataset_version,source_uri AS source_file_uri,
 source_checksum AS source_file_checksum,source_locator->>'sheet' AS source_sheet,expected_item_count,
 batch_state,processing_rule_version AS verification_rule_version,metadata,created_by,created_at,updated_at
FROM smartlib.ingestion_batch WHERE pipeline_key='publication';
CREATE VIEW smartlib.publication_import_item WITH(security_invoker=true) AS
SELECT r.record_id AS import_item_id,r.batch_id AS import_batch_id,r.source_locator->>'sheet' AS source_sheet,
 (r.source_locator->>'row')::integer AS source_row_number,s.representative_work_number,s.awardee_name_raw,
 r.raw_payload,r.normalized_payload,r.payload_checksum AS row_checksum,p.verification_state,p.matched_publication_id,
 p.duplicate_of_item_id,r.created_by,r.created_at,r.updated_at,s.awardee_person_id
FROM smartlib.ingestion_record r JOIN smartlib.publication_intake_record p USING(record_id)
LEFT JOIN smartlib.representative_work_submission s USING(record_id);
GRANT SELECT,INSERT,UPDATE ON smartlib.publication_import_batch,smartlib.publication_import_item TO smartlib_app;
GRANT SELECT ON smartlib.publication_import_batch,smartlib.publication_import_item TO smartlib_readonly;

CREATE FUNCTION smartlib.write_publication_import_batch() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,smartlib AS $$
BEGIN
 IF TG_OP='INSERT' THEN
 NEW.import_batch_id=COALESCE(NEW.import_batch_id,gen_random_uuid());
 NEW.created_at=COALESCE(NEW.created_at,clock_timestamp()); NEW.updated_at=COALESCE(NEW.updated_at,NEW.created_at);
 INSERT INTO smartlib.ingestion_batch(batch_id,source_system_id,dataset_version,source_uri,source_checksum,
 source_locator,pipeline_key,expected_item_count,batch_state,processing_rule_version,metadata,created_by,created_at,updated_at)
 VALUES(NEW.import_batch_id,NEW.source_system_id,NEW.dataset_version,NEW.source_file_uri,NEW.source_file_checksum,
 jsonb_build_object('sheet',NEW.source_sheet),'publication',NEW.expected_item_count,COALESCE(NEW.batch_state,'created'),
 NEW.verification_rule_version,COALESCE(NEW.metadata,'{}'),NEW.created_by,NEW.created_at,NEW.updated_at);
 ELSE
 IF NEW.import_batch_id<>OLD.import_batch_id THEN RAISE EXCEPTION 'batch identity is immutable'; END IF;
 UPDATE smartlib.ingestion_batch SET source_system_id=NEW.source_system_id,dataset_version=NEW.dataset_version,
 source_uri=NEW.source_file_uri,source_checksum=NEW.source_file_checksum,source_locator=jsonb_build_object('sheet',NEW.source_sheet),
 expected_item_count=NEW.expected_item_count,batch_state=NEW.batch_state,processing_rule_version=NEW.verification_rule_version,
 metadata=NEW.metadata,created_by=NEW.created_by WHERE batch_id=OLD.import_batch_id;
 END IF;
 SELECT * INTO NEW FROM smartlib.publication_import_batch WHERE import_batch_id=NEW.import_batch_id;
 RETURN NEW;
END $$;
CREATE TRIGGER publication_import_batch_write INSTEAD OF INSERT OR UPDATE ON smartlib.publication_import_batch
FOR EACH ROW EXECUTE FUNCTION smartlib.write_publication_import_batch();
CREATE FUNCTION smartlib.write_publication_import_item() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,smartlib AS $$
BEGIN
 IF NEW.source_sheet IS NULL OR btrim(NEW.source_sheet)='' OR NEW.source_row_number IS NULL OR NEW.source_row_number<1 THEN
 RAISE EXCEPTION 'publication compatibility adapter requires sheet and positive row'; END IF;
 IF TG_OP='INSERT' THEN
 NEW.import_item_id=COALESCE(NEW.import_item_id,gen_random_uuid());
 NEW.created_at=COALESCE(NEW.created_at,clock_timestamp()); NEW.updated_at=COALESCE(NEW.updated_at,NEW.created_at);
 NEW.verification_state=COALESCE(NEW.verification_state,'pending'); NEW.normalized_payload=COALESCE(NEW.normalized_payload,'{}');
 INSERT INTO smartlib.ingestion_record(record_id,batch_id,source_locator,source_record_key,record_kind,raw_payload,
 normalized_payload,payload_checksum,created_by,created_at,updated_at)
 VALUES(NEW.import_item_id,NEW.import_batch_id,jsonb_build_object('sheet',NEW.source_sheet,'row',NEW.source_row_number),
 jsonb_build_array(NEW.source_sheet,NEW.source_row_number)::text,'publication',NEW.raw_payload,NEW.normalized_payload,
 NEW.row_checksum,NEW.created_by,NEW.created_at,NEW.updated_at);
 INSERT INTO smartlib.publication_intake_record(record_id,verification_state,matched_publication_id,duplicate_of_item_id)
 VALUES(NEW.import_item_id,NEW.verification_state,NEW.matched_publication_id,NEW.duplicate_of_item_id);
 ELSE
 IF NEW.import_item_id<>OLD.import_item_id THEN RAISE EXCEPTION 'record identity is immutable'; END IF;
 UPDATE smartlib.ingestion_record SET batch_id=NEW.import_batch_id,
 source_locator=jsonb_build_object('sheet',NEW.source_sheet,'row',NEW.source_row_number),
 source_record_key=jsonb_build_array(NEW.source_sheet,NEW.source_row_number)::text,
 raw_payload=NEW.raw_payload,normalized_payload=NEW.normalized_payload,payload_checksum=NEW.row_checksum,created_by=NEW.created_by
 WHERE record_id=OLD.import_item_id;
 UPDATE smartlib.publication_intake_record SET verification_state=NEW.verification_state,
 matched_publication_id=NEW.matched_publication_id,duplicate_of_item_id=NEW.duplicate_of_item_id WHERE record_id=OLD.import_item_id;
 END IF;
 IF NEW.representative_work_number IS NOT NULL OR NEW.awardee_name_raw IS NOT NULL OR NEW.awardee_person_id IS NOT NULL
 OR EXISTS(SELECT 1 FROM smartlib.representative_work_submission WHERE record_id=NEW.import_item_id) THEN
 INSERT INTO smartlib.representative_work_submission(record_id,representative_work_number,awardee_name_raw,awardee_person_id)
 VALUES(NEW.import_item_id,NEW.representative_work_number,NEW.awardee_name_raw,NEW.awardee_person_id)
 ON CONFLICT(record_id) DO UPDATE SET representative_work_number=EXCLUDED.representative_work_number,
 awardee_name_raw=EXCLUDED.awardee_name_raw,awardee_person_id=EXCLUDED.awardee_person_id;
 END IF;
 SELECT * INTO NEW FROM smartlib.publication_import_item WHERE import_item_id=NEW.import_item_id;
 RETURN NEW;
END $$;
CREATE TRIGGER publication_import_item_write INSTEAD OF INSERT OR UPDATE ON smartlib.publication_import_item
FOR EACH ROW EXECUTE FUNCTION smartlib.write_publication_import_item();

CREATE TRIGGER ingestion_batch_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.ingestion_batch
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('batch_id');
CREATE TRIGGER ingestion_record_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.ingestion_record
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('record_id');
CREATE TRIGGER publication_intake_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.publication_intake_record
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('record_id');
CREATE TRIGGER representative_work_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.representative_work_submission
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('record_id');
COMMENT ON TABLE smartlib.ingestion_batch IS 'Generic input batch for files, APIs, manual input, connectors and streams; pipeline selects a domain adapter.';
COMMENT ON TABLE smartlib.ingestion_record IS 'Generic source occurrence; raw payload and source locator are retained independently of resulting objects.';
COMMENT ON VIEW smartlib.publication_import_item IS 'Compatibility view for the publication workbench; ON CONFLICT is not supported, use ingestion service for generic input.';
REVOKE ALL ON FUNCTION smartlib.write_publication_import_batch(),smartlib.write_publication_import_item() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.write_publication_import_batch(),smartlib.write_publication_import_item() TO smartlib_app;
RESET ROLE;

SET ROLE smartlib_owner;
CREATE FUNCTION smartlib.validate_publication_intake_kind() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,smartlib AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM smartlib.ingestion_record WHERE record_id=NEW.record_id AND record_kind='publication') THEN
 RAISE EXCEPTION 'publication intake requires a publication source record' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER publication_intake_kind BEFORE INSERT OR UPDATE ON smartlib.publication_intake_record
FOR EACH ROW EXECUTE FUNCTION smartlib.validate_publication_intake_kind();
CREATE FUNCTION smartlib.guard_ingestion_record_kind() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.record_kind<>OLD.record_kind THEN RAISE EXCEPTION 'input record kind is immutable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ingestion_record_kind BEFORE UPDATE ON smartlib.ingestion_record
FOR EACH ROW EXECUTE FUNCTION smartlib.guard_ingestion_record_kind();
INSERT INTO smartlib.access_permission(code,name,risk_level) VALUES('ingestion.submit','提交通用数据导入','normal');
INSERT INTO smartlib.access_role_permission(role_id,permission_id)
SELECT r.role_id,p.permission_id FROM smartlib.access_role r CROSS JOIN smartlib.access_permission p
WHERE r.code='knowledge_admin' AND p.code='ingestion.submit';
REVOKE ALL ON FUNCTION smartlib.validate_publication_intake_kind(),smartlib.guard_ingestion_record_kind() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.validate_publication_intake_kind(),smartlib.guard_ingestion_record_kind() TO smartlib_app;
RESET ROLE;
