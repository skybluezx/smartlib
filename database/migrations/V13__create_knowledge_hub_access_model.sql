SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

CREATE TABLE smartlib.access_role (
    role_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_.-]{1,63}$'),
    name text NOT NULL CHECK (btrim(name) <> ''),
    description text,
    built_in boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE smartlib.access_permission (
    permission_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    name text NOT NULL CHECK (btrim(name) <> ''),
    risk_level text NOT NULL DEFAULT 'normal'
        CHECK (risk_level IN ('read', 'normal', 'high')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE smartlib.access_role_permission (
    role_id uuid NOT NULL REFERENCES smartlib.access_role(role_id),
    permission_id uuid NOT NULL REFERENCES smartlib.access_permission(permission_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE smartlib.actor_role_assignment (
    actor_id uuid NOT NULL,
    role_id uuid NOT NULL REFERENCES smartlib.access_role(role_id),
    data_scope jsonb NOT NULL DEFAULT '{"scope":"all"}'::jsonb
        CHECK (jsonb_typeof(data_scope) = 'object'),
    assigned_by uuid NOT NULL,
    assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_to timestamptz NOT NULL DEFAULT 'infinity',
    PRIMARY KEY (actor_id, role_id),
    CHECK (valid_from < valid_to)
);

INSERT INTO smartlib.access_role (code, name, description, built_in) VALUES
    ('knowledge_admin', '知识中台管理员', '知识中台全部管理权限', true),
    ('publication_reviewer', '论文审核员', '查看并处理论文核验任务', true),
    ('system_observer', '系统观察员', '只读查看运行状态和审核记录', true);

INSERT INTO smartlib.access_permission (code, name, risk_level) VALUES
    ('knowledge_hub.read', '查看知识中台', 'read'),
    ('publication_verification.read', '查看论文核验', 'read'),
    ('publication_verification.decide', '确认或驳回论文核验', 'normal'),
    ('knowledge_hub.audit.read', '查看知识中台审计记录', 'read');

INSERT INTO smartlib.access_role_permission (role_id, permission_id)
SELECT role.role_id, permission.permission_id
  FROM smartlib.access_role role
 CROSS JOIN smartlib.access_permission permission
 WHERE role.code = 'knowledge_admin'
    OR (role.code = 'publication_reviewer'
        AND permission.code IN (
            'knowledge_hub.read', 'publication_verification.read',
            'publication_verification.decide', 'knowledge_hub.audit.read'
        ))
    OR (role.code = 'system_observer'
        AND permission.code IN (
            'knowledge_hub.read', 'publication_verification.read',
            'knowledge_hub.audit.read'
        ));

CREATE FUNCTION smartlib.actor_has_permission(selected_actor_id uuid, selected_permission text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
    SELECT EXISTS (
        SELECT 1
          FROM smartlib.actor_role_assignment assignment
          JOIN smartlib.access_role_permission role_permission
            ON role_permission.role_id = assignment.role_id
          JOIN smartlib.access_permission permission
            ON permission.permission_id = role_permission.permission_id
         WHERE assignment.actor_id = selected_actor_id
           AND permission.code = selected_permission
           AND assignment.valid_from <= clock_timestamp()
           AND assignment.valid_to > clock_timestamp()
    )
$function$;

GRANT SELECT ON smartlib.access_role, smartlib.access_permission,
    smartlib.access_role_permission, smartlib.actor_role_assignment
TO smartlib_app, smartlib_readonly;
GRANT EXECUTE ON FUNCTION smartlib.actor_has_permission(uuid, text) TO smartlib_app;

ALTER TABLE smartlib.actor_role_assignment ENABLE ROW LEVEL SECURITY;
CREATE POLICY actor_role_assignment_self_read ON smartlib.actor_role_assignment
FOR SELECT TO smartlib_app, smartlib_readonly
USING (actor_id = smartlib.current_actor_id());

COMMENT ON TABLE smartlib.actor_role_assignment IS
    'Backend-enforced, time-bounded actor roles; UI visibility is never the authorization boundary';
COMMENT ON FUNCTION smartlib.actor_has_permission(uuid, text) IS
    'Central knowledge-hub permission decision used by API endpoints';

RESET ROLE;
