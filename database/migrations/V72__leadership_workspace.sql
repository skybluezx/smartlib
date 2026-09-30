SET ROLE smartlib_owner;

-- Define the role; do not assign it to any real user or broaden fact visibility.
INSERT INTO smartlib.access_role(code,name,description,built_in)
VALUES ('school_leader','学校领导','决策看板和本人决策材料；事实读取仍受原有数据权限约束',true);
INSERT INTO smartlib.access_permission(code,name,risk_level) VALUES
 ('leadership.read','查看领导工作台','read'),
 ('leadership.write','维护本人决策事项与报告','normal');
INSERT INTO smartlib.access_role_permission(role_id,permission_id)
SELECT r.role_id,p.permission_id FROM smartlib.access_role r CROSS JOIN smartlib.access_permission p
WHERE r.code='school_leader' AND p.code IN ('leadership.read','leadership.write');

CREATE TABLE smartlib.leadership_record (
 record_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 kind text NOT NULL CHECK(kind IN ('matter','report')),
 category text NOT NULL CHECK(category IN ('recruitment','cultivation','teams','transfer','research','disciplines','resources','overview')),
 title text NOT NULL CHECK(btrim(title)<>''),
 payload jsonb NOT NULL,
 object_ids uuid[] NOT NULL DEFAULT '{}',
 created_by uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 supersedes_id uuid UNIQUE REFERENCES smartlib.leadership_record(record_id),
 result_hash text
);
ALTER TABLE smartlib.leadership_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.leadership_record FORCE ROW LEVEL SECURITY;
CREATE POLICY leadership_record_read ON smartlib.leadership_record FOR SELECT TO smartlib_app,smartlib_readonly
USING(created_by=smartlib.current_actor_id() AND NOT EXISTS (
 SELECT 1 FROM unnest(object_ids) x(id) WHERE NOT EXISTS (
 SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=x.id)));
CREATE POLICY leadership_record_insert ON smartlib.leadership_record FOR INSERT TO smartlib_app
WITH CHECK(created_by=smartlib.current_actor_id() AND
 (smartlib.actor_has_permission(smartlib.current_actor_id(),'leadership.write') OR
  smartlib.actor_has_permission(smartlib.current_actor_id(),'knowledge_hub.manage')));
GRANT SELECT,INSERT ON smartlib.leadership_record TO smartlib_app;
GRANT SELECT ON smartlib.leadership_record TO smartlib_readonly;
RESET ROLE;
