from psycopg.types.json import Jsonb

from smartlib_platform.foundation.database import DbConnection

from .models import SourceCreate, SourceView


def list_sources(connection: DbConnection) -> list[SourceView]:
    rows = connection.execute(
        """SELECT source_system_id, code, name, owner_department, source_type,
                  authorization_state, metadata, created_at, updated_at
           FROM smartlib.source_system ORDER BY name"""
    ).fetchall()
    return [SourceView.model_validate(row) for row in rows]


def create_source(connection: DbConnection, command: SourceCreate) -> SourceView:
    row = connection.execute(
        """INSERT INTO smartlib.source_system
                  (code, name, owner_department, source_type, authorization_state, metadata)
           VALUES (%s, %s, %s, %s, %s, %s)
           RETURNING source_system_id, code, name, owner_department, source_type,
                     authorization_state, metadata, created_at, updated_at""",
        (
            command.code,
            command.name,
            command.owner_department,
            command.source_type,
            command.authorization_state,
            Jsonb(command.metadata),
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("source insert returned no row")
    return SourceView.model_validate(row)
