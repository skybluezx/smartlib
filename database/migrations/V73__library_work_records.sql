SET ROLE smartlib_owner;
CREATE TABLE smartlib.library_work_batch (
 batch_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL DEFAULT clock_timestamp()+interval '24 hours',
 filename text NOT NULL, file_hash text NOT NULL, mode text NOT NULL CHECK(mode IN ('real','demo')),
 state text NOT NULL DEFAULT 'preview' CHECK(state IN ('preview','imported')),
 preview jsonb NOT NULL, committed_at timestamptz,
 parser_version text NOT NULL DEFAULT 'library-work-v1'
);
CREATE UNIQUE INDEX library_work_import_once ON smartlib.library_work_batch(created_by,file_hash,mode)
 WHERE state='imported';
CREATE TABLE smartlib.library_work_record (
 record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), batch_id uuid REFERENCES smartlib.library_work_batch,
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 category text NOT NULL, title text NOT NULL CHECK(btrim(title)<>''),
 mode text NOT NULL CHECK(mode IN ('real','demo')),
 state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','withdrawn')),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 year integer, month integer CHECK(month BETWEEN 1 AND 12),
 date_precision text NOT NULL CHECK(date_precision IN ('day','month','year','unknown')),
 department text NOT NULL DEFAULT '', audience integer CHECK(audience>=0),
 fields jsonb NOT NULL, warnings jsonb NOT NULL DEFAULT '[]', origin jsonb NOT NULL,
 content_hash text NOT NULL
);
CREATE INDEX library_work_filter ON smartlib.library_work_record(created_by,mode,category,year,state);
CREATE TABLE smartlib.library_work_revision (
 revision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 record_id uuid NOT NULL REFERENCES smartlib.library_work_record,
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 version integer NOT NULL, reason text NOT NULL, snapshot jsonb NOT NULL,
 UNIQUE(record_id,version)
);
DO $block$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['library_work_batch','library_work_record','library_work_revision'] LOOP
  EXECUTE format('ALTER TABLE smartlib.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE smartlib.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY library_work_read ON smartlib.%I FOR SELECT TO smartlib_app USING(created_by=smartlib.current_actor_id() AND smartlib.actor_has_permission(smartlib.current_actor_id(),''knowledge_hub.read''))',t);
  EXECUTE format('CREATE POLICY library_work_insert ON smartlib.%I FOR INSERT TO smartlib_app WITH CHECK(created_by=smartlib.current_actor_id() AND smartlib.actor_has_permission(smartlib.current_actor_id(),''knowledge_hub.manage''))',t);
  EXECUTE format('GRANT SELECT,INSERT ON smartlib.%I TO smartlib_app',t);
  IF t<>'library_work_revision' THEN
   EXECUTE format('CREATE POLICY library_work_update ON smartlib.%I FOR UPDATE TO smartlib_app USING(created_by=smartlib.current_actor_id() AND smartlib.actor_has_permission(smartlib.current_actor_id(),''knowledge_hub.manage'')) WITH CHECK(created_by=smartlib.current_actor_id())',t);
   EXECUTE format('GRANT UPDATE ON smartlib.%I TO smartlib_app',t);
  END IF;
 END LOOP;
END $block$;
CREATE FUNCTION smartlib.guard_library_work_record() RETURNS trigger LANGUAGE plpgsql AS $body$
BEGIN
 IF NEW.mode<>OLD.mode OR NEW.created_by<>OLD.created_by OR NEW.batch_id IS DISTINCT FROM OLD.batch_id THEN
  RAISE EXCEPTION 'library record provenance is immutable';
 END IF;
 RETURN NEW;
END $body$;
CREATE TRIGGER library_work_guard BEFORE UPDATE ON smartlib.library_work_record
 FOR EACH ROW EXECUTE FUNCTION smartlib.guard_library_work_record();
RESET ROLE;
