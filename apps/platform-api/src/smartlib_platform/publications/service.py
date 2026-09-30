import hashlib
import html
import json
import re
from uuid import UUID, uuid4, uuid5

import httpx
from psycopg.types.json import Jsonb

from smartlib_platform.foundation.config import Settings
from smartlib_platform.foundation.database import DbConnection

from .incremental import get_incremental_status, promote_staged_fulltext
from .models import (
    FieldVerificationView,
    FulltextPreverificationView,
    ImportBatchSummary,
    KnowledgeHubOverview,
    PublicationIdentifiers,
    PublicationVerificationDecisionCommand,
    PublicationVerificationDecisionResult,
    PublicationVerificationDetail,
    PublicationVerificationPage,
    PublicationVerificationSummary,
    ServiceStatus,
    VerificationCheckView,
    VerificationDecisionView,
    VerificationLayerView,
)

PUBLICATION_NAMESPACE = UUID("df2fabc9-b9bb-4dcc-8e11-3460ca0871fa")
CROSSREF_SOURCE_ID = UUID("26aaf5cb-9d1e-5ed7-b1c6-5415a63abf09")
NCBI_SOURCE_ID = UUID("eb13a9a8-f769-589d-b51b-1ff433cc6af4")


class VerificationStateConflict(RuntimeError):
    pass



def _existing_publication_for_verification(
    connection: DbConnection, matched_publication_id: UUID | None, doi: str | None
) -> dict[str, UUID] | None:
    """Keep an import's established identity when its raw record lacks a DOI."""
    linked = None
    if matched_publication_id:
        linked = connection.execute(
            """SELECT current_object.object_id AS publication_id
                 FROM smartlib.knowledge_object original
                 JOIN smartlib.knowledge_object current_object
                   ON current_object.object_id=COALESCE(
                       (original.attributes->>'merged_into_publication_id')::uuid,
                       original.object_id)
                WHERE original.object_id=%s AND original.object_type='publication'
                  AND current_object.object_type='publication'
                  AND current_object.system_to='infinity'::timestamptz""",
            (matched_publication_id,),
        ).fetchone()
        if linked is None:
            raise ValueError("关联论文已失效, 请先核对合并后的论文身份")
    if not doi:
        return linked
    existing = connection.execute(
        """SELECT identifier.publication_id
             FROM smartlib.publication_identifier identifier
             JOIN smartlib.knowledge_object object
               ON object.object_id=identifier.publication_id
            WHERE identifier.identifier_type='doi'
              AND lower(identifier.normalized_value)=%s
              AND identifier.verification_status<>'rejected'
              AND object.system_to='infinity'::timestamptz LIMIT 1""",
        (doi,),
    ).fetchone()
    if linked and existing and linked["publication_id"] != existing["publication_id"]:
        raise ValueError("DOI 与已关联论文指向不同对象, 请先核验并合并论文身份")
    if linked:
        conflicting = connection.execute(
            """SELECT publication_identifier_id FROM smartlib.publication_identifier
                WHERE publication_id=%s AND identifier_type='doi'
                  AND verification_status<>'rejected'
                  AND lower(normalized_value)<>%s LIMIT 1""",
            (linked["publication_id"], doi),
        ).fetchone()
        if conflicting:
            raise ValueError("DOI 与已关联论文的已核验 DOI 不一致, 请先核对论文身份")
    return existing or linked


def _probe(url: str) -> tuple[bool, str]:
    try:
        response = httpx.get(url, timeout=1.5)
        response.raise_for_status()
        return True, f"HTTP {response.status_code}"
    except (httpx.HTTPError, ValueError) as exc:
        return False, type(exc).__name__


def get_knowledge_hub_overview(connection: DbConnection, settings: Settings) -> KnowledgeHubOverview:
    counts = connection.execute(
        """SELECT object_type, count(*) AS total
             FROM smartlib.knowledge_object
            WHERE system_to = 'infinity'::timestamptz
            GROUP BY object_type"""
    ).fetchall()
    states = connection.execute(
        """SELECT verification_state, count(*) AS total
             FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
            GROUP BY verification_state"""
    ).fetchall()
    layer_states = connection.execute(
        """SELECT layer_code, layer_status, count(*) AS total
             FROM smartlib.publication_verification_layer
            GROUP BY layer_code, layer_status"""
    ).fetchall()
    metrics = connection.execute(
        """SELECT
              (SELECT count(*) FROM smartlib.source_system) AS registered_sources,
              (SELECT count(*) FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
                WHERE verification_state IN (
                  'pending','normalized','manual_review',
                  'reverification_required','verification_conflict'
                )) AS pending,
              (SELECT count(*) FROM smartlib.publication_field_verification
                WHERE verification_status = 'conflict') AS conflicts,
              smartlib_projection.pending_event_count(
                'postgres_search', 'hugegraph_graph') AS unpublished_events,
              clock_timestamp() AS generated_at"""
    ).fetchone()
    latest = connection.execute(
        """SELECT batch.batch_id, batch.dataset_version, batch.batch_state,
                  count(item.record_id) AS total_items,
                  count(*) FILTER (WHERE item.verification_state IN
                    ('auto_verified','human_verified','corrected')) AS completed_items,
                  count(*) FILTER (WHERE item.verification_state IN (
                    'manual_review','reverification_required','verification_conflict'
                  )) AS manual_review_items,
                  count(*) FILTER (WHERE item.verification_state = 'rejected') AS rejected_items,
                  batch.updated_at
             FROM smartlib.ingestion_batch batch
             LEFT JOIN (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
               ON input_record.batch_id = batch.batch_id
            WHERE batch.pipeline_key='publication'
            GROUP BY batch.batch_id,batch.dataset_version,batch.batch_state,batch.updated_at
            ORDER BY batch.updated_at DESC LIMIT 1"""
    ).fetchone()
    hugegraph_ok, hugegraph_detail = _probe(f"{settings.hugegraph_url.rstrip('/')}/versions")
    opensearch_ok, opensearch_detail = _probe(settings.opensearch_url.rstrip("/"))
    services = [
        ServiceStatus(
            service="postgresql",
            state="available",
            purpose="权威业务记录与事务",
            active_backend=True,
            detail="当前 API 权威数据源",
        ),
        ServiceStatus(
            service="hugegraph",
            state="available" if hugegraph_ok else "unavailable",
            purpose="图实体、关系与图查询",
            active_backend=settings.graph_backend == "hugegraph",
            detail=("当前图查询后端" if settings.graph_backend == "hugegraph" else "投影服务已配置")
            + f" · {hugegraph_detail}",
        ),
        ServiceStatus(
            service="opensearch",
            state="available" if opensearch_ok else "unavailable",
            purpose="全文检索与索引",
            active_backend=settings.search_backend == "opensearch",
            detail=("当前检索后端" if settings.search_backend == "opensearch" else "索引服务已配置")
            + f" · {opensearch_detail}",
        ),
    ]
    assert metrics is not None
    return KnowledgeHubOverview(
        entity_counts={row["object_type"]: row["total"] for row in counts},
        registered_sources=metrics["registered_sources"],
        pending_verifications=metrics["pending"],
        conflict_fields=metrics["conflicts"],
        verification_states={row["verification_state"]: row["total"] for row in states},
        verification_layers={
            code: {row["layer_status"]: row["total"] for row in layer_states if row["layer_code"] == code}
            for code in ("identity", "attribution", "enrichment")
        },
        latest_import=ImportBatchSummary.model_validate(latest) if latest else None,
        unpublished_events=metrics["unpublished_events"],
        services=services,
        generated_at=metrics["generated_at"],
    )


def list_publication_verifications(
    connection: DbConnection,
    *,
    state: str | None,
    fulltext_status: str | None,
    query: str | None,
    page: int,
    page_size: int,
) -> PublicationVerificationPage:
    clauses = []
    params: list[object] = []
    if state:
        clauses.append("item.verification_state = %s")
        params.append(state)
    if fulltext_status:
        clauses.append(
            "EXISTS (SELECT 1 FROM smartlib.publication_fulltext_preverification pre_filter "
            "WHERE pre_filter.record_id=item.record_id "
            "AND pre_filter.preverification_status=%s)"
        )
        params.append(fulltext_status)
    if query:
        clauses.append(
            "(submission.awardee_name_raw ILIKE %s OR input_record.normalized_payload->>'title' ILIKE %s "
            "OR input_record.normalized_payload->>'doi' ILIKE %s "
            "OR input_record.normalized_payload->>'pmid' ILIKE %s)"
        )
        pattern = f"%{query.strip()}%"
        params.extend([pattern] * 4)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total_row = connection.execute(
        f"""SELECT count(*) AS total FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
             {where}""", params
    ).fetchone()
    rows = connection.execute(
        f"""SELECT item.record_id, COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer) AS source_row_number,
                   submission.awardee_name_raw AS awardee_name,
                   input_record.normalized_payload->>'title' AS title,
                   input_record.normalized_payload->>'journal_or_conference' AS journal_name,
                   NULLIF(input_record.normalized_payload->>'publication_year','')::integer
                     AS publication_year,
                   input_record.normalized_payload->>'doi' AS doi,
                   input_record.normalized_payload->>'pmid' AS pmid,
                   input_record.normalized_payload->>'pmcid' AS pmcid,
                   item.verification_state,
                   count(field.field_verification_id) FILTER
                     (WHERE field.verification_status = 'conflict') AS conflict_count,
                   count(DISTINCT field.candidate_source_code) FILTER
                     (WHERE field.candidate_source_code IS NOT NULL) AS evidence_source_count,
                   min(field.match_score) AS minimum_match_score,
                   COALESCE((
                     SELECT jsonb_object_agg(layer.layer_code, layer.layer_status)
                     FROM smartlib.publication_verification_layer AS layer
                     WHERE layer.record_id = item.record_id
                   ), '{{}}'::jsonb) AS layer_statuses,
                   (
                     SELECT pre.preverification_status
                     FROM smartlib.publication_fulltext_preverification AS pre
                     WHERE pre.record_id=item.record_id
                       AND pre.preverification_status <> 'superseded'
                     ORDER BY pre.evaluated_at DESC LIMIT 1
                   ) AS fulltext_preverification_status,
                   input_record.updated_at
              FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
              LEFT JOIN smartlib.publication_field_verification field
                ON field.record_id = item.record_id
              {where}
             GROUP BY item.record_id,COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer),submission.awardee_name_raw,
                      input_record.normalized_payload,item.verification_state,input_record.updated_at
             ORDER BY CASE item.verification_state WHEN 'manual_review' THEN 1
                       WHEN 'normalized' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END,
                      COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer)
             LIMIT %s OFFSET %s""",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    state_rows = connection.execute(
        """SELECT verification_state, count(*) AS total FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id)) GROUP BY 1"""
    ).fetchall()
    fulltext_state_rows = connection.execute(
        """SELECT preverification_status, count(*) AS total
             FROM smartlib.publication_fulltext_preverification
            WHERE preverification_status <> 'superseded'
            GROUP BY preverification_status"""
    ).fetchall()
    items = [
        PublicationVerificationSummary(
            **{
                key: row[key]
                for key in (
                    "record_id",
                    "source_row_number",
                    "awardee_name",
                    "title",
                    "journal_name",
                    "publication_year",
                    "verification_state",
                    "conflict_count",
                    "evidence_source_count",
                    "minimum_match_score",
                    "layer_statuses",
                    "fulltext_preverification_status",
                    "updated_at",
                )
            },
            identifiers=PublicationIdentifiers(doi=row["doi"], pmid=row["pmid"], pmcid=row["pmcid"]),
        )
        for row in rows
    ]
    return PublicationVerificationPage(
        items=items,
        total=total_row["total"] if total_row else 0,
        page=page,
        page_size=page_size,
        state_counts={row["verification_state"]: row["total"] for row in state_rows},
        fulltext_preverification_counts={
            row["preverification_status"]: row["total"] for row in fulltext_state_rows
        },
    )


def _source_url(code: str | None, external_id: str | None) -> str | None:
    if not code or not external_id:
        return None
    if code == "crossref":
        return f"https://api.crossref.org/works/{external_id}"
    if code == "ncbi_pubmed":
        return f"https://pubmed.ncbi.nlm.nih.gov/{external_id}/"
    return None


def get_publication_verification(
    connection: DbConnection, record_id: UUID
) -> PublicationVerificationDetail | None:
    item = connection.execute(
        """SELECT record_id, batch_id, input_record.source_locator->>'sheet' AS source_sheet,
                  COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer) AS source_row_number,
                  awardee_name_raw AS awardee_name, awardee_person_id, verification_state,
                  matched_publication_id, raw_payload, normalized_payload, updated_at
             FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
             WHERE record_id = %s""",
        (record_id,),
    ).fetchone()
    if not item:
        return None
    field_rows = connection.execute(
        """SELECT field_name, source_value, candidate_value, candidate_source_code,
                  candidate_external_id, match_score, verification_status,
                  difference_type, decision_reason
             FROM smartlib.publication_field_verification
            WHERE record_id = %s ORDER BY field_name""",
        (record_id,),
    ).fetchall()
    decision = connection.execute(
        """SELECT decision, decision_reason, decision_method, decided_by, decided_at
             FROM smartlib.publication_verification_decision
            WHERE record_id = %s AND is_current""",
        (record_id,),
    ).fetchone()
    layer_rows = connection.execute(
        """SELECT layer_id, layer_code, layer_status, is_blocking, check_count,
                  passed_count, conflict_count, missing_count, rule_version, evaluated_at
             FROM smartlib.publication_verification_layer
            WHERE record_id = %s
            ORDER BY CASE layer_code WHEN 'identity' THEN 1
                       WHEN 'attribution' THEN 2 ELSE 3 END""",
        (record_id,),
    ).fetchall()
    layers = []
    for layer in layer_rows:
        check_rows = connection.execute(
            """SELECT check_code, check_label, check_status, severity, source_value,
                      authoritative_value, evidence_sources, details, decision_reason
                 FROM smartlib.publication_verification_check
                WHERE layer_id = %s
                ORDER BY CASE severity WHEN 'blocking' THEN 1
                           WHEN 'warning' THEN 2 ELSE 3 END, check_code""",
            (layer["layer_id"],),
        ).fetchall()
        layers.append(
            VerificationLayerView(
                **{
                    key: layer[key]
                    for key in (
                        "layer_code",
                        "layer_status",
                        "is_blocking",
                        "check_count",
                        "passed_count",
                        "conflict_count",
                        "missing_count",
                        "rule_version",
                        "evaluated_at",
                    )
                },
                checks=[VerificationCheckView.model_validate(row) for row in check_rows],
            )
        )
    actor_audits = connection.execute("SELECT * FROM smartlib.list_actor_audit_events(100)").fetchall()
    audits = [
        row
        for row in actor_audits
        if row["resource_id"] == str(record_id) and row["action"].startswith("publication.")
    ][:20]
    preverification = connection.execute(
        """SELECT preverification_id,content_checksum,source_path,file_name,size_bytes,
                  page_count,text_length,extraction_method,match_confidence,match_score,
                  preverification_status,proposed_metadata,proposed_identifiers,checks,
                  shared_source_rows,rule_version,evaluated_at
             FROM smartlib.publication_fulltext_preverification
            WHERE record_id=%s AND preverification_status <> 'superseded'
            ORDER BY evaluated_at DESC LIMIT 1""",
        (record_id,),
    ).fetchone()
    return PublicationVerificationDetail(
        **item,
        fields=[
            FieldVerificationView(
                **row, source_url=_source_url(row["candidate_source_code"], row["candidate_external_id"])
            )
            for row in field_rows
        ],
        layers=layers,
        current_decision=VerificationDecisionView.model_validate(decision) if decision else None,
        audit_events=audits,
        incremental_status=(
            get_incremental_status(connection, item["matched_publication_id"])
            if item["matched_publication_id"]
            else None
        ),
        fulltext_preverification=(
            FulltextPreverificationView.model_validate(preverification) if preverification else None
        ),
    )


def _selected_fields(
    fields: list[dict[str, object]],
    choices: dict[str, str],
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    selected: dict[str, object] = {}
    for field in fields:
        name = str(field["field_name"])
        choice = choices.get(name, "candidate" if field["verification_status"] == "matched" else "source")
        value = field[f"{choice}_value"]
        if value is not None:
            selected[name] = html.unescape(value) if isinstance(value, str) else value
    for name, value in (overrides or {}).items():
        if value not in (None, ""):
            selected[name] = html.unescape(value) if isinstance(value, str) else value
    return selected


def unresolved_blocking_checks(
    checks: list[dict[str, object]], command: PublicationVerificationDecisionCommand
) -> list[dict[str, object]]:
    known_codes = {str(row["check_code"]) for row in checks}
    unknown_codes = sorted(set(command.accepted_check_codes) - known_codes)
    if unknown_codes:
        raise ValueError(f"unknown verification check codes: {', '.join(unknown_codes)}")

    accepted_codes = set(command.accepted_check_codes)
    if command.awardee_author_order:
        accepted_codes.add("awardee_author_match")
    if command.corresponding_author_orders:
        accepted_codes.add("corresponding_author")

    fulltext_check_statuses = {
        str(row["check_code"]): row["check_status"]
        for row in checks
        if str(row["check_code"]).startswith("fulltext_")
    }
    fulltext_supports_author_selection = bool(command.awardee_author_order) and all(
        fulltext_check_statuses.get(code) == "passed"
        for code in ("fulltext_parse_completeness", "fulltext_title_identity")
    )
    non_overridable = set() if fulltext_supports_author_selection else {"author_list_available"}
    invalid_overrides = sorted(accepted_codes & non_overridable)
    if invalid_overrides:
        raise ValueError(f"verification checks cannot be manually overridden: {', '.join(invalid_overrides)}")

    def effective_status(row: dict[str, object]) -> object:
        if row["check_code"] != "identifier_triangle":
            return row["check_status"]
        source = row.get("source_value") if isinstance(row.get("source_value"), dict) else {}
        authority = (
            row.get("authoritative_value")
            if isinstance(row.get("authoritative_value"), dict)
            else {}
        )
        comparisons = authority.get("comparisons")
        if isinstance(comparisons, list):
            statuses = {
                item.get("status") for item in comparisons if isinstance(item, dict)
            }
        else:
            statuses: set[str] = set()

            def compare(left: object, right: object) -> None:
                if left in (None, "") or right in (None, ""):
                    return
                normalized_left = str(left).strip().casefold()
                normalized_right = str(right).strip().casefold()
                statuses.add("passed" if normalized_left == normalized_right else "conflict")

            compare(source.get("doi"), authority.get("crossref_doi"))
            compare(authority.get("crossref_doi"), authority.get("pubmed_doi"))
            compare(source.get("pmid"), authority.get("pubmed_pmid"))
            compare(source.get("pmcid"), authority.get("pubmed_pmcid"))
            if (authority.get("pubmed_pmid") or source.get("pmid")) and authority.get("pubmed_pmcid"):
                statuses.add("passed")
        if "conflict" in statuses:
            return "conflict"
        if "passed" in statuses:
            return "passed"
        return "missing"

    return [
        row
        for row in checks
        if row["severity"] == "blocking"
        and effective_status(row) in {"conflict", "missing", "pending"}
        and row["check_code"] not in accepted_codes
    ]


def _plain_title(value: object) -> str:
    decoded = html.unescape(str(value))
    decoded = re.sub(
        r"\s*<sup>\s*([+\-\u2212])\s*</sup>\s*",
        lambda match: f"{match.group(1)} ",
        decoded,
        flags=re.IGNORECASE,
    )
    without_markup = re.sub(r"<[^>]+>", "", decoded)
    return re.sub(r"\s+", " ", without_markup).strip()


def _checksum(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _ensure_source_systems(connection: DbConnection) -> None:
    connection.execute(
        """INSERT INTO smartlib.source_system
                  (source_system_id, code, name, owner_department, source_type,
                   authorization_state, metadata)
             VALUES
                  (%s, 'crossref_rest', 'Crossref REST API', 'Crossref', 'api', 'approved',
                   '{"scope":"public bibliographic metadata"}'::jsonb),
                  (%s, 'ncbi_pubmed_api', 'NCBI PubMed E-utilities',
                   'U.S. National Library of Medicine', 'api', 'approved',
                   '{"scope":"public PubMed bibliographic metadata"}'::jsonb)
             ON CONFLICT (code) DO NOTHING""",
        (CROSSREF_SOURCE_ID, NCBI_SOURCE_ID),
    )


def decide_publication_verification(
    connection: DbConnection,
    *,
    record_id: UUID,
    command: PublicationVerificationDecisionCommand,
    actor_id: UUID,
    trace_id: str,
    approve: bool,
) -> PublicationVerificationDecisionResult:
    item = connection.execute(
        """SELECT item.*,input_record.batch_id,input_record.raw_payload,input_record.normalized_payload,
                   input_record.created_by,input_record.updated_at,
                   COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer) AS source_row_number,
                   submission.awardee_name_raw,submission.awardee_person_id,submission.representative_work_number
            FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
            WHERE item.record_id = %s FOR UPDATE OF input_record,item""",
        (record_id,),
    ).fetchone()
    if not item:
        raise LookupError("publication verification item not found")
    fields = connection.execute(
        "SELECT * FROM smartlib.publication_field_verification WHERE record_id = %s",
        (record_id,),
    ).fetchall()
    layer_checks = connection.execute(
        """SELECT layer.layer_code, check_row.*
             FROM smartlib.publication_verification_check AS check_row
             JOIN smartlib.publication_verification_layer AS layer
               ON layer.layer_id = check_row.layer_id
            WHERE layer.record_id = %s""",
        (record_id,),
    ).fetchall()
    has_open_layer_checks = any(row["check_status"] != "passed" for row in layer_checks)
    if item["verification_state"] != "manual_review" and (not approve or not has_open_layer_checks):
        raise VerificationStateConflict(
            f"item is {item['verification_state']}; it has no open verification layers to confirm"
        )
    previous = {"verification_state": item["verification_state"], "publication_id": None}
    if not approve:
        decision_id = uuid4()
        connection.execute(
            """INSERT INTO smartlib.publication_verification_decision
                      (verification_decision_id, record_id, decision, decision_reason,
                       decision_method, evidence_summary, decided_by, created_by)
                 VALUES (%s, %s, 'rejected', %s, 'human', %s, %s, %s)""",
            (
                decision_id,
                record_id,
                command.reason,
                Jsonb({"rejection_scope": "source_record"}),
                actor_id,
                actor_id,
            ),
        )
        connection.execute(
            """UPDATE smartlib.publication_intake_record
                  SET verification_state='rejected' WHERE record_id=%s""",
            (record_id,),
        )
        connection.execute(
            """INSERT INTO audit.audit_event
                      (actor_id, action, resource_type, resource_id, decision, trace_id, details)
                 VALUES (%s, 'publication.verification.rejected', 'publication_intake_record', %s,
                         'allowed', %s, %s)""",
            (
                actor_id,
                str(record_id),
                trace_id,
                Jsonb(
                    {
                        "before": previous,
                        "after": {"verification_state": "rejected"},
                        "reason": command.reason,
                    }
                ),
            ),
        )
        return PublicationVerificationDecisionResult(
            record_id=record_id,
            publication_id=None,
            verification_state="rejected",
            decision="rejected",
            outbox_events_created=0,
        )

    unresolved_checks = unresolved_blocking_checks(layer_checks, command)
    if unresolved_checks:
        labels = ", ".join(
            str(row.get("check_label") or row["check_code"]) for row in unresolved_checks
        )
        raise ValueError(f"存在尚未处理的阻断核验项: {labels}")

    selected = _selected_fields(fields, command.field_choices, command.field_overrides)
    normalized = item["normalized_payload"]
    title = _plain_title(selected.get("title") or normalized.get("title") or "")
    if not title:
        raise ValueError("a publication title is required")
    doi = str(selected.get("doi") or normalized.get("doi") or "").strip().lower() or None
    existing = _existing_publication_for_verification(
        connection, item.get("matched_publication_id"), doi
    )
    publication_id = (
        existing["publication_id"]
        if existing
        else uuid5(
            PUBLICATION_NAMESPACE, f"publication:doi:{doi}" if doi else f"publication:item:{record_id}"
        )
    )
    inserted_object = 0
    if not existing:
        inserted_object = connection.execute(
            """INSERT INTO smartlib.knowledge_object
                      (object_id, object_type, canonical_name, description, visibility,
                       quality_state, review_state, attributes, created_by)
                 VALUES (%s, 'publication', %s, %s, 'restricted', 'validated', 'approved', %s, %s)
                 ON CONFLICT (object_id) DO NOTHING""",
            (
                publication_id,
                title,
                "Human-verified publication from controlled import.",
                Jsonb({"doi": doi, "human_verified": True, "record_id": str(record_id)}),
                actor_id,
            ),
        ).rowcount
        connection.execute(
            """INSERT INTO smartlib.publication_metadata
                      (publication_id, title, journal_name, publication_year, publication_status,
                       attributes, created_by)
                 VALUES (%s, %s, %s, %s, 'published', %s, %s)
                 ON CONFLICT (publication_id) DO NOTHING""",
            (
                publication_id,
                title,
                selected.get("journal_name") or normalized.get("journal_or_conference"),
                selected.get("publication_year") or normalized.get("publication_year"),
                Jsonb({"human_decision_reason": command.reason}),
                actor_id,
            ),
        )
    _ensure_source_systems(connection)
    source_reference_ids: dict[str, UUID] = {}
    for code, source_id, external_id, uri in (
        ("crossref", CROSSREF_SOURCE_ID, doi, f"https://api.crossref.org/works/{doi}" if doi else None),
        (
            "ncbi_pubmed",
            NCBI_SOURCE_ID,
            str(selected.get("pmid") or normalized.get("pmid") or "") or None,
            None,
        ),
    ):
        if not external_id:
            continue
        if code == "ncbi_pubmed":
            uri = f"https://pubmed.ncbi.nlm.nih.gov/{external_id}/"
        reference_id = uuid5(PUBLICATION_NAMESPACE, f"{code}-reference:{external_id}")
        source_reference = connection.execute(
            """INSERT INTO smartlib.source_reference
                      (source_reference_id, object_id, source_system_id, external_id,
                       source_version, payload_checksum, raw_object_uri, metadata)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                 ON CONFLICT (source_system_id, external_id, version) DO UPDATE SET
                   object_id=excluded.object_id,
                   source_version=excluded.source_version,
                   payload_checksum=excluded.payload_checksum,
                   raw_object_uri=excluded.raw_object_uri,
                   metadata=smartlib.source_reference.metadata || excluded.metadata,
                   observed_at=clock_timestamp()
                 RETURNING source_reference_id""",
            (
                reference_id,
                publication_id,
                source_id,
                external_id,
                "human-verification-v1",
                _checksum({"selected": selected, "record_id": str(record_id)}),
                uri,
                Jsonb({"human_verified": True, "trace_id": trace_id}),
            ),
        ).fetchone()
        source_reference_ids[code] = source_reference["source_reference_id"]
    passed_check_values = {
        row["check_code"]: row["authoritative_value"]
        for row in layer_checks
        if row["check_status"] == "passed" or row["check_code"] in command.accepted_check_codes
    }
    identifiers = {
        "doi": doi,
        "pmid": str(selected.get("pmid") or normalized.get("pmid") or "") or None,
        "pmcid": str(
            selected.get("pmcid")
            or passed_check_values.get("pmcid")
            or normalized.get("pmcid")
            or ""
        ).upper()
        or None,
    }
    for kind, value in identifiers.items():
        if not value:
            continue
        identifier_id = uuid5(PUBLICATION_NAMESPACE, f"publication-identifier:{kind}:{value}")
        reference_id = source_reference_ids.get("crossref" if kind == "doi" else "ncbi_pubmed")
        connection.execute(
            """INSERT INTO smartlib.publication_identifier
                      (publication_identifier_id, publication_id, identifier_type, raw_value,
                       normalized_value, is_primary, verification_status, source_reference_id, created_by)
                 VALUES (%s, %s, %s, %s, %s, true, 'matched', %s, %s)
                 ON CONFLICT (publication_identifier_id) DO NOTHING""",
            (identifier_id, publication_id, kind, value, value, reference_id, actor_id),
        )
    if inserted_object:
        for order, author_name in enumerate(normalized.get("authors_raw_list") or [], start=1):
            connection.execute(
                """INSERT INTO smartlib.publication_authorship
                          (publication_authorship_id, publication_id, author_order, author_name_raw,
                           author_name_normalized, is_first_author, match_status,
                           verification_status, created_by)
                     VALUES (%s,%s,%s,%s,%s,%s,'unmatched','matched',%s)
                     ON CONFLICT (publication_id, author_order) DO NOTHING""",
                (
                    uuid5(PUBLICATION_NAMESPACE, f"publication-authorship:{publication_id}:{order}"),
                    publication_id,
                    order,
                    author_name,
                    author_name,
                    order == 1,
                    actor_id,
                ),
            )
    evidence_id = uuid5(PUBLICATION_NAMESPACE, f"publication-human-evidence:{record_id}")
    connection.execute(
        """INSERT INTO smartlib.evidence_record
                  (evidence_id, object_id, source_reference_id, evidence_type, citation, excerpt,
                   visibility, license_tags, content_checksum, metadata, created_by)
             VALUES (%s,%s,%s,'manual_review',%s,%s,'restricted',%s,%s,%s,%s)
             ON CONFLICT (evidence_id) DO NOTHING""",
        (
            evidence_id,
            publication_id,
            source_reference_ids.get("crossref"),
            f"Excel row {item['source_row_number']} manually verified",
            command.reason,
            ["controlled-file", "human-review"],
            item["row_checksum"],
            Jsonb(
                {
                    "record_id": str(record_id),
                    "field_choices": command.field_choices,
                    "field_overrides": command.field_overrides,
                }
            ),
            actor_id,
        ),
    )
    relation_id: UUID | None = None
    if item["awardee_person_id"] and command.awardee_author_order:
        connection.execute(
            """UPDATE smartlib.publication_authorship
                  SET person_object_id=%s, match_status='matched',
                      verification_status='matched'
                WHERE publication_id=%s AND author_order=%s""",
            (item["awardee_person_id"], publication_id, command.awardee_author_order),
        )
        relation = connection.execute(
            """SELECT relation_id FROM smartlib.relation_assertion
                 WHERE subject_id=%s AND predicate='person.authored' AND object_id=%s""",
            (item["awardee_person_id"], publication_id),
        ).fetchone()
        if relation is None:
            raise RuntimeError("authorship graph projection was not synchronized")
        relation_id = relation["relation_id"]
        connection.execute(
            """INSERT INTO smartlib.relation_evidence (relation_id,evidence_id)
                 VALUES (%s,%s) ON CONFLICT DO NOTHING""",
            (relation_id, evidence_id),
        )
    if command.corresponding_author_orders:
        connection.execute(
            """UPDATE smartlib.publication_authorship SET is_corresponding_author=true
                WHERE publication_id=%s AND author_order=ANY(%s)""",
            (publication_id, command.corresponding_author_orders),
        )
    if command.co_first_author_orders:
        connection.execute(
            """UPDATE smartlib.publication_authorship SET is_co_first_author=true
                WHERE publication_id=%s AND author_order=ANY(%s)""",
            (publication_id, command.co_first_author_orders),
        )
    corrected = any(
        choice == "candidate"
        and next(
            (f["source_value"] != f["candidate_value"] for f in fields if f["field_name"] == name), False
        )
        for name, choice in command.field_choices.items()
    ) or any(
        next(
            (field["source_value"] != value for field in fields if field["field_name"] == name),
            True,
        )
        for name, value in command.field_overrides.items()
        if value not in (None, "")
    )
    decision = "corrected" if corrected else "human_verified"
    accepted_codes = set(command.accepted_check_codes)
    if command.awardee_author_order:
        accepted_codes.add("awardee_author_match")
    if command.corresponding_author_orders:
        accepted_codes.add("corresponding_author")
    connection.execute(
        """UPDATE smartlib.publication_verification_decision SET is_current=false
            WHERE record_id=%s AND is_current""",
        (record_id,),
    )
    connection.execute(
        """INSERT INTO smartlib.publication_verification_decision
                  (verification_decision_id, record_id, publication_id, decision,
                   decision_reason, decision_method, rule_version, evidence_summary,
                   decided_by, created_by)
             VALUES (%s,%s,%s,%s,%s,'human','human-verification-v1',%s,%s,%s)""",
        (
            uuid4(),
            record_id,
            publication_id,
            decision,
            command.reason,
            Jsonb(
                {
                    "selected_fields": selected,
                    "field_choices": command.field_choices,
                    "field_overrides": command.field_overrides,
                    "accepted_check_codes": sorted(accepted_codes),
                    "awardee_author_order": command.awardee_author_order,
                }
            ),
            actor_id,
            actor_id,
        ),
    )
    connection.execute(
        """UPDATE smartlib.publication_intake_record
              SET verification_state=%s, matched_publication_id=%s WHERE record_id=%s""",
        (decision, publication_id, record_id),
    )
    for field in fields:
        choice = command.field_choices.get(field["field_name"])
        override_present = field["field_name"] in command.field_overrides
        if choice or override_present:
            status = (
                "corrected"
                if (
                    override_present
                    and field["source_value"] != command.field_overrides[field["field_name"]]
                )
                or (choice == "candidate" and field["source_value"] != field["candidate_value"])
                else "matched"
            )
            connection.execute(
                """UPDATE smartlib.publication_field_verification
                      SET verification_status=%s, decision_reason=%s
                    WHERE field_verification_id=%s""",
                (status, command.reason, field["field_verification_id"]),
            )
    for check_code in accepted_codes:
        connection.execute(
            """UPDATE smartlib.publication_verification_check AS check_row
                  SET check_status='passed', decision_reason=%s,
                      decided_by=%s, decided_at=clock_timestamp(),
                      details=details || %s
                 FROM smartlib.publication_verification_layer AS layer
                WHERE check_row.layer_id=layer.layer_id
                  AND layer.record_id=%s AND check_row.check_code=%s""",
            (
                command.reason,
                actor_id,
                Jsonb(
                    {
                        "human_accepted": True,
                        "awardee_author_order": command.awardee_author_order,
                        "corresponding_author_orders": command.corresponding_author_orders,
                        "co_first_author_orders": command.co_first_author_orders,
                    }
                ),
                record_id,
                check_code,
            ),
        )
    promote_staged_fulltext(
        connection,
        record_id=record_id,
        publication_id=publication_id,
        actor_id=actor_id,
        trace_id=trace_id,
    )
    connection.execute(
        """UPDATE smartlib.publication_verification_layer AS layer
              SET passed_count=summary.passed_count,
                  conflict_count=summary.conflict_count,
                  missing_count=summary.missing_count,
                  layer_status=CASE
                    WHEN summary.blocking_conflicts > 0 THEN 'conflict'
                    WHEN summary.blocking_open > 0 THEN 'incomplete'
                    WHEN layer.layer_code='enrichment' AND summary.missing_count > 0
                      THEN 'incomplete'
                    ELSE 'passed' END
             FROM (
               SELECT check_row.layer_id,
                      count(*) FILTER (WHERE check_status='passed') AS passed_count,
                      count(*) FILTER (WHERE check_status='conflict') AS conflict_count,
                      count(*) FILTER (WHERE check_status IN ('missing','pending')) AS missing_count,
                      count(*) FILTER (
                        WHERE severity='blocking' AND check_status='conflict'
                      ) AS blocking_conflicts,
                      count(*) FILTER (
                        WHERE severity='blocking' AND check_status IN ('missing','pending')
                      ) AS blocking_open
                 FROM smartlib.publication_verification_check AS check_row
                GROUP BY check_row.layer_id
             ) AS summary
            WHERE layer.layer_id=summary.layer_id AND layer.record_id=%s""",
        (record_id,),
    )
    event_count = 0
    if inserted_object:
        event_count += connection.execute(
            """INSERT INTO smartlib.outbox_event
                      (event_id, aggregate_type, aggregate_id, event_type, payload, trace_id)
                 VALUES (%s,'knowledge_object',%s,'knowledge.publication.verified',%s,%s)
                 ON CONFLICT (event_id) DO NOTHING""",
            (
                uuid5(PUBLICATION_NAMESPACE, f"outbox:human-publication:{record_id}"),
                publication_id,
                Jsonb({"object_id": str(publication_id), "version": 1, "doi": doi}),
                trace_id,
            ),
        ).rowcount
    if relation_id is not None:
        event_count += connection.execute(
            """INSERT INTO smartlib.outbox_event
                      (event_id, aggregate_type, aggregate_id, event_type, payload, trace_id)
                 VALUES (%s,'relation_assertion',%s,'knowledge.relation.verified',%s,%s)
                 ON CONFLICT (event_id) DO NOTHING""",
            (
                uuid5(PUBLICATION_NAMESPACE, f"outbox:human-authorship:{record_id}"),
                relation_id,
                Jsonb(
                    {
                        "relation_id": str(relation_id),
                        "subject_id": str(item["awardee_person_id"]),
                        "object_id": str(publication_id),
                        "predicate": "person.authored",
                        "version": 1,
                    }
                ),
                trace_id,
            ),
        ).rowcount
    connection.execute(
        """INSERT INTO audit.audit_event
                  (actor_id, action, resource_type, resource_id, decision, trace_id, details)
             VALUES (%s,'publication.verification.approved','publication_intake_record',%s,
                     'allowed',%s,%s)""",
        (
            actor_id,
            str(record_id),
            trace_id,
            Jsonb(
                {
                    "before": previous,
                    "after": {"verification_state": decision, "publication_id": str(publication_id)},
                    "reason": command.reason,
                    "field_choices": command.field_choices,
                    "field_overrides": command.field_overrides,
                    "accepted_check_codes": sorted(accepted_codes),
                    "awardee_author_order": command.awardee_author_order,
                    "corresponding_author_orders": command.corresponding_author_orders,
                    "co_first_author_orders": command.co_first_author_orders,
                }
            ),
        ),
    )
    return PublicationVerificationDecisionResult(
        record_id=record_id,
        publication_id=publication_id,
        verification_state=decision,
        decision=decision,
        outbox_events_created=event_count,
    )
