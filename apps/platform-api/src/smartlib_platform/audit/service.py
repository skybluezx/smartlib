from uuid import UUID

from psycopg.types.json import Jsonb

from smartlib_platform.foundation.database import DbConnection


def record_allowed(
    connection: DbConnection,
    *,
    actor_id: UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    trace_id: str,
    details: dict[str, object] | None = None,
) -> None:
    connection.execute(
        """INSERT INTO audit.audit_event
                  (actor_id, action, resource_type, resource_id, decision, trace_id, details)
             VALUES (%s, %s, %s, %s, 'allowed', %s, %s)""",
        (actor_id, action, resource_type, resource_id, trace_id, Jsonb(details or {})),
    )
