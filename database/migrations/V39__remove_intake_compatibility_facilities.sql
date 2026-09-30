SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;
DROP VIEW smartlib.publication_import_item;
DROP VIEW smartlib.publication_import_batch;
DROP FUNCTION smartlib.write_publication_import_item();
DROP FUNCTION smartlib.write_publication_import_batch();
ALTER TABLE smartlib.publication_field_verification RENAME COLUMN import_item_id TO record_id;
ALTER TABLE smartlib.publication_verification_decision RENAME COLUMN import_item_id TO record_id;
ALTER TABLE smartlib.publication_verification_layer RENAME COLUMN import_item_id TO record_id;
ALTER TABLE smartlib.publication_fulltext_preverification RENAME COLUMN import_item_id TO record_id;
ALTER TABLE smartlib.publication_intake_record RENAME COLUMN duplicate_of_item_id TO duplicate_of_record_id;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM smartlib.publication_authorship WHERE cardinality(affiliation_organization_ids)>0) THEN
 RAISE EXCEPTION 'nonempty obsolete affiliation cache must be reconciled before removal';
 END IF;
END $$;
ALTER TABLE smartlib.publication_authorship DROP COLUMN affiliation_organization_ids;
ALTER TRIGGER publication_import_batch_updated_at ON smartlib.ingestion_batch RENAME TO ingestion_batch_updated_at;
ALTER TRIGGER publication_import_item_updated_at ON smartlib.ingestion_record RENAME TO ingestion_record_updated_at;
ALTER POLICY publication_import_batch_read ON smartlib.ingestion_batch RENAME TO ingestion_batch_read;
ALTER POLICY publication_import_batch_write ON smartlib.ingestion_batch RENAME TO ingestion_batch_write;
ALTER POLICY publication_import_item_read ON smartlib.ingestion_record RENAME TO ingestion_record_read;
ALTER POLICY publication_import_item_write ON smartlib.ingestion_record RENAME TO ingestion_record_write;
UPDATE smartlib.access_permission SET code='publication_intake.submit',name='提交论文入库记录'
WHERE code='publication_import.submit';
-- Domain changes must update the source occurrence timestamp without a view write trigger.
CREATE FUNCTION smartlib.touch_intake_record() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
BEGIN
 UPDATE smartlib.ingestion_record SET updated_at=clock_timestamp() WHERE record_id=NEW.record_id;
 RETURN NEW;
END $$;
CREATE TRIGGER publication_intake_updated AFTER UPDATE ON smartlib.publication_intake_record
FOR EACH ROW WHEN (OLD IS DISTINCT FROM NEW) EXECUTE FUNCTION smartlib.touch_intake_record();
CREATE TRIGGER representative_work_updated AFTER UPDATE ON smartlib.representative_work_submission
FOR EACH ROW WHEN (OLD IS DISTINCT FROM NEW) EXECUTE FUNCTION smartlib.touch_intake_record();
REVOKE ALL ON FUNCTION smartlib.touch_intake_record() FROM PUBLIC;
COMMENT ON TABLE smartlib.publication_intake_record IS 'Publication-specific verification authority. Applications access it and ingestion_record directly; no legacy intake view exists.';
RESET ROLE;
