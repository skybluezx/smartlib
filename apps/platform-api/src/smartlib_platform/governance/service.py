from datetime import UTC, datetime
from uuid import UUID

from psycopg.types.json import Jsonb

from smartlib_platform.foundation.database import DbConnection

from .models import (
    DataAssetTrace,
    EvidenceTrace,
    GovernanceAuditEventView,
    GovernanceDashboard,
    GovernanceSummary,
    KnowledgeObjectProvenanceTrace,
    LicenseGrantView,
    QualityIssueView,
    ReviewTaskCreate,
    ReviewTaskDecision,
    ReviewTaskView,
    SourceReferenceTrace,
)

_REVIEW_TASK_COLUMNS = """review_task_id, issue_type, target_type, target_id, publication_id,
publication_authorship_id, evidence_id, relation_id, object_id, candidate_object_ids,
reason_code, description, machine_suggestion, confidence, state, decision, assigned_to,
reviewed_by, reviewed_at, created_by, created_at, updated_at"""


def get_governance_summary(connection: DbConnection) -> GovernanceSummary:
    row = connection.execute(
        """WITH visible_assets AS (
                   SELECT data_asset_id, source_system_id, synthetic
                     FROM smartlib.data_asset
               ), license_states AS (
                   SELECT CASE
                            WHEN authorization_state = 'pending' THEN 'review_required'
                            WHEN authorization_state <> 'approved' THEN 'denied'
                            WHEN valid_from IS NOT NULL
                                 AND valid_from > clock_timestamp() THEN 'not_yet_valid'
                            WHEN valid_to IS NOT NULL AND valid_to < clock_timestamp() THEN 'expired'
                            ELSE 'effective'
                          END AS effective_state
                     FROM smartlib.license_grant
               )
               SELECT
                   (SELECT count(*) FROM visible_assets) AS visible_assets,
                   (SELECT count(DISTINCT source_system_id) FROM visible_assets) AS registered_sources,
                   (SELECT count(*) FROM license_states) AS license_grants,
                   (SELECT count(*) FROM license_states
                     WHERE effective_state = 'effective') AS effective_license_grants,
                   (SELECT count(*) FROM license_states
                     WHERE effective_state <> 'effective') AS licenses_requiring_review,
                   (SELECT count(*) FROM smartlib.quality_issue
                     WHERE issue_state IN ('open', 'acknowledged')) AS open_quality_issues,
                   (SELECT count(*) FROM smartlib.quality_issue
                     WHERE issue_state IN ('open', 'acknowledged')
                       AND requires_human_confirmation) AS human_confirmation_issues,
                   (SELECT count(*) FROM smartlib.data_contract
                     WHERE contract_state = 'active') AS active_contracts,
                   (SELECT count(*) FROM visible_assets WHERE synthetic) AS synthetic_assets,
                   clock_timestamp() AS generated_at"""
    ).fetchone()
    if row is None:
        raise RuntimeError("governance summary query returned no row")
    return GovernanceSummary.model_validate(row)


def list_license_grants(connection: DbConnection) -> list[LicenseGrantView]:
    rows = connection.execute(
        """SELECT grant_row.*,
                  CASE WHEN grant_row.effective_state = 'effective' THEN 'allow' ELSE 'deny' END AS decision
             FROM (
                 SELECT g.license_grant_id, g.data_asset_id, a.name AS asset_name,
                        s.name AS source_name, g.allowed_content, g.allowed_purposes,
                        g.prohibited_purposes, g.valid_from, g.valid_to,
                        g.authorization_state,
                        CASE
                          WHEN g.authorization_state = 'pending' THEN 'review_required'
                          WHEN g.authorization_state <> 'approved' THEN 'denied'
                          WHEN g.valid_from IS NOT NULL
                               AND g.valid_from > clock_timestamp() THEN 'not_yet_valid'
                          WHEN g.valid_to IS NOT NULL AND g.valid_to < clock_timestamp() THEN 'expired'
                          ELSE 'effective'
                        END AS effective_state,
                        (g.synthetic OR a.synthetic) AS synthetic
                   FROM smartlib.license_grant g
                   JOIN smartlib.data_asset a ON a.data_asset_id = g.data_asset_id
                   JOIN smartlib.source_system s ON s.source_system_id = a.source_system_id
             ) grant_row
             ORDER BY grant_row.asset_name"""
    ).fetchall()
    return [LicenseGrantView.model_validate(row) for row in rows]


def list_quality_issues(connection: DbConnection, *, open_only: bool = True) -> list[QualityIssueView]:
    state_clause = "WHERE i.issue_state IN ('open', 'acknowledged')" if open_only else ""
    rows = connection.execute(
        f"""SELECT i.quality_issue_id, i.data_asset_id, a.name AS asset_name,
                   i.title, i.description, i.severity, i.issue_state,
                   i.requires_human_confirmation, r.code AS quality_rule_code,
                   r.name AS quality_rule_name, run.run_state,
                   run.observed_value, run.expected_value,
                   steward.responsibility, i.detected_at
              FROM smartlib.quality_issue i
              JOIN smartlib.data_asset a ON a.data_asset_id = i.data_asset_id
              LEFT JOIN smartlib.quality_run run ON run.quality_run_id = i.quality_run_id
              LEFT JOIN smartlib.quality_rule r ON r.quality_rule_id = run.quality_rule_id
              LEFT JOIN LATERAL (
                  SELECT sa.responsibility
                    FROM smartlib.stewardship_assignment sa
                   WHERE sa.data_asset_id = i.data_asset_id
                     AND sa.steward_id = i.assigned_to
                     AND sa.valid_from <= clock_timestamp() AND sa.valid_to > clock_timestamp()
                   ORDER BY sa.valid_from DESC LIMIT 1
              ) steward ON true
              {state_clause}
             ORDER BY CASE i.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                                      WHEN 'medium' THEN 3 ELSE 4 END,
                      i.detected_at DESC"""
    ).fetchall()
    return [QualityIssueView.model_validate(row) for row in rows]


def create_review_task(
    connection: DbConnection, command: ReviewTaskCreate, actor_id: UUID
) -> ReviewTaskView:
    row = connection.execute(
        f"""INSERT INTO smartlib.review_task (
                  issue_type, target_type, target_id, publication_id,
                  publication_authorship_id, evidence_id, relation_id, object_id,
                  candidate_object_ids, reason_code, description, machine_suggestion,
                  confidence, assigned_to, created_by
              ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
              RETURNING {_REVIEW_TASK_COLUMNS}""",
        (
            command.issue_type,
            command.target_type,
            command.target_id,
            command.publication_id,
            command.publication_authorship_id,
            command.evidence_id,
            command.relation_id,
            command.object_id,
            command.candidate_object_ids,
            command.reason_code,
            command.description,
            Jsonb(command.machine_suggestion),
            command.confidence,
            command.assigned_to,
            actor_id,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("review task insert returned no row")
    return ReviewTaskView.model_validate(row)


def list_review_tasks(
    connection: DbConnection,
    *,
    state: str | None = None,
    issue_type: str | None = None,
    publication_id: UUID | None = None,
    limit: int = 100,
) -> list[ReviewTaskView]:
    clauses: list[str] = []
    params: list[object] = []
    if state:
        clauses.append("state = %s")
        params.append(state)
    if issue_type:
        clauses.append("issue_type = %s")
        params.append(issue_type)
    if publication_id:
        clauses.append("publication_id = %s")
        params.append(publication_id)
    where = " AND ".join(clauses) if clauses else "TRUE"
    rows = connection.execute(
        f"""SELECT {_REVIEW_TASK_COLUMNS}
              FROM smartlib.review_task
             WHERE {where}
             ORDER BY CASE state WHEN 'open' THEN 1 WHEN 'in_review' THEN 2 ELSE 3 END,
                      created_at
             LIMIT %s""",
        (*params, limit),
    ).fetchall()
    return [ReviewTaskView.model_validate(row) for row in rows]


def decide_review_task(
    connection: DbConnection,
    review_task_id: UUID,
    command: ReviewTaskDecision,
    actor_id: UUID,
) -> ReviewTaskView | None:
    research_task = connection.execute("SELECT issue_type FROM smartlib.review_task WHERE review_task_id=%s", (review_task_id,)).fetchone()
    if research_task and research_task['issue_type'].startswith('RESEARCH_'):
        raise ValueError('研究方向任务必须通过专用工作台审核，以执行分类校验和版本检查')
    final = command.state in {"resolved", "rejected"}
    row = connection.execute(
        f"""UPDATE smartlib.review_task
               SET state = %s,
                   decision = %s,
                   reviewed_by = CASE WHEN %s THEN %s ELSE reviewed_by END,
                   reviewed_at = CASE WHEN %s THEN clock_timestamp() ELSE reviewed_at END
             WHERE review_task_id = %s
               AND state IN ('open', 'in_review')
         RETURNING {_REVIEW_TASK_COLUMNS}""",
        (
            command.state,
            Jsonb(command.decision),
            final,
            actor_id,
            final,
            review_task_id,
        ),
    ).fetchone()
    return ReviewTaskView.model_validate(row) if row else None


def list_governance_audit_events(connection: DbConnection, limit: int = 10) -> list[GovernanceAuditEventView]:
    rows = connection.execute("SELECT * FROM smartlib.list_actor_audit_events(%s)", (limit,)).fetchall()
    return [GovernanceAuditEventView.model_validate(row) for row in rows]


def get_governance_dashboard(connection: DbConnection) -> GovernanceDashboard:
    return GovernanceDashboard(
        summary=get_governance_summary(connection),
        licenses=list_license_grants(connection),
        quality_issues=list_quality_issues(connection),
        audit_events=list_governance_audit_events(connection, 8),
    )


def get_data_asset_trace(connection: DbConnection, data_asset_id: UUID) -> DataAssetTrace | None:
    row = connection.execute(
        """SELECT a.data_asset_id, a.name AS asset_name, a.asset_type, a.lifecycle_state,
                  a.synthetic, a.metadata ->> 'dataset_version' AS dataset_version,
                  d.name AS domain_name, s.source_system_id, s.name AS source_name,
                  s.owner_department AS source_owner_department,
                  s.authorization_state AS source_authorization_state,
                  version_row.version_number AS latest_asset_version,
                  version_row.schema_version AS latest_schema_version,
                  COALESCE(contract_row.codes, ARRAY[]::text[]) AS contract_codes,
                  COALESCE(steward_row.responsibilities, ARRAY[]::text[]) AS steward_responsibilities
             FROM smartlib.data_asset a
             JOIN smartlib.governance_domain d ON d.governance_domain_id = a.governance_domain_id
             JOIN smartlib.source_system s ON s.source_system_id = a.source_system_id
             LEFT JOIN LATERAL (
                 SELECT v.version_number, v.schema_version
                   FROM smartlib.data_asset_version v
                  WHERE v.data_asset_id = a.data_asset_id
                  ORDER BY v.version_number DESC LIMIT 1
             ) version_row ON true
             LEFT JOIN LATERAL (
                 SELECT array_agg(c.code ORDER BY c.code) AS codes
                   FROM smartlib.data_contract c WHERE c.data_asset_id = a.data_asset_id
             ) contract_row ON true
             LEFT JOIN LATERAL (
                 SELECT array_agg(sa.responsibility ORDER BY sa.responsibility) AS responsibilities
                   FROM smartlib.stewardship_assignment sa
                  WHERE sa.data_asset_id = a.data_asset_id
                    AND sa.valid_from <= clock_timestamp() AND sa.valid_to > clock_timestamp()
             ) steward_row ON true
            WHERE a.data_asset_id = %s""",
        (data_asset_id,),
    ).fetchone()
    return DataAssetTrace.model_validate(row) if row else None


def get_knowledge_object_provenance(
    connection: DbConnection, object_id: UUID
) -> KnowledgeObjectProvenanceTrace | None:
    object_row = connection.execute(
        """SELECT object_id, object_type, canonical_name, version AS object_version
             FROM smartlib.knowledge_object WHERE object_id = %s""",
        (object_id,),
    ).fetchone()
    if object_row is None:
        return None
    source_rows = connection.execute(
        """SELECT sr.source_reference_id, sr.source_system_id, s.name AS source_name,
                  sr.external_id, sr.source_version, sr.observed_at, sr.raw_object_uri
             FROM smartlib.source_reference sr
             JOIN smartlib.source_system s ON s.source_system_id = sr.source_system_id
            WHERE sr.object_id = %s
            ORDER BY sr.observed_at DESC""",
        (object_id,),
    ).fetchall()
    evidence_rows = connection.execute(
        """SELECT e.evidence_id, e.source_reference_id, e.evidence_type, e.evidence_kind,
                  e.fulltext_resource_id, e.page_number, e.evidence_locator,
                  e.verification_state, e.citation, e.excerpt, e.created_at
             FROM smartlib.evidence_record e
            WHERE e.object_id = %s
               OR e.source_reference_id IN (
                   SELECT sr.source_reference_id FROM smartlib.source_reference sr
                    WHERE sr.object_id = %s
               )
            ORDER BY e.created_at DESC""",
        (object_id, object_id),
    ).fetchall()
    return KnowledgeObjectProvenanceTrace(
        **object_row,
        source_references=[SourceReferenceTrace.model_validate(row) for row in source_rows],
        evidence=[EvidenceTrace.model_validate(row) for row in evidence_rows],
    )


def effective_license_state(
    authorization_state: str,
    valid_from: datetime | None,
    valid_to: datetime | None,
    *,
    now: datetime | None = None,
) -> str:
    """Pure policy helper used by non-SQL adapters and contract tests."""
    instant = now or datetime.now(UTC)
    if authorization_state == "pending":
        return "review_required"
    if authorization_state != "approved":
        return "denied"
    if valid_from is not None and valid_from > instant:
        return "not_yet_valid"
    if valid_to is not None and valid_to < instant:
        return "expired"
    return "effective"
