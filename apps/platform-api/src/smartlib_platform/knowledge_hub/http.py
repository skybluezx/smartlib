from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Query, UploadFile
from psycopg import IntegrityError
from psycopg.errors import InsufficientPrivilege

from smartlib_platform.audit.service import record_allowed

from . import catalog, service
from .models import (
    ApplicationCommand,
    AssetCommand,
    Command,
    DomainCommand,
    HubTable,
    LibraryCommand,
    LibraryRevision,
    LicenseCommand,
    RuleCommand,
    SchemaCommand,
    SettingCommand,
    SourceCommand,
    StateCommand,
)


def register(app, database, Context, request_context, require_permission):
    def execute(context, permission, fn, action=None):
        require_permission(context, permission)
        try:
            with database.transaction(context.actor_id) as connection:
                result = fn(connection)
                if action:
                    record_allowed(
                        connection,
                        actor_id=context.actor_id,
                        action="knowledge_hub." + action,
                        resource_type="knowledge_hub",
                        resource_id=str(result.get("id", "batch")),
                        trace_id=context.trace_id,
                        details={"reason": result.pop("_reason", "馆员工作台操作")},
                    )
                return result
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except service.ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except IntegrityError as exc:
            raise HTTPException(409, "编码或同月同机构记录重复，或引用对象不可用；本次操作已回滚") from exc
        except InsufficientPrivilege as exc:
            raise HTTPException(403, "当前身份无权维护此记录，请由记录负责人处理") from exc

    def write(context, command, handler, action=None):
        def save(c):
            c.execute("SELECT set_config('smartlib.change_reason',%s,true)", (command.reason,))
            result = handler(c, command, context.actor_id)
            result["_reason"] = command.reason
            return result

        return execute(context, "knowledge_hub.manage", save, action or handler.__name__)

    @app.get("/api/v1/knowledge-hub/workbench/options", tags=["knowledge-hub"])
    def options(context: Annotated[Context, Depends(request_context)]):
        return execute(context, "knowledge_hub.read", catalog.options)

    @app.get("/api/v1/knowledge-hub/workbench/{section}", response_model=HubTable, tags=["knowledge-hub"])
    def records(
        section: str,
        context: Annotated[Context, Depends(request_context)],
        q: str = "",
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    ):
        return execute(
            context,
            "knowledge_hub.audit.read" if section == "audit" else "knowledge_hub.read",
            lambda c: catalog.table(c, section, q, page, page_size),
        )

    @app.post("/api/v1/knowledge-hub/workbench/sources", tags=["knowledge-hub"], status_code=201)
    def source(command: SourceCommand, context: Annotated[Context, Depends(request_context)]):
        return write(context, command, service.create_source)

    @app.post("/api/v1/knowledge-hub/workbench/domains", tags=["knowledge-hub"], status_code=201)
    def domain(command: DomainCommand, context: Annotated[Context, Depends(request_context)]):
        return write(context, command, service.create_domain)

    @app.post("/api/v1/knowledge-hub/workbench/resources", tags=["knowledge-hub"], status_code=201)
    def asset(command: AssetCommand, context: Annotated[Context, Depends(request_context)]):
        return write(context, command, service.create_asset)

    @app.post("/api/v1/knowledge-hub/workbench/licenses", tags=["knowledge-hub"], status_code=201)
    def license_record(command: LicenseCommand, context: Annotated[Context, Depends(request_context)]):
        return write(context, command, service.create_license)

    @app.post("/api/v1/knowledge-hub/workbench/rules", tags=["knowledge-hub"], status_code=201)
    def rule(command: RuleCommand, context: Annotated[Context, Depends(request_context)]):
        return write(context, command, service.create_rule)

    @app.post("/api/v1/knowledge-hub/workbench/metadata", tags=["knowledge-hub"], status_code=201)
    def schema(command: SchemaCommand, context: Annotated[Context, Depends(request_context)]):
        return write(context, command, service.create_schema)

    @app.post("/api/v1/knowledge-hub/workbench/library", tags=["knowledge-hub"], status_code=201)
    def library(command: LibraryCommand, context: Annotated[Context, Depends(request_context)]):
        return write(context, command, service.create_library)

    @app.post("/api/v1/knowledge-hub/library/{record_id}/revision", tags=["knowledge-hub"])
    def revise(
        record_id: UUID, command: LibraryRevision, context: Annotated[Context, Depends(request_context)]
    ):
        return write(
            context,
            command,
            lambda c, cmd, actor: service.revise_library(c, record_id, cmd, actor),
            "library.revise",
        )

    @app.post("/api/v1/knowledge-hub/workbench/library/import", tags=["knowledge-hub"], status_code=201)
    async def library_import(file: UploadFile, context: Annotated[Context, Depends(request_context)]):
        require_permission(context, "knowledge_hub.manage")
        raw = await file.read(2_000_001)

        def save(c):
            records = service.parse_library_csv(raw)
            for record in records:
                service.create_library(c, record, context.actor_id)
            return {"count": len(records), "_reason": "馆务 CSV 原子批量导入"}

        return execute(context, "knowledge_hub.manage", save, "library.import")

    @app.post("/api/v1/knowledge-hub/workbench/applications", tags=["knowledge-hub"], status_code=201)
    def application(command: ApplicationCommand, context: Annotated[Context, Depends(request_context)]):
        return write(context, command, service.create_application)

    @app.post("/api/v1/knowledge-hub/workbench/settings", tags=["knowledge-hub"])
    def setting(command: SettingCommand, context: Annotated[Context, Depends(request_context)]):
        return write(context, command, service.save_setting)

    @app.post("/api/v1/knowledge-hub/workbench/{section}/{record_id}/state", tags=["knowledge-hub"])
    def state(
        section: str,
        record_id: UUID,
        command: StateCommand,
        context: Annotated[Context, Depends(request_context)],
    ):
        return write(
            context,
            command,
            lambda c, cmd, actor: service.change_state(c, section, record_id, cmd, actor),
            section + ".state",
        )

    @app.post("/api/v1/knowledge-hub/workbench/rules/{rule_id}/run", tags=["knowledge-hub"])
    def run(rule_id: UUID, command: Command, context: Annotated[Context, Depends(request_context)]):
        return write(context, command, lambda c, cmd, actor: service.run_rule(c, rule_id, actor), "rule.run")

    @app.get("/api/v1/knowledge-hub/quality-runs/{rule_id}", tags=["knowledge-hub"])
    def runs(rule_id: UUID, context: Annotated[Context, Depends(request_context)]):
        return execute(
            context,
            "knowledge_hub.read",
            lambda c: c.execute(
                """SELECT quality_run_id id,run_state,
           observed_value,expected_value,started_at,details FROM smartlib.quality_run
           WHERE quality_rule_id=%s ORDER BY started_at DESC LIMIT 20""",
                (rule_id,),
            ).fetchall(),
        )

    @app.get("/api/v1/knowledge-hub/library-analysis", tags=["knowledge-hub"])
    def library_analysis(
        context: Annotated[Context, Depends(request_context)], metric_code: str = "", organization: str = ""
    ):
        def read(c):
            metrics = c.execute("""SELECT metric_code,metric_name,unit,count(*) records FROM smartlib.library_metric_record
              GROUP BY 1,2,3 ORDER BY metric_name""").fetchall()
            rows = (
                c.execute(
                    """SELECT period,organization,value,unit,source_reference FROM smartlib.library_metric_record
              WHERE metric_code=%s AND (%s='' OR organization=%s) ORDER BY period,organization""",
                    (metric_code, organization, organization),
                ).fetchall()
                if metric_code
                else []
            )
            return {
                "metrics": metrics,
                "items": rows,
                "note": "按月、按机构分别展示，不跨指标或机构直接求和；未登记月份保持缺失。",
            }

        return execute(context, "knowledge_hub.read", read)
