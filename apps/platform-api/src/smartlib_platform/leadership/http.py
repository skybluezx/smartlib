from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException
from psycopg import IntegrityError

from smartlib_platform.access.service import actor_permissions
from smartlib_platform.audit.service import record_allowed
from smartlib_platform.graph_analytics.custom_scopes import get_custom_scope
from smartlib_platform.graph_analytics.service import get_scholar_graph_analytics

from . import service
from .models import MatterCommand, ReportCommand, Scope


def authorization(permissions, environment, write=False):
    required = "leadership.write" if write else "leadership.read"
    verified = required in permissions
    preview = environment == "development" and "knowledge_hub.manage" in permissions
    if not verified and not preview:
        raise HTTPException(403, "当前身份未获学校领导工作台权限，请由管理员按岗位授权")
    return verified


def register(app, database, Context, request_context, settings, execute_custom):
    def run(context, fn, write=False, action=None):
        try:
            with database.transaction(context.actor_id, repeatable_read=True) as c:
                permissions = actor_permissions(c, context.actor_id)
                verified = authorization(permissions, settings.environment, write)
                result = fn(c, verified, permissions)
                if action:
                    record_allowed(
                        c,
                        actor_id=context.actor_id,
                        action="leadership." + action,
                        resource_type="leadership_record",
                        resource_id=str(result["record_id"]),
                        trace_id=context.trace_id,
                        details={"view": "school_leader"},
                    )
                return result
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except IntegrityError as exc:
            raise HTTPException(409, "记录已变化或引用不可用，请刷新后重试") from exc

    def resolve(c, scope, context):
        custom, name = None, None
        if scope.custom_scope_id:
            saved = get_custom_scope(c, scope.custom_scope_id)
            if saved is None:
                raise LookupError("自定义范围不存在或无权读取")
            custom, _ = execute_custom(c, saved.graph_query, context)
            name = saved.name
        return service.paper_ids(c, scope, custom), name

    @app.get("/api/v1/leadership/session", tags=["leadership"])
    def session(context: Annotated[Context, Depends(request_context)]):
        return run(
            context,
            lambda c, verified, permissions: {
                "actor_id": str(context.actor_id),
                "role": "学校领导",
                "role_verified": verified,
                "mode": "authorized" if verified else "development_preview",
                "can_write": "leadership.write" in permissions
                or (settings.environment == "development" and "knowledge_hub.manage" in permissions),
            },
        )

    @app.post("/api/v1/leadership/summary", tags=["leadership"])
    def summary(scope: Scope, context: Annotated[Context, Depends(request_context)]):
        def read(c, *_):
            ids, name = resolve(c, scope, context)
            return service.dashboard(c, scope, ids, name)

        return run(context, read)

    @app.get("/api/v1/leadership/resources", tags=["leadership"])
    def resources(context: Annotated[Context, Depends(request_context)]):
        return run(context, lambda c, *_: service.resources(c))

    @app.get("/api/v1/leadership/records", tags=["leadership"])
    def records(
        context: Annotated[Context, Depends(request_context)], kind: Literal["matter", "report"] = "matter"
    ):
        return run(context, lambda c, *_: service.list_records(c, kind))

    @app.get("/api/v1/leadership/records/{record_id}", tags=["leadership"])
    def record(record_id: UUID, context: Annotated[Context, Depends(request_context)]):
        return run(context, lambda c, *_: service.get_record(c, record_id))

    @app.post("/api/v1/leadership/matters", status_code=201, tags=["leadership"])
    def matter(command: MatterCommand, context: Annotated[Context, Depends(request_context)]):
        return run(
            context, lambda c, *_: service.save_matter(c, command, context.actor_id), True, "matter.save"
        )

    @app.post("/api/v1/leadership/reports", status_code=201, tags=["leadership"])
    def report(command: ReportCommand, context: Annotated[Context, Depends(request_context)]):
        def create(c, *_):
            ids, name = resolve(c, command.scope, context)
            summary = service.dashboard(c, command.scope, ids, name)
            result = get_scholar_graph_analytics(
                c,
                graph_backend=settings.graph_backend,
                selected_module="journals",
                custom_publication_ids=ids,
            )
            return service.save_report(c, command, context.actor_id, summary, result.journals)

        return run(context, create, True, "report.save")
