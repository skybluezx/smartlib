SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

INSERT INTO smartlib.access_permission (code,name,risk_level)
VALUES ('knowledge_hub.manage','维护知识中台业务配置与台账','normal');
INSERT INTO smartlib.access_role_permission(role_id,permission_id)
SELECT r.role_id,p.permission_id FROM smartlib.access_role r,smartlib.access_permission p
WHERE r.code='knowledge_admin' AND p.code='knowledge_hub.manage';

CREATE TABLE smartlib.hub_application (
 application_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 code text NOT NULL UNIQUE CHECK(code ~ '^[a-z][a-z0-9_-]{1,63}$'),
 name text NOT NULL CHECK(btrim(name)<>''),
 description text NOT NULL DEFAULT '',
 entry_path text NOT NULL CHECK(entry_path LIKE '/%' AND entry_path NOT LIKE '//%'),
 owner_department text NOT NULL,
 lifecycle_state text NOT NULL DEFAULT 'draft' CHECK(lifecycle_state IN ('draft','active','paused','retired')),
 version bigint NOT NULL DEFAULT 1,
 created_by uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE smartlib.library_metric_record (
 record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 metric_code text NOT NULL CHECK(metric_code ~ '^[a-z][a-z0-9_.-]{1,63}$'),
 metric_name text NOT NULL CHECK(btrim(metric_name)<>''),
 period date NOT NULL CHECK(EXTRACT(DAY FROM period)=1), organization text NOT NULL CHECK(btrim(organization)<>''),
 value numeric NOT NULL CHECK(value>=0 AND value<'Infinity'::numeric),
 unit text NOT NULL CHECK(btrim(unit)<>''),
 source_reference text NOT NULL CHECK(btrim(source_reference)<>''),
 note text NOT NULL DEFAULT '', version bigint NOT NULL DEFAULT 1,
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(metric_code,period,organization)
);
CREATE TABLE smartlib.hub_setting (
 setting_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 code text NOT NULL UNIQUE CHECK(code IN ('library_name','service_contact','workbench_notice')),
 value text NOT NULL CHECK(length(value)<=2000),
 version bigint NOT NULL DEFAULT 1,
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $block$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['hub_application','library_metric_record','hub_setting'] LOOP
  EXECUTE format('ALTER TABLE smartlib.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY hub_read ON smartlib.%I FOR SELECT TO smartlib_app USING (smartlib.actor_has_permission(smartlib.current_actor_id(),''knowledge_hub.read''))',t);
  EXECUTE format('CREATE POLICY hub_write ON smartlib.%I FOR ALL TO smartlib_app USING (smartlib.actor_has_permission(smartlib.current_actor_id(),''knowledge_hub.manage'')) WITH CHECK (smartlib.actor_has_permission(smartlib.current_actor_id(),''knowledge_hub.manage''))',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE ON smartlib.%I TO smartlib_app',t);
  EXECUTE format('CREATE TRIGGER hub_updated BEFORE UPDATE ON smartlib.%I FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at()',t);
 END LOOP;
END $block$;
RESET ROLE;
