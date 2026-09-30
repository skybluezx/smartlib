"""Read-only historical snapshots; restoration always submits a reviewed field change."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from smartlib_platform.changes import service


class RestoreInput(BaseModel):
    revision_id: UUID
    side: Literal['before_value', 'after_value'] = 'after_value'
    field_path: str
    base_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


def list_history(c, object_id, limit=50, offset=0, scope='all'):
    rows = c.execute(
        'SELECT smartlib.read_object_history(%s,%s,%s,NULL,%s) AS item',
        (object_id, limit, offset, 'knowledge_object' if scope == 'object' else None),
    ).fetchall()
    items = [r['item'] for r in rows]
    for item in items:
        table = item['entity_table']
        snap = item['after_value'] or item['before_value']
        current = None
        if table == 'relation_assertion':
            current = c.execute('SELECT version FROM smartlib.relation_assertion WHERE relation_id=%s', (item['entity_id'],)).fetchone()
        elif table in ('knowledge_object', 'person_profile', 'organization_profile'):
            current = c.execute('SELECT version FROM smartlib.knowledge_object WHERE object_id=%s', (snap['object_id'],)).fetchone()
        item['current_version'] = current['version'] if current else None
    reviews = c.execute('''SELECT DISTINCT s.submission_id,s.source_label,s.status,s.created_at,
         s.created_by,s.decided_at,s.decided_by,s.decision_reason,s.source_uri
         FROM smartlib.change_submission s LEFT JOIN smartlib.change_proposal p USING(submission_id)
         WHERE s.context_object_id=%s OR p.target_object_id=%s
         ORDER BY s.created_at DESC LIMIT 20''', (object_id, object_id)).fetchall()
    obj = c.execute('SELECT canonical_name FROM smartlib.knowledge_object WHERE object_id=%s', (object_id,)).fetchone()
    return {'items': items, 'object_name': obj['canonical_name'] if obj else None, 'reviews': reviews, 'offset': offset, 'limit': limit,
            'historical_context_note': '旧快照未补写变更原因；新增覆盖表从 V45 启用时开始记录。'}


def restore(c, object_id, command, actor, trace):
    row = c.execute('SELECT smartlib.read_object_history(%s,1,0,%s) AS item',
                    (object_id, command.revision_id)).fetchone()
    if not row:
        raise LookupError('历史记录不可用')
    revision = row['item']
    snapshot = revision[command.side]
    if not snapshot:
        raise ValueError('所选历史状态不存在，不能作为恢复内容')
    table = revision['entity_table']
    field = command.field_path
    if table in ('knowledge_object', 'relation_assertion'):
        kind = 'object' if table == 'knowledge_object' else 'relation'
        target = revision['entity_id']
        if field.startswith('attributes.'):
            key = field[11:]
            if key not in snapshot.get('attributes', {}):
                raise ValueError('历史状态不存在该属性；不能把缺失属性自动转换为空值')
            value = snapshot['attributes'][key]
        elif field in ('canonical_name', 'description', 'confidence') and field in snapshot:
            value = snapshot[field]
        else:
            raise ValueError('该字段须通过专属治理流程恢复')
    elif table in ('person_profile', 'organization_profile') and field.startswith('profile.'):
        kind, target = 'object', snapshot['object_id']
        if field[8:] not in snapshot:
            raise ValueError('历史状态不存在该字段')
        value = snapshot[field[8:]]
    else:
        raise ValueError('署名、证据、资源及别名记录请通过专属治理流程修改，不直接整行恢复')
    return service.submit(c, service.SubmissionInput(
        context_object_id=object_id,
        source_label='历史版本恢复申请',
        source_uri=f'urn:smartlib:revision:{command.revision_id}:{command.side}',
        reason=command.reason,
        proposals=[service.ProposalInput(target_kind=kind, target_id=target,
            field_path=field, proposed_value=value, base_version=command.base_version)],
    ), actor, trace)
