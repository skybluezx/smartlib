from uuid import UUID

from smartlib_platform.foundation.database import DbConnection

from .models import JobView


def get_job(connection: DbConnection, job_id: UUID) -> JobView | None:
    row = connection.execute(
        """SELECT job_id, job_type, state, progress, requested_by, trace_id,
                  failure_code, failure_message, created_at, updated_at
             FROM smartlib.async_job WHERE job_id = %s""",
        (job_id,),
    ).fetchone()
    return JobView.model_validate(row) if row else None
