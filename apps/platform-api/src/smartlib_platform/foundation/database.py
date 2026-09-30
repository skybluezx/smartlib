from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

type DbRow = dict[str, Any]
type DbConnection = Connection[DbRow]
request_change_context: ContextVar[tuple[str, str] | None] = ContextVar('request_change_context', default=None)


class Database:
    def __init__(self, url: str) -> None:
        self.pool: ConnectionPool[DbConnection] = ConnectionPool(
            conninfo=url,
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=10,
            open=False,
        )

    def open(self) -> None:
        self.pool.open(wait=True)

    def close(self) -> None:
        self.pool.close()

    @contextmanager
    def transaction(self, actor_id: UUID, *, repeatable_read: bool = False) -> Iterator[DbConnection]:
        with self.pool.connection() as connection, connection.transaction():
            if repeatable_read:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            request_context = request_change_context.get()
            if request_context:
                connection.execute("SELECT set_config('smartlib.trace_id',%s,true), set_config('smartlib.change_source',%s,true)", request_context)
            yield connection

    def ping(self) -> bool:
        with self.pool.connection() as connection:
            row = connection.execute("SELECT 1 AS ok").fetchone()
            return row is not None and row["ok"] == 1
