from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, File, Form, HTTPException, Query, UploadFile
from psycopg import IntegrityError

from smartlib_platform.audit.service import record_allowed
from smartlib_platform.knowledge_hub.service import ConflictError

from . import service
from .models import ImportCommit, WorkCommand, WorkRevision
from .parser import CATALOG, MAX_UPLOAD


def register(app, database, Context, request_context, require_permission):
    prefix = "/api/v1/knowledge-hub/library-work"

    def run(ctx, fn, action=None, reason=""):
        require_permission(ctx, "knowledge_hub.manage" if action else "knowledge_hub.read")
        try:
            with database.transaction(ctx.actor_id) as c:
                result = fn(c)
                if action:
                    record_allowed(
                        c,
                        actor_id=ctx.actor_id,
                        action="library_work." + action,
                        resource_type="library_work",
                        resource_id=str(result.get("id", "batch")),
                        trace_id=ctx.trace_id,
                        details={"reason": reason},
                    )
                return result
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except IntegrityError as exc:
            raise HTTPException(409, "记录冲突，操作已整体回滚") from exc

    @app.get(prefix + "/catalog", tags=["library-work"])
    def catalog(ctx: Annotated[Context, Depends(request_context)]):
        return run(ctx, lambda _: CATALOG)

    @app.get(prefix + "/records", tags=["library-work"])
    def records(
        ctx: Annotated[Context, Depends(request_context)],
        mode: Literal["real", "demo"] = "real",
        category: str = "",
        year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
        department: str = "",
        q: Annotated[str, Query(max_length=200)] = "",
        state: Literal["active", "withdrawn", "all"] = "active",
        page: Annotated[int, Query(ge=1)] = 1,
    ):
        return run(ctx, lambda c: service.listing(c, mode, category, year, department, q, state, page))

    @app.get(prefix + "/overview", tags=["library-work"])
    def overview(
        ctx: Annotated[Context, Depends(request_context)],
        mode: Literal["real", "demo"] = "real",
        category: str = "",
        year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
        department: str = "",
        q: Annotated[str, Query(max_length=200)] = "",
        state: Literal["active", "withdrawn", "all"] = "active",
    ):
        return run(ctx, lambda c: service.overview(c, mode, category, year, department, q, state))

    @app.get(prefix + "/records/{identifier}", tags=["library-work"])
    def detail(identifier: UUID, ctx: Annotated[Context, Depends(request_context)]):
        return run(ctx, lambda c: service.detail(c, identifier))

    @app.post(prefix + "/records", tags=["library-work"], status_code=201)
    def create(command: WorkCommand, ctx: Annotated[Context, Depends(request_context)]):
        return run(ctx, lambda c: service.create(c, ctx.actor_id, command), "create", command.reason)

    @app.post(prefix + "/records/{identifier}/revision", tags=["library-work"])
    def revision(identifier: UUID, command: WorkRevision, ctx: Annotated[Context, Depends(request_context)]):
        return run(
            ctx, lambda c: service.revise(c, ctx.actor_id, identifier, command), "revise", command.reason
        )

    @app.post(prefix + "/preview", tags=["library-work"])
    async def preview(
        ctx: Annotated[Context, Depends(request_context)],
        file: Annotated[UploadFile, File()],
        mode: Annotated[Literal["real", "demo"], Form()],
        category: Annotated[str, Form()] = "",
    ):
        require_permission(ctx, "knowledge_hub.manage")
        data = await file.read(MAX_UPLOAD + 1)
        await file.close()
        return run(
            ctx,
            lambda c: service.preview(
                c, ctx.actor_id, (file.filename or "upload")[:255], data, mode, category
            ),
            "preview",
            "工作表导入预检，仅暂存，不写入业务台账",
        )

    @app.get(prefix + "/batches", tags=["library-work"])
    def batches(ctx: Annotated[Context, Depends(request_context)], mode: Literal["real", "demo"] = "real"):
        return run(ctx, lambda c: service.batches(c, mode))

    @app.get(prefix + "/batches/{identifier}", tags=["library-work"])
    def batch(identifier: UUID, ctx: Annotated[Context, Depends(request_context)]):
        return run(ctx, lambda c: service.batch_detail(c, identifier))

    @app.post(prefix + "/batches/{identifier}/commit", tags=["library-work"])
    def commit(identifier: UUID, command: ImportCommit, ctx: Annotated[Context, Depends(request_context)]):
        return run(
            ctx, lambda c: service.commit(c, ctx.actor_id, identifier, command), "import", command.reason
        )
