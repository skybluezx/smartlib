# ruff: noqa: RUF001 -- Chinese interface messages.
"""Evidence-backed, owner-scoped application and intervention registers.

These registers never imply a complete population or causal impact.
"""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator

from smartlib_platform.foundation.database import DbConnection


class ApplicationRecord(BaseModel):
    reference: str = Field(min_length=1, max_length=150)
    title: str = Field(min_length=1, max_length=500)
    applicant_id: UUID
    project_kind_id: UUID
    deadline: date
    submitted_on: date
    decision: Literal['pending', 'awarded', 'declined', 'withdrawn'] = 'pending'
    decided_on: date | None = None
    project_id: UUID | None = None
    prior_publication_ids: list[UUID] = Field(default_factory=list, max_length=500)
    evidence: str = Field(min_length=1, max_length=4000)

    @model_validator(mode='after')
    def dates(self):
        if self.submitted_on > self.deadline:
            raise ValueError('提交时间不能晚于申请截止日')
        if self.decision != 'pending' and self.decided_on is None:
            raise ValueError('已决定的申请必须填写决定日期')
        if self.decided_on and self.decided_on < self.submitted_on:
            raise ValueError('决定日期不能早于提交日期')
        if self.project_id and self.decision != 'awarded':
            raise ValueError('只有获批申请可以关联正式项目')
        return self


class SupportAction(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=4000)
    beneficiary_ids: list[UUID] = Field(min_length=1, max_length=100)
    support: str = Field(min_length=1, max_length=4000)
    expected_change: str = Field(min_length=1, max_length=4000)
    started_on: date
    review_on: date
    decision: Literal['proposed', 'adopted', 'adjusted', 'declined', 'completed'] = 'proposed'
    decision_reason: str = Field(min_length=1, max_length=4000)
    baseline_analysis_id: UUID | None = None
    evidence: str = Field(min_length=1, max_length=4000)

    @model_validator(mode='after')
    def dates(self):
        if self.review_on < self.started_on:
            raise ValueError('复盘日期不能早于行动开始日期')
        return self


class ActionReview(BaseModel):
    action_id: UUID
    reviewed_on: date
    observed_change: str = Field(min_length=1, max_length=4000)
    alternative_explanations: str = Field(min_length=1, max_length=4000)
    decision: Literal['continue', 'adjust', 'stop', 'complete']
    decision_reason: str = Field(min_length=1, max_length=4000)
    followup_analysis_id: UUID | None = None
    evidence: str = Field(min_length=1, max_length=4000)


class PlanningCommand(BaseModel):
    kind: Literal['application', 'action', 'review']
    supersedes_id: UUID | None = None
    application: ApplicationRecord | None = None
    action: SupportAction | None = None
    review: ActionReview | None = None

    @model_validator(mode='after')
    def payload(self):
        if getattr(self, self.kind) is None or sum(x is not None for x in
                (self.application, self.action, self.review)) != 1:
            raise ValueError('仅提交与类型对应的一项内容')
        return self


class PlanningRecord(BaseModel):
    record_id: UUID
    kind: str
    payload: dict
    created_at: datetime
    supersedes_id: UUID | None = None


def list_records(connection: DbConnection) -> list[PlanningRecord]:
    return [PlanningRecord.model_validate(r) for r in connection.execute(
        """SELECT r.* FROM smartlib.research_planning_record r WHERE r.parent_id IS NULL
        OR EXISTS (SELECT 1 FROM smartlib.research_planning_record p WHERE p.record_id=r.parent_id)
        ORDER BY r.created_at DESC LIMIT 1000"""
    ).fetchall()]


def add_record(connection: DbConnection, command: PlanningCommand, actor_id: UUID) -> PlanningRecord:
    payload = getattr(command, command.kind)
    required: dict[UUID, set[str] | None] = {}
    snapshot_id = None
    previous = None
    if command.supersedes_id:
        previous = connection.execute("""SELECT * FROM smartlib.research_planning_record
            WHERE record_id=%s""", (command.supersedes_id,)).fetchone()
        if not previous or previous['kind'] != command.kind:
            raise ValueError('原记录不存在、类型不一致或不可访问')
        if connection.execute('SELECT 1 FROM smartlib.research_planning_record WHERE supersedes_id=%s',
                              (command.supersedes_id,)).fetchone():
            raise ValueError('该记录已有更新版本，请刷新后修改最新版本')
    if command.application:
        a = command.application
        required[a.applicant_id] = {'person'}
        required[a.project_kind_id] = {'funding_program'}
        if a.project_id:
            required[a.project_id] = {'project'}
        for pid in a.prior_publication_ids:
            required[pid] = {'publication'}
        if previous and previous['payload']['reference'] != a.reference:
            raise ValueError('修订申请时不能改变申请编号')
        if not previous and connection.execute("""SELECT 1 FROM smartlib.research_planning_record
            WHERE kind='application' AND payload->>'reference'=%s""", (a.reference,)).fetchone():
            raise ValueError('当前身份已登记该申请编号，请勿重复录入')
        # Require an exact dated event before the deadline, never infer Jan 1 from a year.
        for pid in a.prior_publication_ids:
            row = connection.execute("""SELECT least(published_online_at,published_print_at) AS published
                FROM smartlib.publication_metadata WHERE publication_id=%s""", (pid,)).fetchone()
            if not row or not row['published'] or row['published'] > a.deadline:
                raise ValueError('前期论文必须有不晚于截止日的精确发表日期；仅年份不足以纳入')
    if command.action:
        required = dict.fromkeys(command.action.beneficiary_ids, None)
        snapshot_id = command.action.baseline_analysis_id
    if command.review:
        row = connection.execute("""SELECT payload,object_ids FROM smartlib.research_planning_record
            WHERE record_id=%s AND kind='action'""", (command.review.action_id,)).fetchone()
        if not row:
            raise ValueError('支持措施不存在或不可访问')
        required = dict.fromkeys(row['object_ids'], None)
        if command.review.reviewed_on < date.fromisoformat(row['payload']['started_on']):
            raise ValueError('复盘日期不能早于支持措施开始日期')
        snapshot_id = command.review.followup_analysis_id
    for oid, types in required.items():
        row = connection.execute("""SELECT object_type FROM smartlib.knowledge_object
            WHERE object_id=%s AND system_to='infinity'
              AND smartlib.analysis_state_eligible(review_state)""", (oid,)).fetchone()
        if not row or (types and row['object_type'] not in types):
            raise ValueError('关联对象不存在、类型不符或无权访问')
    if snapshot_id and not connection.execute("""SELECT 1 FROM smartlib.saved_analysis
        WHERE analysis_id=%s AND kind='snapshot'""", (snapshot_id,)).fetchone():
        raise ValueError('基线或后续快照不存在或不可访问')
    row = connection.execute("""INSERT INTO smartlib.research_planning_record
        (kind,payload,created_by,object_ids,snapshot_id,parent_id,supersedes_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (
            command.kind, Jsonb(payload.model_dump(mode='json')), actor_id,
            list(required), snapshot_id, command.review.action_id if command.review else None,
            command.supersedes_id,
        )).fetchone()
    return PlanningRecord.model_validate(row)


def parse_application_csv(content: bytes) -> list[PlanningCommand]:
    import csv
    import io

    if len(content) > 2 * 1024 * 1024:
        raise ValueError('CSV不能超过2 MB')
    try:
        reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
        allowed = set(ApplicationRecord.model_fields)
        headers = reader.fieldnames or []
        if not headers or len(headers) != len(set(headers)) or not set(headers) <= allowed:
            raise ValueError('CSV表头缺失、重复或包含不支持的字段，请使用模板')
        result = []
        for index, row in enumerate(reader, 2):
            if len(result) >= 500:
                raise ValueError('单批最多500条申请')
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'第{index}行列数与表头不一致')
            values = {k: v.strip() for k, v in row.items() if v.strip()}
            if 'prior_publication_ids' in values:
                values['prior_publication_ids'] = [
                    p.strip() for p in values['prior_publication_ids'].split(';') if p.strip()
                ]
            try:
                record = ApplicationRecord.model_validate(values)
            except ValueError as exc:
                raise ValueError(f'第{index}行字段不完整或格式错误，请检查日期、对象编号和决定状态') from exc
            result.append(PlanningCommand(kind='application', application=record))
        if not result:
            raise ValueError('CSV没有申请记录')
        return result
    except UnicodeDecodeError as exc:
        raise ValueError('CSV必须使用UTF-8编码') from exc
