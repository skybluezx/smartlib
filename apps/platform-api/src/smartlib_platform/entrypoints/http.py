from smartlib_platform.graph_analytics.models import AnalysisModule
from smartlib_platform.leadership.http import register as register_leadership_routes
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from psycopg import IntegrityError
from psycopg.types.json import Jsonb
from starlette.middleware.base import RequestResponseEndpoint

from smartlib_platform.access.service import actor_has_permission, actor_permissions
from smartlib_platform.knowledge.research_http import register as register_research_routes
from smartlib_platform.audit.service import record_allowed
from smartlib_platform.changes import history
from smartlib_platform.changes import service as changes
from smartlib_platform.foundation.config import Settings
from smartlib_platform.foundation.database import Database, DbConnection, request_change_context
from smartlib_platform.foundation.types import ObjectType
from smartlib_platform.fulltext import extract_pdf
from smartlib_platform.governance.models import (
    DataAssetTrace,
    GovernanceAuditEventView,
    GovernanceDashboard,
    GovernanceSummary,
    KnowledgeObjectProvenanceTrace,
    LicenseGrantView,
    QualityIssueView,
    ReviewTaskCreate,
    ReviewTaskDecision,
    ReviewTaskView,
)
from smartlib_platform.governance.service import (
    create_review_task,
    decide_review_task,
    get_data_asset_trace,
    get_governance_dashboard,
    get_governance_summary,
    get_knowledge_object_provenance,
    list_governance_audit_events,
    list_license_grants,
    list_quality_issues,
    list_review_tasks,
)
from smartlib_platform.graph_analytics.models import (
    AnalysisSaveCommand, SavedAnalysis, SavedAnalysisDetail,
)
from smartlib_platform.graph_analytics.saved import get_analysis, list_analyses, save_analysis
from smartlib_platform.graph_analytics.planning import (
    PlanningCommand, PlanningRecord, add_record, list_records, parse_application_csv,
)
from smartlib_platform.graph.errors import (
    GraphAuthorizationInvariantError,
    GraphBackendUnavailable,
)
from smartlib_platform.graph.hugegraph import CustomGraphQueryRejected, HugeGraphAdapter
from smartlib_platform.graph.models import (
    GraphAccessContext,
    NeighborhoodCommand,
    NeighborhoodResult,
    PathCommand,
    PathResult,
    RelationExplanation,
)
from smartlib_platform.graph.postgres import PostgresGraphAdapter
from smartlib_platform.graph.service import (
    explain_relation,
    find_knowledge_paths,
    get_knowledge_neighborhood,
)
from smartlib_platform.graph_analytics.custom_scopes import (
    CustomScopeNameConflictError,
    create_custom_scope,
    delete_custom_scope,
    execute_custom_scope,
    get_custom_scope,
    list_custom_scopes,
    mark_custom_scope_executed,
)
from smartlib_platform.graph_analytics.models import (
    CustomGraphAnalyticsCommand,
    CustomGraphScopeCreate,
    CustomGraphScopePreview,
    CustomGraphScopeQuery,
    GraphAnalysisScopeOptions,
    SavedCustomGraphScope,
    ScholarGraphAnalytics,
)
from smartlib_platform.graph_analytics.service import (
    get_graph_analysis_scope_options,
    get_scholar_graph_analytics,
)
from smartlib_platform.ingestion.models import IngestionCreate, IngestionResult
from smartlib_platform.ingestion.service import receive_batch
from smartlib_platform.journal_metrics.models import (
    JournalMetricReleaseView,
    PublicationJournalMetricView,
)
from smartlib_platform.journal_metrics.service import (
    list_journal_metric_releases,
    list_publication_journal_metrics,
)
from smartlib_platform.knowledge.models import (
    KnowledgeObjectCreate,
    KnowledgeObjectDetailView,
    KnowledgeObjectPage,
    KnowledgeObjectView,
    OrganizationHierarchyOptions,
    ProjectKindOptions,
)
from smartlib_platform.knowledge.service import (
    create_object,
    get_object,
    get_object_detail,
    get_organization_hierarchy_options,
    get_project_kind_options,
    get_publication_resource_reference,
    list_object_catalog,
    list_objects,
)
from smartlib_platform.operations.models import JobView
from smartlib_platform.operations.service import get_job
from smartlib_platform.publications.incremental import (
    decide_publication_supplement,
    get_incremental_status,
    list_publication_fulltexts,
    list_publication_supplements,
    submit_publication_supplement,
)
from smartlib_platform.publications.intake import (
    import_publication_records,
    records_from_csv,
    records_from_xlsx,
)
from smartlib_platform.publications.models import (
    FulltextSupplementInput,
    KnowledgeHubOverview,
    KnowledgeHubSession,
    PublicationFulltextResourceView,
    PublicationFulltextUploadResult,
    PublicationImportCreate,
    PublicationImportResult,
    PublicationIncrementalStatus,
    PublicationSupplementCreate,
    PublicationSupplementDecisionCommand,
    PublicationSupplementView,
    PublicationVerificationDecisionCommand,
    PublicationVerificationDecisionResult,
    PublicationVerificationDetail,
    PublicationVerificationPage,
)
from smartlib_platform.publications.provenance import (
    PublicationRelationCreate,
    PublicationRelationView,
    create_publication_relation,
)
from smartlib_platform.publications.service import (
    VerificationStateConflict,
    decide_publication_verification,
    get_knowledge_hub_overview,
    get_publication_verification,
    list_publication_verifications,
)
from smartlib_platform.relations.models import (
    EvidenceCreate,
    EvidenceView,
    RelationCreate,
    RelationView,
)
from smartlib_platform.relations.service import create_evidence, create_relation
from smartlib_platform.scholars.models import (
    ScholarEvidenceBundle,
    ScholarProfile,
    ScholarSummary,
)
from smartlib_platform.scholars.service import (
    get_scholar_evidence,
    get_scholar_profile,
    list_scholars,
    resolve_scholar_object_id,
)
from smartlib_platform.search.errors import (
    InvalidSearchCursor,
    SearchAuthorizationInvariantError,
    SearchBackendUnavailable,
    SearchModeUnavailable,
)
from smartlib_platform.search.models import SearchAccessContext, SearchCommand, SearchResult
from smartlib_platform.search.opensearch import OpenSearchAdapter
from smartlib_platform.search.postgres import PostgresSearchAdapter
from smartlib_platform.search.service import search_knowledge
from smartlib_platform.source.models import SourceCreate, SourceView
from smartlib_platform.source.service import create_source, list_sources
from smartlib_platform.storage.s3 import (
    InvalidFulltextFile,
    ObjectRangeNotSatisfiable,
    ObjectStoreUnavailable,
    S3ObjectStore,
    inspect_pdf,
)

settings = Settings.from_env()
database = Database(settings.database_url)


@dataclass(frozen=True)
class RequestContext:
    actor_id: UUID
    trace_id: str
    purpose: str


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    database.open()
    yield
    database.close()


app = FastAPI(
    title="SmartLib Platform API",
    version="1.0.0-alpha.20",
    description="SmartLib 权威能力层; 所有渠道共享相同领域、RLS、审计和事件语义。",
    lifespan=lifespan,
)


@app.middleware("http")
async def trace_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
    trace_id = request.headers.get("x-trace-id") or str(uuid4())
    request.state.trace_id = trace_id
    token = request_change_context.set((trace_id, request.method + ' ' + request.url.path))
    try:
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response
    finally:
        request_change_context.reset(token)


def request_context(
    request: Request,
    x_smartlib_actor_id: Annotated[UUID | None, Header()] = None,
) -> RequestContext:
    if settings.environment != "development" and x_smartlib_actor_id is None:
        raise HTTPException(status_code=401, detail="authenticated actor required")
    return RequestContext(
        x_smartlib_actor_id or settings.dev_actor_id,
        request.state.trace_id,
        "interactive_search",
    )


def require_knowledge_hub_permission(context: RequestContext, permission: str) -> None:
    with database.transaction(context.actor_id) as connection:
        allowed = actor_has_permission(connection, context.actor_id, permission)
        if not allowed:
            connection.execute(
                """INSERT INTO audit.audit_event
                          (actor_id, action, resource_type, resource_id, decision, trace_id, details)
                     VALUES (%s, 'knowledge_hub.authorization', 'permission', %s,
                             'denied', %s, %s)""",
                (
                    context.actor_id,
                    permission,
                    context.trace_id,
                    Jsonb({"required_permission": permission}),
                ),
            )
    if not allowed:
        raise HTTPException(status_code=403, detail="knowledge hub permission required")


_SINGLE_BYTE_RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


def _validated_pdf_range(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    match = _SINGLE_BYTE_RANGE.fullmatch(normalized)
    if match is None or not any(match.groups()):
        raise HTTPException(status_code=416, detail="invalid PDF byte range")
    return normalized


def _storage_object_key(storage_uri: str) -> str:
    parsed = urlsplit(storage_uri)
    key = parsed.path.lstrip("/")
    if parsed.scheme != "s3" or parsed.netloc != settings.s3_bucket or not key:
        raise HTTPException(status_code=500, detail="fulltext storage reference is invalid")
    return key


from smartlib_platform.knowledge_hub.http import register as register_hub_routes

register_research_routes(app, database, RequestContext, request_context, require_knowledge_hub_permission)
register_hub_routes(app, database, RequestContext, request_context, require_knowledge_hub_permission)
from smartlib_platform.library_work.http import register as register_library_work_routes
register_library_work_routes(app, database, RequestContext, request_context, require_knowledge_hub_permission)


@app.exception_handler(IntegrityError)
async def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"code": "conflict", "detail": str(exc.diag.message_primary)},
    )


@app.exception_handler(InvalidSearchCursor)
async def invalid_search_cursor(_: Request, exc: InvalidSearchCursor) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": "invalid_search_cursor", "detail": str(exc)})


@app.exception_handler(SearchModeUnavailable)
async def search_mode_unavailable(_: Request, exc: SearchModeUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"code": "search_mode_unavailable", "detail": str(exc)},
    )


@app.exception_handler(SearchBackendUnavailable)
async def search_backend_unavailable(_: Request, __: SearchBackendUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"code": "search_backend_unavailable", "detail": "search backend unavailable"},
    )


@app.exception_handler(SearchAuthorizationInvariantError)
async def search_authorization_invariant(_: Request, __: SearchAuthorizationInvariantError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"code": "search_scope_violation", "detail": "search result rejected"},
    )


@app.exception_handler(GraphBackendUnavailable)
async def graph_backend_unavailable(_: Request, __: GraphBackendUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"code": "graph_backend_unavailable", "detail": "graph backend unavailable"},
    )


@app.exception_handler(GraphAuthorizationInvariantError)
async def graph_authorization_invariant(_: Request, __: GraphAuthorizationInvariantError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"code": "graph_scope_violation", "detail": "graph result rejected"},
    )


@app.get("/health/live", tags=["health"], operation_id="health_live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"], operation_id="health_ready")
def health_ready() -> dict[str, str]:
    if not database.ping():
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}


@app.get("/api/v1/sources", response_model=list[SourceView], tags=["sources"], operation_id="list_sources")
def sources_index(context: Annotated[RequestContext, Depends(request_context)]) -> list[SourceView]:
    with database.transaction(context.actor_id) as connection:
        return list_sources(connection)


@app.post(
    "/api/v1/sources",
    response_model=SourceView,
    status_code=status.HTTP_201_CREATED,
    tags=["sources"],
    operation_id="create_source",
)
def sources_create(
    command: SourceCreate,
    context: Annotated[RequestContext, Depends(request_context)],
) -> SourceView:
    with database.transaction(context.actor_id) as connection:
        result = create_source(connection, command)
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="source.create",
            resource_type="source_system",
            resource_id=str(result.source_system_id),
            trace_id=context.trace_id,
        )
        return result


@app.get(
    "/api/v1/governance/dashboard",
    response_model=GovernanceDashboard,
    tags=["governance"],
    operation_id="get_governance_dashboard",
)
def governance_dashboard(
    context: Annotated[RequestContext, Depends(request_context)],
) -> GovernanceDashboard:
    with database.transaction(context.actor_id) as connection:
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="governance.dashboard.read",
            resource_type="governance_dashboard",
            resource_id="current",
            trace_id=context.trace_id,
            details={"purpose": "interactive_governance"},
        )
        return get_governance_dashboard(connection)


@app.get(
    "/api/v1/knowledge-hub/session",
    response_model=KnowledgeHubSession,
    tags=["knowledge-hub"],
    operation_id="get_knowledge_hub_session",
)
def knowledge_hub_session(
    context: Annotated[RequestContext, Depends(request_context)],
) -> KnowledgeHubSession:
    with database.transaction(context.actor_id) as connection:
        return KnowledgeHubSession(
            actor_id=context.actor_id,
            permissions=actor_permissions(connection, context.actor_id),
        )


@app.get(
    "/api/v1/knowledge-hub/overview",
    response_model=KnowledgeHubOverview,
    tags=["knowledge-hub"],
    operation_id="get_knowledge_hub_overview",
)
def knowledge_hub_overview(
    context: Annotated[RequestContext, Depends(request_context)],
) -> KnowledgeHubOverview:
    require_knowledge_hub_permission(context, "knowledge_hub.read")
    with database.transaction(context.actor_id) as connection:
        result = get_knowledge_hub_overview(connection, settings)
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="knowledge_hub.overview.read",
            resource_type="knowledge_hub",
            resource_id="overview",
            trace_id=context.trace_id,
        )
        return result


@app.get(
    "/api/v1/publications/intake",
    response_model=PublicationVerificationPage,
    tags=["knowledge-hub"],
    operation_id="list_publication_verifications",
)
def publication_verification_index(
    context: Annotated[RequestContext, Depends(request_context)],
    state: str | None = None,
    fulltext_status: str | None = None,
    query: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PublicationVerificationPage:
    require_knowledge_hub_permission(context, "publication_verification.read")
    with database.transaction(context.actor_id) as connection:
        return list_publication_verifications(
            connection,
            state=state,
            fulltext_status=fulltext_status,
            query=query,
            page=page,
            page_size=page_size,
        )


@app.post(
    "/api/v1/ingestion/publications",
    response_model=PublicationImportResult,
    tags=["knowledge-hub"],
    operation_id="create_publication_import",
    status_code=status.HTTP_201_CREATED,
)
def publication_import_create(
    command: PublicationImportCreate,
    context: Annotated[RequestContext, Depends(request_context)],
) -> PublicationImportResult:
    require_knowledge_hub_permission(context, "publication_intake.submit")
    payload = command.record.model_dump(mode="json")
    checksum = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    with database.transaction(context.actor_id) as connection:
        return import_publication_records(
            connection,
            records=[command.record],
            source_label=command.source_label,
            source_uri=command.source_uri or "manual://knowledge-hub/single-publication",
            source_checksum=checksum,
            source_sheet="单篇录入",
            actor_id=context.actor_id,
            trace_id=context.trace_id,
        )


@app.post(
    "/api/v1/ingestion/publications/file",
    response_model=PublicationImportResult,
    tags=["knowledge-hub"],
    operation_id="create_publication_batch_import",
    status_code=status.HTTP_201_CREATED,
)
async def publication_batch_import_create(
    context: Annotated[RequestContext, Depends(request_context)],
    file: Annotated[UploadFile, File()],
    source_label: Annotated[str, Form(min_length=1, max_length=500)],
) -> PublicationImportResult:
    require_knowledge_hub_permission(context, "publication_intake.submit")
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.casefold()
    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="批量导入仅支持 UTF-8 CSV 或 XLSX 文件")
    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="批量导入文件不能超过 20 MB")
    try:
        if suffix == ".csv":
            records = records_from_csv(content)
        else:
            with NamedTemporaryFile(suffix=".xlsx") as temporary:
                temporary.write(content)
                temporary.flush()
                records = records_from_xlsx(Path(temporary.name))
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with database.transaction(context.actor_id) as connection:
        return import_publication_records(
            connection,
            records=records,
            source_label=source_label,
            source_uri=f"upload://{filename}",
            source_checksum=sha256(content).hexdigest(),
            source_sheet="首个工作表" if suffix == ".xlsx" else "CSV",
            actor_id=context.actor_id,
            trace_id=context.trace_id,
        )


@app.get(
    "/api/v1/publications/intake/{record_id}",
    response_model=PublicationVerificationDetail,
    tags=["knowledge-hub"],
    operation_id="get_publication_verification",
)
def publication_verification_show(
    record_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> PublicationVerificationDetail:
    require_knowledge_hub_permission(context, "publication_verification.read")
    with database.transaction(context.actor_id) as connection:
        result = get_publication_verification(connection, record_id)
        if result is None:
            raise HTTPException(status_code=404, detail="publication verification item not found")
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="publication.verification.read",
            resource_type="publication_intake_record",
            resource_id=str(record_id),
            trace_id=context.trace_id,
        )
        return result


def _decide_publication(
    record_id: UUID,
    command: PublicationVerificationDecisionCommand,
    context: RequestContext,
    *,
    approve: bool,
) -> PublicationVerificationDecisionResult:
    require_knowledge_hub_permission(context, "publication_verification.decide")
    try:
        with database.transaction(context.actor_id) as connection:
            return decide_publication_verification(
                connection,
                record_id=record_id,
                command=command,
                actor_id=context.actor_id,
                trace_id=context.trace_id,
                approve=approve,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VerificationStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (CustomGraphQueryRejected, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/v1/publications/intake/{record_id}/confirm",
    response_model=PublicationVerificationDecisionResult,
    tags=["knowledge-hub"],
    operation_id="confirm_publication_verification",
)
def publication_verification_confirm(
    record_id: UUID,
    command: PublicationVerificationDecisionCommand,
    context: Annotated[RequestContext, Depends(request_context)],
) -> PublicationVerificationDecisionResult:
    return _decide_publication(record_id, command, context, approve=True)


@app.post(
    "/api/v1/publications/intake/{record_id}/reject",
    response_model=PublicationVerificationDecisionResult,
    tags=["knowledge-hub"],
    operation_id="reject_publication_verification",
)
def publication_verification_reject(
    record_id: UUID,
    command: PublicationVerificationDecisionCommand,
    context: Annotated[RequestContext, Depends(request_context)],
) -> PublicationVerificationDecisionResult:
    return _decide_publication(record_id, command, context, approve=False)


@app.get(
    "/api/v1/knowledge-hub/publications/{publication_id}/incremental-status",
    response_model=PublicationIncrementalStatus,
    tags=["knowledge-hub"],
    operation_id="get_publication_incremental_status",
)
def publication_incremental_status(
    publication_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> PublicationIncrementalStatus:
    require_knowledge_hub_permission(context, "publication_supplement.read")
    with database.transaction(context.actor_id) as connection:
        result = get_incremental_status(connection, publication_id)
        if result is None:
            raise HTTPException(status_code=404, detail="publication not found")
        return result


@app.get(
    "/api/v1/knowledge-hub/publications/{publication_id}/supplements",
    response_model=list[PublicationSupplementView],
    tags=["knowledge-hub"],
    operation_id="list_publication_supplements",
)
def publication_supplement_index(
    publication_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> list[PublicationSupplementView]:
    require_knowledge_hub_permission(context, "publication_supplement.read")
    with database.transaction(context.actor_id) as connection:
        if get_incremental_status(connection, publication_id) is None:
            raise HTTPException(status_code=404, detail="publication not found")
        return list_publication_supplements(connection, publication_id)


@app.get(
    "/api/v1/knowledge-hub/publications/{publication_id}/fulltexts",
    response_model=list[PublicationFulltextResourceView],
    tags=["knowledge-hub"],
    operation_id="list_publication_fulltexts",
)
def publication_fulltext_index(
    publication_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> list[PublicationFulltextResourceView]:
    require_knowledge_hub_permission(context, "publication_supplement.read")
    with database.transaction(context.actor_id) as connection:
        if get_incremental_status(connection, publication_id) is None:
            raise HTTPException(status_code=404, detail="publication not found")
        return list_publication_fulltexts(connection, publication_id)


@app.post(
    "/api/v1/knowledge-hub/publications/{publication_id}/fulltext",
    response_model=PublicationFulltextUploadResult,
    status_code=status.HTTP_201_CREATED,
    tags=["knowledge-hub"],
    operation_id="upload_publication_fulltext",
)
def publication_fulltext_upload(
    publication_id: UUID,
    file: Annotated[UploadFile, File(description="论文全文 PDF")],
    context: Annotated[RequestContext, Depends(request_context)],
    source_label: Annotated[str, Form(min_length=1, max_length=500)] = "人工上传论文全文",
    resource_role: Annotated[Literal["article", "correction", "supplementary"], Form()] = "article",
    note: Annotated[str | None, Form(max_length=1000)] = None,
) -> PublicationFulltextUploadResult:
    require_knowledge_hub_permission(context, "publication_supplement.submit")
    if not settings.s3_access_key or not settings.s3_secret_key:
        raise HTTPException(status_code=503, detail="对象存储凭据尚未配置")
    try:
        with database.transaction(context.actor_id) as connection:
            if get_incremental_status(connection, publication_id) is None:
                raise LookupError("publication not found")
        prepared = inspect_pdf(file.file, file.filename or "", settings.fulltext_max_bytes)
        with NamedTemporaryFile(suffix=".pdf") as temporary:
            file.file.seek(0)
            copyfileobj(file.file, temporary)
            temporary.flush()
            extraction = extract_pdf(Path(temporary.name))
        file.file.seek(0)
        object_store = S3ObjectStore(
            settings.s3_endpoint_url,
            settings.s3_bucket,
            settings.s3_access_key,
            settings.s3_secret_key,
            settings.s3_region,
        )
        stored = object_store.put_fulltext(publication_id, prepared, file.file)
        text_key = f"publications/{publication_id}/derived/{prepared.content_checksum}/fulltext.txt"
        try:
            text_object = object_store.put_bytes(
                text_key, extraction.text.encode("utf-8"), "text/plain; charset=utf-8"
            )
        except Exception:
            if stored.created and stored.version_id:
                object_store.delete_version(stored.object_key, stored.version_id)
            raise
        structural = dict(extraction.metadata)
        structural["extracted_text_uri"] = text_object.storage_uri
        enrich: dict[str, object] = {"fulltext_extraction": structural}
        if structural.get("abstract"):
            enrich["abstract"] = structural["abstract"]
        if structural.get("keywords"):
            enrich["keywords"] = structural["keywords"]
        command = PublicationSupplementCreate(
            source_kind="fulltext",
            source_label=source_label,
            source_uri=stored.storage_uri,
            content_checksum=prepared.content_checksum,
            fulltext=FulltextSupplementInput(
                file_name=prepared.file_name,
                storage_uri=stored.storage_uri,
                content_checksum=prepared.content_checksum,
                mime_type=prepared.mime_type,
                resource_role=resource_role,
                size_bytes=prepared.size_bytes,
                license_tags=["controlled-fulltext", "uploaded"],
                extraction_state="extracted",
                extracted_metadata=enrich,
            ),
            note=note,
        )
        try:
            with database.transaction(context.actor_id) as connection:
                supplement = submit_publication_supplement(
                    connection, publication_id, command, context.actor_id, context.trace_id
                )
                connection.execute(
                    """UPDATE smartlib.publication_fulltext_resource SET
                           extraction_method=%s,extraction_version=%s,extracted_text_uri=%s,
                           page_count=%s,text_length=%s,ocr_page_count=%s,extracted_metadata=%s,
                           extracted_at=clock_timestamp(),extraction_error=NULL
                         WHERE publication_id=%s AND content_checksum=%s""",
                    (
                        extraction.method,
                        "publication-fulltext-extraction-v1",
                        text_object.storage_uri,
                        extraction.page_count,
                        len(extraction.text),
                        extraction.ocr_page_count,
                        Jsonb(enrich),
                        publication_id,
                        prepared.content_checksum,
                    ),
                )
        except Exception:
            for created_object in (text_object, stored):
                if created_object.created and created_object.version_id:
                    try:
                        object_store.delete_version(
                            created_object.object_key, created_object.version_id
                        )
                    except ObjectStoreUnavailable:
                        pass
            raise
        return PublicationFulltextUploadResult(
            supplement=supplement,
            file_name=prepared.file_name,
            storage_uri=stored.storage_uri,
            content_checksum=prepared.content_checksum,
            mime_type=prepared.mime_type,
            size_bytes=prepared.size_bytes,
            object_created=stored.created,
        )
    except InvalidFulltextFile as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ObjectStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/v1/knowledge-hub/publications/{publication_id}/supplements",
    response_model=PublicationSupplementView,
    status_code=status.HTTP_201_CREATED,
    tags=["knowledge-hub"],
    operation_id="submit_publication_supplement",
)
def publication_supplement_create(
    publication_id: UUID,
    command: PublicationSupplementCreate,
    context: Annotated[RequestContext, Depends(request_context)],
) -> PublicationSupplementView:
    require_knowledge_hub_permission(context, "publication_supplement.submit")
    try:
        with database.transaction(context.actor_id) as connection:
            return submit_publication_supplement(
                connection, publication_id, command, context.actor_id, context.trace_id
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/v1/knowledge-hub/publication-supplements/{submission_id}/decision",
    response_model=PublicationSupplementView,
    tags=["knowledge-hub"],
    operation_id="decide_publication_supplement",
)
def publication_supplement_decide(
    submission_id: UUID,
    command: PublicationSupplementDecisionCommand,
    context: Annotated[RequestContext, Depends(request_context)],
) -> PublicationSupplementView:
    require_knowledge_hub_permission(context, "publication_supplement.decide")
    try:
        with database.transaction(context.actor_id) as connection:
            return decide_publication_supplement(
                connection, submission_id, command, context.actor_id, context.trace_id
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/v1/governance/summary",
    response_model=GovernanceSummary,
    tags=["governance"],
    operation_id="get_governance_summary",
)
def governance_summary(
    context: Annotated[RequestContext, Depends(request_context)],
) -> GovernanceSummary:
    with database.transaction(context.actor_id) as connection:
        return get_governance_summary(connection)


@app.get(
    "/api/v1/governance/licenses",
    response_model=list[LicenseGrantView],
    tags=["governance"],
    operation_id="list_governance_license_grants",
)
def governance_licenses(
    context: Annotated[RequestContext, Depends(request_context)],
) -> list[LicenseGrantView]:
    with database.transaction(context.actor_id) as connection:
        return list_license_grants(connection)


@app.get(
    "/api/v1/governance/quality-issues",
    response_model=list[QualityIssueView],
    tags=["governance"],
    operation_id="list_governance_quality_issues",
)
def governance_quality_issues(
    context: Annotated[RequestContext, Depends(request_context)],
    open_only: bool = True,
) -> list[QualityIssueView]:
    with database.transaction(context.actor_id) as connection:
        return list_quality_issues(connection, open_only=open_only)


@app.get(
    "/api/v1/governance/review-tasks",
    response_model=list[ReviewTaskView],
    tags=["governance"],
    operation_id="list_governance_review_tasks",
)
def governance_review_tasks(
    context: Annotated[RequestContext, Depends(request_context)],
    state: Literal["open", "in_review", "resolved", "rejected", "cancelled"] | None = None,
    issue_type: str | None = None,
    publication_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ReviewTaskView]:
    with database.transaction(context.actor_id) as connection:
        return list_review_tasks(
            connection,
            state=state,
            issue_type=issue_type,
            publication_id=publication_id,
            limit=limit,
        )


@app.post(
    "/api/v1/governance/review-tasks",
    response_model=ReviewTaskView,
    status_code=status.HTTP_201_CREATED,
    tags=["governance"],
    operation_id="create_governance_review_task",
)
def governance_review_task_create(
    command: ReviewTaskCreate,
    context: Annotated[RequestContext, Depends(request_context)],
) -> ReviewTaskView:
    try:
        with database.transaction(context.actor_id) as connection:
            result = create_review_task(connection, command, context.actor_id)
            record_allowed(
                connection,
                actor_id=context.actor_id,
                action="governance.review_task.create",
                resource_type="review_task",
                resource_id=str(result.review_task_id),
                trace_id=context.trace_id,
                details={"issue_type": result.issue_type, "target_type": result.target_type},
            )
            return result
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="review task target is invalid or already open") from exc


@app.post(
    "/api/v1/governance/review-tasks/{review_task_id}/decision",
    response_model=ReviewTaskView,
    tags=["governance"],
    operation_id="decide_governance_review_task",
)
def governance_review_task_decide(
    review_task_id: UUID,
    command: ReviewTaskDecision,
    context: Annotated[RequestContext, Depends(request_context)],
) -> ReviewTaskView:
    with database.transaction(context.actor_id) as connection:
        result = decide_review_task(connection, review_task_id, command, context.actor_id)
        if result is None:
            raise HTTPException(status_code=404, detail="open review task not found")
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="governance.review_task.decide",
            resource_type="review_task",
            resource_id=str(review_task_id),
            trace_id=context.trace_id,
            details={"state": result.state},
        )
        return result


@app.get(
    "/api/v1/governance/journal-metrics/releases",
    response_model=list[JournalMetricReleaseView],
    tags=["governance"],
    operation_id="list_journal_metric_releases",
)
def journal_metric_releases(
    context: Annotated[RequestContext, Depends(request_context)],
) -> list[JournalMetricReleaseView]:
    require_knowledge_hub_permission(context, "journal_metric.read")
    with database.transaction(context.actor_id) as connection:
        return list_journal_metric_releases(connection)


@app.get('/api/v1/governance/publication-metrics/releases', tags=['governance'])
def publication_metric_release_list(context: Annotated[RequestContext, Depends(request_context)]) -> list[dict]:
    from smartlib_platform.publications.metrics import metric_releases
    require_knowledge_hub_permission(context, 'publication_metric.read')
    with database.transaction(context.actor_id) as connection:
        return metric_releases(connection)


@app.get('/api/v1/governance/publication-metrics/summary', tags=['governance'])
def publication_metric_summary(
    release_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
    publication_id: Annotated[list[UUID] | None, Query()] = None,
) -> dict:
    from smartlib_platform.publications.metrics import metric_summary
    require_knowledge_hub_permission(context, 'publication_metric.read')
    with database.transaction(context.actor_id) as connection:
        try:
            return metric_summary(connection, release_id, publication_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get('/api/v1/governance/publications/{publication_id}/metrics', tags=['governance'])
def publication_metric_detail(
    publication_id: UUID,
    release_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> list[dict]:
    from smartlib_platform.publications.metrics import publication_metrics
    require_knowledge_hub_permission(context, 'publication_metric.read')
    with database.transaction(context.actor_id) as connection:
        return publication_metrics(connection, publication_id, release_id)


@app.get(
    "/api/v1/governance/publications/{publication_id}/journal-metrics",
    response_model=list[PublicationJournalMetricView],
    tags=["governance"],
    operation_id="list_publication_journal_metrics",
)
def publication_journal_metrics(
    publication_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> list[PublicationJournalMetricView]:
    require_knowledge_hub_permission(context, "journal_metric.read")
    with database.transaction(context.actor_id) as connection:
        return list_publication_journal_metrics(connection, publication_id)


@app.get(
    "/api/v1/governance/audit-events",
    response_model=list[GovernanceAuditEventView],
    tags=["governance"],
    operation_id="list_governance_audit_events",
)
def governance_audit_events(
    context: Annotated[RequestContext, Depends(request_context)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[GovernanceAuditEventView]:
    with database.transaction(context.actor_id) as connection:
        return list_governance_audit_events(connection, limit)


@app.get(
    "/api/v1/governance/assets/{data_asset_id}/trace",
    response_model=DataAssetTrace,
    tags=["governance"],
    operation_id="get_governance_data_asset_trace",
)
def governance_data_asset_trace(
    data_asset_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> DataAssetTrace:
    with database.transaction(context.actor_id) as connection:
        result = get_data_asset_trace(connection, data_asset_id)
        if result is None:
            raise HTTPException(status_code=404, detail="data asset not found")
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="governance.asset.trace.read",
            resource_type="data_asset",
            resource_id=str(data_asset_id),
            trace_id=context.trace_id,
            details={"synthetic": result.synthetic, "source_system_id": str(result.source_system_id)},
        )
        return result


@app.get(
    "/api/v1/governance/objects/{object_id}/provenance",
    response_model=KnowledgeObjectProvenanceTrace,
    tags=["governance"],
    operation_id="get_governance_knowledge_object_provenance",
)
def governance_knowledge_object_provenance(
    object_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> KnowledgeObjectProvenanceTrace:
    with database.transaction(context.actor_id) as connection:
        result = get_knowledge_object_provenance(connection, object_id)
        if result is None:
            raise HTTPException(status_code=404, detail="knowledge object not found")
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="governance.object.provenance.read",
            resource_type="knowledge_object",
            resource_id=str(object_id),
            trace_id=context.trace_id,
            details={
                "source_reference_count": len(result.source_references),
                "evidence_count": len(result.evidence),
            },
        )
        return result


@app.get(
    "/api/v1/objects",
    response_model=list[KnowledgeObjectView],
    tags=["knowledge"],
    operation_id="list_knowledge_objects",
)
def objects_index(
    context: Annotated[RequestContext, Depends(request_context)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[KnowledgeObjectView]:
    with database.transaction(context.actor_id) as connection:
        return list_objects(connection, limit)


@app.get(
    "/api/v1/catalog/objects",
    response_model=KnowledgeObjectPage,
    tags=["knowledge"],
    operation_id="list_knowledge_object_catalog",
)
def object_catalog_index(
    context: Annotated[RequestContext, Depends(request_context)],
    object_types: Annotated[list[ObjectType] | None, Query()] = None,
    linked_only: Annotated[bool, Query()] = False,
    query: Annotated[str | None, Query(max_length=500)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[Literal["updated", "name", "year"], Query()] = "updated",
    hierarchy_root_id: Annotated[UUID | None, Query()] = None,
    organization_level: Annotated[int | None, Query(ge=1, le=20)] = None,
    project_kind_id: Annotated[UUID | None, Query()] = None,
) -> KnowledgeObjectPage:
    with database.transaction(context.actor_id) as connection:
        return list_object_catalog(
            connection,
            object_types=list(object_types) if object_types else None,
            linked_only=linked_only,
            query=query,
            page=page,
            page_size=page_size,
            sort=sort,
            hierarchy_root_id=hierarchy_root_id,
            organization_level=organization_level,
            project_kind_id=project_kind_id,
        )


@app.get(
    "/api/v1/catalog/organization-hierarchy/options",
    response_model=OrganizationHierarchyOptions,
    tags=["knowledge"],
    operation_id="get_organization_hierarchy_options",
)
def organization_hierarchy_options(
    context: Annotated[RequestContext, Depends(request_context)],
) -> OrganizationHierarchyOptions:
    with database.transaction(context.actor_id) as connection:
        return get_organization_hierarchy_options(connection)


@app.get(
    "/api/v1/catalog/project-kinds/options",
    response_model=ProjectKindOptions,
    tags=["knowledge"],
    operation_id="get_project_kind_options",
)
def project_kind_options(
    context: Annotated[RequestContext, Depends(request_context)],
) -> ProjectKindOptions:
    with database.transaction(context.actor_id) as connection:
        return get_project_kind_options(connection)


@app.get(
    "/api/v1/catalog/objects/{object_id}",
    response_model=KnowledgeObjectDetailView,
    tags=["knowledge"],
    operation_id="get_knowledge_object_catalog_detail",
)
def object_catalog_detail(
    object_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> KnowledgeObjectDetailView:
    with database.transaction(context.actor_id) as connection:
        result = get_object_detail(connection, object_id)
    if result is None:
        raise HTTPException(status_code=404, detail="knowledge object not found")
    return result


@app.get('/api/v1/catalog/objects/{object_id}/complete-neighborhood', response_model=NeighborhoodResult, tags=['knowledge'])
def complete_object_neighborhood(
    object_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> NeighborhoodResult:
    access = GraphAccessContext(actor_id=context.actor_id, purpose='interactive_complete_one_hop', trace_id=context.trace_id)
    with database.transaction(context.actor_id) as connection:
        if get_object_detail(connection, object_id) is None:
            raise HTTPException(status_code=404, detail='knowledge object not found')
        result = get_knowledge_neighborhood(
            PostgresGraphAdapter(connection, complete_one_hop=True),
            NeighborhoodCommand(root_object_id=object_id, direction='both', max_depth=1), access,
        )
        _record_graph_audit(connection, 'graph.complete_one_hop.read', object_id, len(result.edges), result.backend, context)
        return result


@app.get('/api/v1/catalog/objects/{object_id}/research-profile', tags=['knowledge'])
def object_research_profile(
    object_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
    start_year: int | None = None,
    end_year: int | None = None,
) -> dict:
    from smartlib_platform.knowledge.research_profiles import load_profiles
    if start_year is not None and end_year is not None and start_year > end_year:
        raise HTTPException(status_code=422, detail='start_year must not exceed end_year')
    with database.transaction(context.actor_id) as connection:
        if get_object_detail(connection, object_id) is None:
            raise HTTPException(status_code=404, detail='knowledge object not found')
        profile = load_profiles(connection, object_id, start_year, end_year).get(str(object_id))
    return {'profile': profile, 'note': '当前画像包含已确认和待审核论文分类；待审核不等于已确认。不代表人事学科归属或项目实际申请代码；多标签篇数不可相加。'}


@app.get(
    "/api/v1/catalog/objects/{object_id}/resources/{resource_id}/content",
    tags=["knowledge"],
    operation_id="read_knowledge_object_resource_content",
    responses={
        200: {
            "description": "Complete PDF content",
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        },
        206: {
            "description": "Partial PDF content",
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        },
    },
)
def object_catalog_resource_content(
    object_id: UUID,
    resource_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    requested_range = _validated_pdf_range(range_header)
    with database.transaction(context.actor_id) as connection:
        resource = get_publication_resource_reference(connection, object_id, resource_id)
        if resource is None:
            raise HTTPException(status_code=404, detail="publication fulltext resource not found")
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="publication.fulltext.read",
            resource_type="publication_fulltext_resource",
            resource_id=str(resource_id),
            trace_id=context.trace_id,
            details={"publication_id": str(object_id), "range_requested": bool(requested_range)},
        )
    if resource.mime_type.lower() != "application/pdf":
        raise HTTPException(status_code=415, detail="resource is not a PDF")
    if not settings.s3_access_key or not settings.s3_secret_key:
        raise HTTPException(status_code=503, detail="对象存储凭据尚未配置")
    object_store = S3ObjectStore(
        settings.s3_endpoint_url,
        settings.s3_bucket,
        settings.s3_access_key,
        settings.s3_secret_key,
        settings.s3_region,
    )
    try:
        stored = object_store.get_object(
            _storage_object_key(resource.storage_uri), requested_range
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="fulltext object not found") from exc
    except ObjectRangeNotSatisfiable as exc:
        raise HTTPException(status_code=416, detail="PDF byte range not satisfiable") from exc
    except ObjectStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail="对象存储当前不可用") from exc

    encoded_name = quote(resource.file_name, safe="")
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": f"inline; filename=fulltext.pdf; filename*=UTF-8''{encoded_name}",
        "Content-Length": str(stored.content_length),
        "X-Content-Type-Options": "nosniff",
    }
    if stored.content_range:
        headers["Content-Range"] = stored.content_range
    if stored.etag:
        headers["ETag"] = stored.etag
    return Response(
        content=stored.content,
        status_code=stored.status_code,
        media_type="application/pdf",
        headers=headers,
    )


@app.post(
    "/api/v1/objects",
    response_model=KnowledgeObjectView,
    status_code=status.HTTP_201_CREATED,
    tags=["knowledge"],
    operation_id="create_knowledge_object",
)
def objects_create(
    command: KnowledgeObjectCreate,
    context: Annotated[RequestContext, Depends(request_context)],
) -> KnowledgeObjectView:
    if command.object_type == 'organization' and not command.attributes.get('entity_decision_id'):
        raise HTTPException(status_code=422, detail='机构尚未完成实体确认; 请先保留为证据并完成实体审核。')
    with database.transaction(context.actor_id) as connection:
        result = create_object(connection, command, context.actor_id, context.trace_id)
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="knowledge_object.create",
            resource_type="knowledge_object",
            resource_id=str(result.object_id),
            trace_id=context.trace_id,
            details={"object_type": result.object_type, "version": result.version},
        )
        return result


@app.get(
    "/api/v1/objects/{object_id}",
    response_model=KnowledgeObjectView,
    tags=["knowledge"],
    operation_id="get_knowledge_object",
)
def objects_show(
    object_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> KnowledgeObjectView:
    with database.transaction(context.actor_id) as connection:
        result = get_object(connection, object_id)
    if result is None:
        raise HTTPException(status_code=404, detail="knowledge object not found")
    return result


@app.post(
    "/api/v1/objects/{object_id}/evidence",
    response_model=EvidenceView,
    status_code=status.HTTP_201_CREATED,
    tags=["knowledge"],
    operation_id="create_evidence_record",
)
def evidence_create(
    object_id: UUID,
    command: EvidenceCreate,
    context: Annotated[RequestContext, Depends(request_context)],
) -> EvidenceView:
    with database.transaction(context.actor_id) as connection:
        try:
            result = create_evidence(connection, object_id, command, context.actor_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="evidence.create",
            resource_type="evidence_record",
            resource_id=str(result.evidence_id),
            trace_id=context.trace_id,
            details={"object_id": str(object_id)},
        )
        return result


@app.post(
    "/api/v1/relations",
    response_model=RelationView,
    status_code=status.HTTP_201_CREATED,
    tags=["graph"],
    operation_id="create_relation_assertion",
)
def relations_create(
    command: RelationCreate,
    context: Annotated[RequestContext, Depends(request_context)],
) -> RelationView:
    with database.transaction(context.actor_id) as connection:
        try:
            result = create_relation(connection, command, context.actor_id, context.trace_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="relation.create",
            resource_type="relation_assertion",
            resource_id=str(result.relation_id),
            trace_id=context.trace_id,
            details={"predicate": result.predicate, "fact_class": result.fact_class},
        )
        return result


@app.post(
    "/api/v1/search",
    response_model=SearchResult,
    tags=["search"],
    operation_id="search_knowledge",
)
def search_create(
    command: SearchCommand,
    context: Annotated[RequestContext, Depends(request_context)],
) -> SearchResult:
    access = SearchAccessContext(
        actor_id=context.actor_id,
        purpose=context.purpose,
        trace_id=context.trace_id,
    )
    if settings.search_backend == "postgres":
        with database.transaction(context.actor_id) as connection:
            result = search_knowledge(PostgresSearchAdapter(connection), command, access)
            _record_search_audit(connection, command, result, context)
            return result

    result = search_knowledge(
        OpenSearchAdapter(settings.opensearch_url, settings.opensearch_index_alias),
        command,
        access,
    )
    with database.transaction(context.actor_id) as connection:
        _record_search_audit(connection, command, result, context)
    return result


def _record_search_audit(
    connection: DbConnection,
    command: SearchCommand,
    result: SearchResult,
    context: RequestContext,
) -> None:
    query_fingerprint = sha256(command.query_text.encode()).hexdigest()
    record_allowed(
        connection,
        actor_id=context.actor_id,
        action="knowledge.search",
        resource_type="search_query",
        resource_id=query_fingerprint,
        trace_id=context.trace_id,
        details={
            "backend": result.backend,
            "retrieval_mode": result.retrieval_mode,
            "result_count": len(result.hits),
            "query_sha256": query_fingerprint,
            "purpose": context.purpose,
        },
    )


@app.post(
    "/api/v1/graph/neighborhood",
    response_model=NeighborhoodResult,
    tags=["graph"],
    operation_id="get_knowledge_neighborhood",
)
def graph_neighborhood(
    command: NeighborhoodCommand,
    context: Annotated[RequestContext, Depends(request_context)],
) -> NeighborhoodResult:
    access = _graph_access(context)
    if settings.graph_backend == "postgres":
        with database.transaction(context.actor_id) as connection:
            result = get_knowledge_neighborhood(PostgresGraphAdapter(connection), command, access)
            _record_graph_audit(
                connection,
                "knowledge.graph.neighborhood",
                command.root_object_id,
                len(result.edges),
                result.backend,
                context,
            )
            return result
    result = get_knowledge_neighborhood(_hugegraph_adapter(), command, access)
    with database.transaction(context.actor_id) as connection:
        _record_graph_audit(
            connection,
            "knowledge.graph.neighborhood",
            command.root_object_id,
            len(result.edges),
            result.backend,
            context,
        )
    return result


@app.get(
    "/api/v1/scholars",
    response_model=list[ScholarSummary],
    tags=["scholars"],
    operation_id="search_scholars",
)
def scholars_index(
    context: Annotated[RequestContext, Depends(request_context)],
    query: Annotated[str | None, Query(max_length=200)] = None,
    department: Annotated[str | None, Query(max_length=200)] = None,
    research_direction: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 50,
) -> list[ScholarSummary]:
    with database.transaction(context.actor_id) as connection:
        result = list_scholars(
            connection,
            query=query,
            department=department,
            research_direction=research_direction,
            limit=limit,
        )
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="scholar.search",
            resource_type="scholar_directory",
            resource_id="current",
            trace_id=context.trace_id,
            details={
                "result_count": len(result),
                "query_supplied": bool(query),
                "department_filter": bool(department),
                "direction_filter": bool(research_direction),
                "purpose": "interactive_scholar_discovery",
            },
        )
        return result


@app.get(
    "/api/v1/scholars/{scholar_id}",
    response_model=ScholarProfile,
    tags=["scholars"],
    operation_id="get_scholar_profile",
)
def scholars_show(
    scholar_id: str,
    context: Annotated[RequestContext, Depends(request_context)],
) -> ScholarProfile:
    with database.transaction(context.actor_id) as connection:
        object_id = resolve_scholar_object_id(connection, scholar_id)
        result = get_scholar_profile(connection, object_id) if object_id else None
        if result is None:
            raise HTTPException(status_code=404, detail="scholar not found")
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="scholar.profile.read",
            resource_type="scholar",
            resource_id=str(object_id),
            trace_id=context.trace_id,
            details={
                "object_version": result.summary.object_version,
                "scholar_id": result.summary.scholar_id,
                "synthetic": result.summary.synthetic,
                "purpose": "interactive_scholar_profile",
            },
        )
        return result


@app.get(
    "/api/v1/scholars/{scholar_id}/network",
    response_model=NeighborhoodResult,
    tags=["scholars"],
    operation_id="get_scholar_network",
)
def scholar_network(
    scholar_id: str,
    context: Annotated[RequestContext, Depends(request_context)],
    max_depth: Annotated[int, Query(ge=1, le=3)] = 2,
    limit: Annotated[int, Query(ge=1, le=200)] = 80,
) -> NeighborhoodResult:
    access = GraphAccessContext(
        actor_id=context.actor_id,
        purpose="interactive_scholar_network",
        trace_id=context.trace_id,
    )
    if settings.graph_backend == "postgres":
        with database.transaction(context.actor_id) as connection:
            object_id = resolve_scholar_object_id(connection, scholar_id)
            if object_id is None or get_scholar_profile(connection, object_id) is None:
                raise HTTPException(status_code=404, detail="scholar not found")
            command = NeighborhoodCommand(
                root_object_id=object_id,
                direction="both",
                max_depth=max_depth,
                limit=limit,
            )
            result = get_knowledge_neighborhood(PostgresGraphAdapter(connection), command, access)
            _record_graph_audit(
                connection,
                "scholar.network.read",
                object_id,
                len(result.edges),
                result.backend,
                context,
            )
            return result
    with database.transaction(context.actor_id) as connection:
        object_id = resolve_scholar_object_id(connection, scholar_id)
        if object_id is None or get_scholar_profile(connection, object_id) is None:
            raise HTTPException(status_code=404, detail="scholar not found")
    command = NeighborhoodCommand(
        root_object_id=object_id,
        direction="both",
        max_depth=max_depth,
        limit=limit,
    )
    result = get_knowledge_neighborhood(_hugegraph_adapter(), command, access)
    with database.transaction(context.actor_id) as connection:
        _record_graph_audit(
            connection,
            "scholar.network.read",
            object_id,
            len(result.edges),
            result.backend,
            context,
        )
    return result


@app.get(
    "/api/v1/scholar-graph/analytics/scope-options",
    response_model=GraphAnalysisScopeOptions,
    tags=["scholar-graph"],
    operation_id="get_graph_analysis_scope_options",
)
def graph_analysis_scope_options(
    context: Annotated[RequestContext, Depends(request_context)],
) -> GraphAnalysisScopeOptions:
    with database.transaction(context.actor_id) as connection:
        return get_graph_analysis_scope_options(connection)


@app.get(
    "/api/v1/scholar-graph/analytics",
    response_model=ScholarGraphAnalytics,
    tags=["scholar-graph"],
    operation_id="get_scholar_graph_analytics",
)
def scholar_graph_analytics(
    context: Annotated[RequestContext, Depends(request_context)],
    minimum_publication_count: Annotated[int, Query(ge=1, le=20)] = 2,
    edge_limit: Annotated[int, Query(ge=1)] = 120,
    people_focus_id: UUID | None = None,
    people_organization_id: UUID | None = None,
    people_include_external: bool = False,
    start_year: Annotated[int | None, Query(ge=1500, le=2200)] = None,
    end_year: Annotated[int | None, Query(ge=1500, le=2200)] = None,
    project_kind_ids: Annotated[list[UUID] | None, Query()] = None,
    organization_ids: Annotated[list[UUID] | None, Query()] = None,
    scholar_ids: Annotated[list[UUID] | None, Query()] = None,
    custom_scope_id: Annotated[UUID | None, Query()] = None,
    institution_settings: Annotated[str | None, Query(max_length=30000)] = None,
    selected_module: AnalysisModule | None = None,
) -> ScholarGraphAnalytics:
    if start_year is not None and end_year is not None and start_year > end_year:
        raise HTTPException(status_code=422, detail="开始年份不能晚于结束年份")
    with database.transaction(context.actor_id, repeatable_read=True) as connection:
        custom_publication_ids: list[UUID] | None = None
        custom_scope_name: str | None = None
        if custom_scope_id is not None:
            saved_scope = get_custom_scope(connection, custom_scope_id)
            if saved_scope is None:
                raise HTTPException(status_code=404, detail="自定义分析范围不存在")
            custom_publication_ids, preview = _execute_custom_graph_scope(
                connection, saved_scope.graph_query, context
            )
            custom_scope_name = saved_scope.name
            mark_custom_scope_executed(connection, custom_scope_id, preview.publication_count)
        result = get_scholar_graph_analytics(
            connection,
            graph_backend=settings.graph_backend,
            minimum_publication_count=minimum_publication_count,
            edge_limit=edge_limit,
            people_focus_id=people_focus_id,
            people_organization_id=people_organization_id,
            people_include_external=people_include_external,
            institution_settings=institution_settings,
            selected_module=selected_module,
            start_year=start_year,
            end_year=end_year,
            project_kind_ids=project_kind_ids,
            organization_ids=organization_ids,
            scholar_ids=scholar_ids,
            custom_publication_ids=custom_publication_ids,
            custom_scope_id=custom_scope_id,
            custom_scope_name=custom_scope_name,
        )
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="scholar_graph.analytics.read",
            resource_type="scholar_graph_analytics",
            resource_id="current",
            trace_id=context.trace_id,
            details={
                "graph_backend": settings.graph_backend,
                "minimum_publication_count": minimum_publication_count,
                "start_year": start_year,
                "end_year": end_year,
                "project_kind_ids": [str(value) for value in project_kind_ids or []],
                "organization_ids": [str(value) for value in organization_ids or []],
                "scholar_ids": [str(value) for value in scholar_ids or []],
                "custom_scope_id": str(custom_scope_id) if custom_scope_id else None,
                "publication_count": result.scope.publication_count,
                "people_edges": result.people_collaboration.displayed_edge_count if result.people_collaboration else None,
                "institution_edges": result.institution_collaboration.displayed_edge_count if result.institution_collaboration else None,
                "purpose": "interactive_scholar_graph_analytics",
            },
        )
        return result


@app.post(
    "/api/v1/scholar-graph/analytics/custom",
    response_model=ScholarGraphAnalytics,
    tags=["scholar-graph"],
    operation_id="get_custom_scholar_graph_analytics",
)
def custom_scholar_graph_analytics(
    command: CustomGraphAnalyticsCommand,
    context: Annotated[RequestContext, Depends(request_context)],
) -> ScholarGraphAnalytics:
    if (
        command.start_year is not None
        and command.end_year is not None
        and command.start_year > command.end_year
    ):
        raise HTTPException(status_code=422, detail="开始年份不能晚于结束年份")
    with database.transaction(context.actor_id, repeatable_read=True) as connection:
        publication_ids, preview = _execute_custom_graph_scope(connection, command.graph_query, context)
        result = get_scholar_graph_analytics(
            connection,
            graph_backend=settings.graph_backend,
            minimum_publication_count=command.minimum_publication_count,
            edge_limit=command.edge_limit,
            people_focus_id=command.people_focus_id,
            people_organization_id=command.people_organization_id,
            people_include_external=command.people_include_external,
            institution_settings=command.institution_settings,
            selected_module=command.selected_module,
            start_year=command.start_year,
            end_year=command.end_year,
            project_kind_ids=command.project_kind_ids,
            organization_ids=command.organization_ids,
            scholar_ids=command.scholar_ids,
            custom_publication_ids=publication_ids,
            custom_scope_name="未保存的自定义范围",
        )
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="scholar_graph.analytics.custom.read",
            resource_type="custom_graph_analysis_scope",
            resource_id=preview.query_hash,
            trace_id=context.trace_id,
            details={"publication_count": result.scope.publication_count},
        )
        return result


@app.post(
    "/api/v1/scholar-graph/analytics/custom-scopes/preview",
    response_model=CustomGraphScopePreview,
    tags=["scholar-graph"],
    operation_id="preview_custom_graph_analysis_scope",
)
def preview_custom_graph_analysis_scope(
    command: CustomGraphScopeQuery,
    context: Annotated[RequestContext, Depends(request_context)],
) -> CustomGraphScopePreview:
    with database.transaction(context.actor_id) as connection:
        _, preview = _execute_custom_graph_scope(connection, command.graph_query, context)
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="scholar_graph.analytics.custom.preview",
            resource_type="custom_graph_analysis_scope",
            resource_id=preview.query_hash,
            trace_id=context.trace_id,
            details={"publication_count": preview.publication_count, "truncated": preview.truncated},
        )
        return preview


@app.get(
    "/api/v1/scholar-graph/analytics/custom-scopes",
    response_model=list[SavedCustomGraphScope],
    tags=["scholar-graph"],
    operation_id="list_custom_graph_analysis_scopes",
)
def list_custom_graph_analysis_scopes(
    context: Annotated[RequestContext, Depends(request_context)],
) -> list[SavedCustomGraphScope]:
    with database.transaction(context.actor_id) as connection:
        return list_custom_scopes(connection)


@app.post(
    "/api/v1/scholar-graph/analytics/custom-scopes",
    response_model=SavedCustomGraphScope,
    status_code=status.HTTP_201_CREATED,
    tags=["scholar-graph"],
    operation_id="create_custom_graph_analysis_scope",
)
def create_custom_graph_analysis_scope(
    command: CustomGraphScopeCreate,
    context: Annotated[RequestContext, Depends(request_context)],
) -> SavedCustomGraphScope:
    with database.transaction(context.actor_id) as connection:
        _, preview = _execute_custom_graph_scope(connection, command.graph_query, context)
        try:
            result = create_custom_scope(connection, command, context.actor_id, preview)
        except CustomScopeNameConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="scholar_graph.analytics.custom.save",
            resource_type="custom_graph_analysis_scope",
            resource_id=str(result.scope_id),
            trace_id=context.trace_id,
            details={"publication_count": preview.publication_count},
        )
        return result


@app.delete(
    "/api/v1/scholar-graph/analytics/custom-scopes/{scope_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["scholar-graph"],
    operation_id="delete_custom_graph_analysis_scope",
)
def delete_custom_graph_analysis_scope(
    scope_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> Response:
    with database.transaction(context.actor_id) as connection:
        if not delete_custom_scope(connection, scope_id):
            raise HTTPException(status_code=404, detail="自定义分析范围不存在")
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="scholar_graph.analytics.custom.delete",
            resource_type="custom_graph_analysis_scope",
            resource_id=str(scope_id),
            trace_id=context.trace_id,
            details={},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _execute_custom_graph_scope(
    connection: DbConnection,
    graph_query: str,
    context: RequestContext,
) -> tuple[list[UUID], CustomGraphScopePreview]:
    try:
        return execute_custom_scope(
            connection,
            _hugegraph_adapter(),
            graph_query,
            GraphAccessContext(
                actor_id=context.actor_id,
                purpose="custom_graph_analysis_scope",
                trace_id=context.trace_id,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/v1/scholars/{scholar_id}/evidence",
    response_model=ScholarEvidenceBundle,
    tags=["scholars"],
    operation_id="get_scholar_evidence",
)
def scholar_evidence(
    scholar_id: str,
    context: Annotated[RequestContext, Depends(request_context)],
) -> ScholarEvidenceBundle:
    with database.transaction(context.actor_id) as connection:
        object_id = resolve_scholar_object_id(connection, scholar_id)
        result = get_scholar_evidence(connection, object_id) if object_id else None
        if result is None:
            raise HTTPException(status_code=404, detail="scholar not found")
        record_allowed(
            connection,
            actor_id=context.actor_id,
            action="scholar.evidence.read",
            resource_type="scholar",
            resource_id=str(object_id),
            trace_id=context.trace_id,
            details={
                "object_version": result.object_version,
                "scholar_id": result.scholar_id,
                "visible_evidence_count": len(result.items),
                "purpose": "interactive_scholar_evidence",
            },
        )
        return result


@app.post(
    "/api/v1/graph/paths",
    response_model=PathResult,
    tags=["graph"],
    operation_id="find_knowledge_paths",
)
def graph_paths(
    command: PathCommand,
    context: Annotated[RequestContext, Depends(request_context)],
) -> PathResult:
    access = _graph_access(context)
    if settings.graph_backend == "postgres":
        with database.transaction(context.actor_id) as connection:
            result = find_knowledge_paths(PostgresGraphAdapter(connection), command, access)
            _record_graph_audit(
                connection,
                "knowledge.graph.paths",
                command.start_object_id,
                len(result.paths),
                result.backend,
                context,
            )
            return result
    result = find_knowledge_paths(_hugegraph_adapter(), command, access)
    with database.transaction(context.actor_id) as connection:
        _record_graph_audit(
            connection,
            "knowledge.graph.paths",
            command.start_object_id,
            len(result.paths),
            result.backend,
            context,
        )
    return result


@app.get(
    "/api/v1/relations/{relation_id}/explanation",
    response_model=RelationExplanation,
    tags=["graph"],
    operation_id="explain_relation",
)
def relation_explanation(
    relation_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> RelationExplanation:
    access = _graph_access(context)
    if settings.graph_backend == "postgres":
        with database.transaction(context.actor_id) as connection:
            result = explain_relation(PostgresGraphAdapter(connection), relation_id, access)
            if result is None:
                raise HTTPException(status_code=404, detail="relation not found")
            _record_graph_audit(
                connection, "knowledge.graph.explain", relation_id, 1, result.backend, context
            )
            return result
    result = explain_relation(_hugegraph_adapter(), relation_id, access)
    if result is None:
        raise HTTPException(status_code=404, detail="relation not found")
    with database.transaction(context.actor_id) as connection:
        _record_graph_audit(connection, "knowledge.graph.explain", relation_id, 1, result.backend, context)
    return result


def _graph_access(context: RequestContext) -> GraphAccessContext:
    return GraphAccessContext(
        actor_id=context.actor_id, purpose="interactive_graph", trace_id=context.trace_id
    )


def _hugegraph_adapter() -> HugeGraphAdapter:
    return HugeGraphAdapter(
        settings.hugegraph_url,
        settings.hugegraph_user,
        settings.hugegraph_password,
        settings.hugegraph_graph,
    )


def _record_graph_audit(
    connection: DbConnection,
    action: str,
    resource_id: UUID,
    result_count: int,
    backend: str,
    context: RequestContext,
) -> None:
    record_allowed(
        connection,
        actor_id=context.actor_id,
        action=action,
        resource_type="knowledge_graph",
        resource_id=str(resource_id),
        trace_id=context.trace_id,
        details={"backend": backend, "result_count": result_count, "purpose": "interactive_graph"},
    )


@app.get("/api/v1/jobs/{job_id}", response_model=JobView, tags=["operations"], operation_id="get_job_status")
def jobs_show(
    job_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> JobView:
    with database.transaction(context.actor_id) as connection:
        result = get_job(connection, job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="job not found")
    return result


@app.post("/api/v1/ingestion/batches", response_model=IngestionResult,
          tags=["ingestion"], operation_id="receive_ingestion_batch", status_code=201)
def ingestion_batch_create(
    command: IngestionCreate,
    context: Annotated[RequestContext, Depends(request_context)],
) -> IngestionResult:
    require_knowledge_hub_permission(context, "ingestion.submit")
    with database.transaction(context.actor_id) as connection:
        try:
            return receive_batch(connection, command, context.actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/ingestion/batches/{batch_id}", tags=["ingestion"], operation_id="get_ingestion_batch")
def ingestion_batch_show(
    batch_id: UUID,
    context: Annotated[RequestContext, Depends(request_context)],
) -> dict[str, object]:
    require_knowledge_hub_permission(context, "ingestion.submit")
    with database.transaction(context.actor_id) as connection:
        batch = connection.execute(
            "SELECT * FROM smartlib.ingestion_batch WHERE batch_id=%s", (batch_id,)
        ).fetchone()
        if batch is None:
            raise HTTPException(status_code=404, detail="input batch not found")
        records = connection.execute(
            "SELECT * FROM smartlib.ingestion_record WHERE batch_id=%s ORDER BY source_record_key",
            (batch_id,),
        ).fetchall()
        return {"batch": batch, "records": records}


@app.post("/api/v1/publications/relations", response_model=PublicationRelationView,
          tags=["publications"], operation_id="create_publication_relation", status_code=201)
def publication_relation_create(
    command: PublicationRelationCreate,
    context: Annotated[RequestContext, Depends(request_context)],
) -> PublicationRelationView:
    with database.transaction(context.actor_id) as connection:
        try:
            result = create_publication_relation(connection, command, context.actor_id, context.trace_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record_allowed(connection, actor_id=context.actor_id, action="publication.relation.create",
                       resource_type="relation_assertion", resource_id=str(result.relation_id),
                       trace_id=context.trace_id, details={"predicate": result.predicate})
        return result


# Generic change workflow; domain-specific publication application retains its own handler.

@app.get('/api/v1/history/{object_id}', tags=['changes'])
def object_history(object_id: UUID, context: Annotated[RequestContext, Depends(request_context)],
                   limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                   scope: Literal['object', 'all'] = 'all') -> dict:
    require_knowledge_hub_permission(context, 'change.decide')
    with database.transaction(context.actor_id) as connection:
        object_row = connection.execute(
            'SELECT object_id FROM smartlib.knowledge_object WHERE object_id=%s', (object_id,)
        ).fetchone()
        if not object_row:
            raise HTTPException(status_code=404, detail='对象不可用')
        result = history.list_history(connection, object_id, limit, offset, scope)
        record_allowed(connection, actor_id=context.actor_id, action='history.read',
                       resource_type='knowledge_object', resource_id=str(object_id),
                       trace_id=context.trace_id, details={'offset': offset, 'limit': limit})
        return result


@app.post('/api/v1/history/{object_id}/restore-proposal', tags=['changes'], status_code=201)
def propose_history_restore(object_id: UUID, command: history.RestoreInput,
                            context: Annotated[RequestContext, Depends(request_context)]) -> dict:
    require_knowledge_hub_permission(context, 'change.decide')
    require_knowledge_hub_permission(context, 'change.submit')
    try:
        with database.transaction(context.actor_id) as connection:
            object_row = connection.execute(
                'SELECT object_id FROM smartlib.knowledge_object WHERE object_id=%s', (object_id,)
            ).fetchone()
            if not object_row:
                raise LookupError('对象不可用')
            return history.restore(connection, object_id, command, context.actor_id, context.trace_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@app.post("/api/v1/changes", tags=["changes"], status_code=201)
def create_change(command: changes.SubmissionInput,
                  context: Annotated[RequestContext, Depends(request_context)]) -> dict:
    require_knowledge_hub_permission(context, "change.submit")
    try:
        with database.transaction(context.actor_id) as connection:
            return changes.submit(connection, command, context.actor_id, context.trace_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=422, detail="改动不符合目标数据的领域约束") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@app.get("/api/v1/changes/{submission_id}", tags=["changes"])
def read_change(submission_id: UUID,
                context: Annotated[RequestContext, Depends(request_context)]) -> dict:
    try:
        with database.transaction(context.actor_id) as connection:
            return changes.get_submission(connection, submission_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.post("/api/v1/changes/{submission_id}/decision", tags=["changes"])
def decide_change(submission_id: UUID, command: changes.DecisionInput,
                  context: Annotated[RequestContext, Depends(request_context)]) -> dict:
    require_knowledge_hub_permission(context, "change.decide")
    try:
        with database.transaction(context.actor_id) as connection:
            return changes.decide(connection, submission_id, command, context.actor_id, context.trace_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=422, detail="改动不符合目标数据的领域约束") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/changes", tags=["changes"])
def list_changes(context: Annotated[RequestContext, Depends(request_context)]) -> list[dict]:
    with database.transaction(context.actor_id) as connection:
        rows = connection.execute("""SELECT s.submission_id,o.canonical_name AS context_name
            FROM smartlib.change_submission s
            JOIN smartlib.knowledge_object o ON o.object_id=s.context_object_id
            WHERE s.workflow_key='entity' ORDER BY s.created_at DESC LIMIT 100""").fetchall()
        return [{**changes.get_submission(connection,row["submission_id"]),"context_name":row["context_name"]}
                for row in rows]


@app.get("/api/v1/identities/{object_id}", tags=["identities"])
def identity_detail(object_id: UUID,
                    context: Annotated[RequestContext, Depends(request_context)]) -> dict:
    from smartlib_platform.identities.service import get_identity
    try:
        with database.transaction(context.actor_id) as connection:
            return get_identity(connection, object_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get('/api/v1/scholar-graph/analyses', response_model=list[SavedAnalysis],
         tags=['scholar-graph'], operation_id='list_saved_analyses')
def saved_analyses(context: Annotated[RequestContext, Depends(request_context)]):
    with database.transaction(context.actor_id) as connection:
        return list_analyses(connection)


@app.get('/api/v1/scholar-graph/planning', response_model=list[PlanningRecord],
         tags=['scholar-graph'], operation_id='list_planning_records')
def planning_records(context: Annotated[RequestContext, Depends(request_context)]):
    with database.transaction(context.actor_id) as connection:
        return list_records(connection)


@app.post('/api/v1/scholar-graph/planning', response_model=PlanningRecord, status_code=201,
          tags=['scholar-graph'], operation_id='create_planning_record')
def create_planning_record(command: PlanningCommand,
                           context: Annotated[RequestContext, Depends(request_context)]):
    try:
        with database.transaction(context.actor_id) as connection:
            result = add_record(connection, command, context.actor_id)
            record_allowed(connection, actor_id=context.actor_id, action='scholar_graph.planning.save',
                           resource_type='research_planning_record',resource_id=str(result.record_id),
                           trace_id=context.trace_id, details={'kind': command.kind})
            return result
    except IntegrityError as exc:
        raise HTTPException(409, '记录已被修订或关联约束发生变化，请刷新后重试') from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post('/api/v1/scholar-graph/planning/applications/import',
          response_model=list[PlanningRecord],status_code=201,
          tags=['scholar-graph'],operation_id='import_application_records')
def import_application_records(file: UploadFile,
                               context: Annotated[RequestContext, Depends(request_context)]):
    try:
        commands = parse_application_csv(file.file.read(2 * 1024 * 1024 + 1))
        with database.transaction(context.actor_id) as connection:
            results = [add_record(connection, command, context.actor_id) for command in commands]
            record_allowed(connection,actor_id=context.actor_id,action='scholar_graph.planning.import',
                           resource_type='research_planning_record',resource_id='batch',
                           trace_id=context.trace_id,details={'count': len(results)})
            return results
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(409, '申请编号重复或关联约束变化，整批未写入') from exc


@app.get('/api/v1/scholar-graph/analyses/{analysis_id}', response_model=SavedAnalysisDetail,
         tags=['scholar-graph'], operation_id='get_saved_analysis', response_model_exclude_unset=True)
def saved_analysis(analysis_id: UUID, context: Annotated[RequestContext, Depends(request_context)]):
    with database.transaction(context.actor_id) as connection:
        result = get_analysis(connection, analysis_id)
        if result is None:
            raise HTTPException(404, '分析不存在或当前无权读取')
        return result


@app.post('/api/v1/scholar-graph/analyses', response_model=SavedAnalysis,
          tags=['scholar-graph'], operation_id='create_saved_analysis', status_code=201)
def create_saved_analysis(command: AnalysisSaveCommand,
                          context: Annotated[RequestContext, Depends(request_context)]):
    definition = command.definition
    if (definition.start_year is not None and definition.end_year is not None
            and definition.start_year > definition.end_year):
        raise HTTPException(422, '开始年份不能晚于结束年份')
    if definition.graph_query and definition.custom_scope_id:
        raise HTTPException(422, '不能同时提交查询语句和已保存范围')
    with database.transaction(context.actor_id, repeatable_read=True) as connection:
        graph_query = definition.graph_query
        scope_name = None
        if definition.custom_scope_id:
            scope = get_custom_scope(connection, definition.custom_scope_id)
            if scope is None:
                raise HTTPException(404, '自定义范围不存在或不可访问')
            graph_query, scope_name = scope.graph_query, scope.name
            # Retain the actual query so later template runs do not depend on a mutable/deleted scope.
            definition.graph_query = graph_query
            definition.custom_scope_id = None
        publication_ids = None
        if graph_query:
            publication_ids, _ = _execute_custom_graph_scope(connection, graph_query, context)
        result = None
        if command.kind == 'snapshot':
            result = get_scholar_graph_analytics(
                connection, graph_backend=settings.graph_backend,
                start_year=definition.start_year,end_year=definition.end_year,
                project_kind_ids=definition.project_kind_ids,
                organization_ids=definition.organization_ids,scholar_ids=definition.scholar_ids,
                minimum_publication_count=definition.minimum_publication_count,
                institution_settings=definition.institution_settings.model_dump_json(),
                edge_limit=definition.edge_limit, people_focus_id=definition.people_focus_id,
                people_organization_id=definition.people_organization_id,
                people_include_external=definition.people_include_external,
                custom_publication_ids=publication_ids,custom_scope_name=scope_name,
            )
        if result is not None and result.disciplines is not None and result.disciplines.workspace is not None:
            from smartlib_platform.knowledge.research_profiles import load_profiles
            from smartlib_platform.knowledge import research_workbench as research
            workspace = result.disciplines.workspace
            preferences = definition.workspace_settings
            scheme = next((item for item in workspace.schemes
                           if item.key == preferences.get('discipline.scheme')), None)
            scheme = scheme or next((item for item in workspace.schemes
                                     if not item.scheme.startswith('GBT_13745')), None)
            if scheme is not None:
                institution = preferences.get('direction.institution')
                institution_id = UUID(institution['id']) if isinstance(institution, dict) and institution.get('id') else None
                result.direction_extensions = research.analytics(
                    load_profiles(connection, publication_ids=[p.object_id for p in workspace.papers]),
                    collaboration_memberships=research.collaboration_members(connection, institution_id) if institution_id else None,
                    scheme=scheme.scheme, scheme_version=scheme.version)
        saved = save_analysis(connection, command, context.actor_id, result)
        record_allowed(connection, actor_id=context.actor_id, action='scholar_graph.analysis.save',
                       resource_type='saved_analysis',resource_id=str(saved.analysis_id),
                       trace_id=context.trace_id,details={'kind':command.kind})
        return saved


register_leadership_routes(app, database, RequestContext, request_context, settings, _execute_custom_graph_scope)
