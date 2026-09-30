from uuid import UUID

from smartlib_platform.foundation.database import DbConnection


def actor_permissions(connection: DbConnection, actor_id: UUID) -> list[str]:
    rows = connection.execute(
        """SELECT DISTINCT permission.code
             FROM smartlib.actor_role_assignment assignment
             JOIN smartlib.access_role_permission role_permission
               ON role_permission.role_id = assignment.role_id
             JOIN smartlib.access_permission permission
               ON permission.permission_id = role_permission.permission_id
            WHERE assignment.actor_id = %s
              AND assignment.valid_from <= clock_timestamp()
              AND assignment.valid_to > clock_timestamp()
            ORDER BY permission.code""",
        (actor_id,),
    ).fetchall()
    return [row["code"] for row in rows]


def actor_has_permission(connection: DbConnection, actor_id: UUID, permission: str) -> bool:
    row = connection.execute(
        "SELECT smartlib.actor_has_permission(%s, %s) AS allowed",
        (actor_id, permission),
    ).fetchone()
    return bool(row and row["allowed"])
