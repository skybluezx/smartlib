import pytest
from smartlib_platform.knowledge.research_workbench import exact_candidates, analytics
from smartlib_platform.knowledge.research_standards import StandardPackage, validate_package

def test_mentions_are_bounded_and_not_substring_matches():
    term={'id':'1','name':'Nursing Care','attributes':{'scheme':'MESH','scheme_code':'D1','scheme_version':'2026'}}
    assert exact_candidates('nursing caregiver',[term])==[]
    result=exact_candidates('Nursing care interventions',[term])
    assert result[0]['role']=='topic' and '需判断' in result[0]['note']

def test_standard_cycles_duplicates_and_source_attestation():
    data={'version':'2022','source_url':'https://www.moe.gov.cn/source','verified_against_official':True,
          'terms':[{'code':'A','name':'类别甲','parent_code':'B'},{'code':'B','name':'类别乙','parent_code':'A'}]}
    with pytest.raises(ValueError,match='循环'):validate_package(StandardPackage(**data))
    data['terms'][0]['parent_code']=None
    validate_package(StandardPackage(**data))
    data['verified_against_official']=False
    with pytest.raises(ValueError,match='官方'):validate_package(StandardPackage(**data))

def test_official_same_name_different_codes_are_preserved():
    data={'version':'2022','source_url':'https://www.moe.gov.cn/source','verified_against_official':True,
          'terms':[{'code':'10','name':'医学'},{'code':'1002','name':'临床医学','parent_code':'10'},
                   {'code':'1051','name':'临床医学','parent_code':'10'}]}
    validate_package(StandardPackage(**data))
    data['terms'].append(data['terms'][1])
    with pytest.raises(ValueError,match='重复代码'):validate_package(StandardPackage(**data))

def test_verified_body_evidence_is_not_an_abstract():
    from smartlib_platform.knowledge.research_workbench import content
    class Result:
        def __init__(self,row):self.row=row
        def fetchone(self):return self.row
    class Connection:
        def execute(self,sql,args):
            if 'publication_metadata' in sql:return Result({'title':'Letter','abstract':None,'version':1})
            return Result({'evidence_id':'e1','metadata':{'abstract':'','body_excerpt':'Verified body text.', 'source_kind':'pdf_body_excerpt_not_abstract'}})
    result=content(Connection(),'p1')
    assert not result['has_abstract'] and result['has_body_evidence']
    assert '不是摘要' in result['basis'] and 'Verified body text.' in result['text']

def test_analytics_deduplicates_and_separates_versions():
    profiles={'p':{'object_type':'publication','name':'论文','papers':[{'publication_id':'p','year':2025}],
                  'rows':[{'scheme':'NSFC_APPLICATION_CODE','scheme_version':'2026','code':'H19','name':'老年医学'},
                          {'scheme':'NSFC_APPLICATION_CODE','scheme_version':'2025','code':'H01','name':'呼吸'}]}}
    result=analytics(profiles)
    assert result['papers']==result['classified']==1
    assert len(result['directions'])==2 and result['intersections']==[]
    assert analytics(profiles,'unavailable')['papers']==0


def test_collaboration_institution_limits_both_people_not_paper_statistics():
    profiles = {}
    for i in range(6):
        pid = f'p{i}'
        profiles[pid] = {'object_type': 'publication', 'name': pid,
            'papers': [{'publication_id': pid, 'year': 2025}],
            'rows': [{'scheme': 'NSFC_APPLICATION_CODE', 'scheme_version': '2026',
                      'code': code, 'name': code} for code in ['H01', 'H02']]}
    for i, person in enumerate(['a', 'b', 'external']):
        profiles[person] = {'object_type': 'person', 'name': person,
            'papers': [{'publication_id': f'p{2*i}'}, {'publication_id': f'p{2*i+1}'}]}
    unfiltered = analytics(profiles)
    filtered = analytics(profiles, collaboration_memberships={'a': {'p0'}, 'b': {'p2'}, 'external': {'outside-scope'}})
    assert len(unfiltered['collaboration']) == 3
    assert [(r['a'], r['b']) for r in filtered['collaboration']] == [('a', 'b')]
    assert filtered['directions'] == unfiltered['directions']
    assert filtered['papers'] == 6
    assert analytics(profiles, collaboration_memberships={})['collaboration'] == []


def test_analytics_respects_selected_classification_system_and_version():
    profiles={'p': {'object_type': 'publication', 'name': '论文',
        'papers':[{'publication_id':'p','year':2025}],
        'rows':[{'scheme':'INCITES_WOS','scheme_version':'snapshot','code':'X','name':'方向'},
                {'scheme':'NSFC_APPLICATION_CODE','scheme_version':'2026','code':'H','name':'国自然方向'}]}}
    result=analytics(profiles,scheme='INCITES_WOS',scheme_version='snapshot')
    assert [r['code'] for r in result['directions']]==['X']
    assert analytics(profiles,scheme='INCITES_WOS',scheme_version='absent')['classified']==0


def test_revision_replaces_eligible_labels_only_in_proposed_version(monkeypatch):
    from datetime import datetime, timezone
    from uuid import UUID
    from smartlib_platform.knowledge import research_workbench as workbench

    now = datetime.now(timezone.utc)
    task_id, paper_id, actor_id = UUID(int=1), UUID(int=2), UUID(int=3)
    old = [{'id': str(UUID(int=4)), 'version': 7, 'review_state': 'pending'}]
    proposal = {'object_id': str(paper_id), 'kind': 'classification',
                'labels': [{'standard_id': str(UUID(int=5)), 'role': 'primary'}],
                'source': '全文依据', 'evidence': '这是经全文核对后的研究内容依据。',
                'expected_object_version': 1, 'method': 'human_proposal',
                'checksum': 'current', 'base_relations': {old[0]['id']: 7}}
    class Result:
        def __init__(self, row=None): self.row = row
        def fetchone(self): return self.row
    class Connection:
        def __init__(self): self.updates = []
        def execute(self, sql, args):
            if 'SELECT * FROM smartlib.review_task' in sql:
                return Result({'state': 'open', 'updated_at': now, 'object_id': paper_id,
                               'machine_suggestion': proposal})
            if 'SELECT version,attributes' in sql: return Result({'version': 1, 'attributes': {}})
            if 'UPDATE smartlib.relation_assertion' in sql: self.updates.append((sql, args))
            return Result()
    monkeypatch.setattr(workbench, 'stamp', lambda *args: None)
    monkeypatch.setattr(workbench, 'current_labels', lambda *args: old)
    monkeypatch.setattr(workbench, 'content', lambda *args: {'checksum': 'current'})
    monkeypatch.setattr(workbench, 'evidence', lambda *args: UUID(int=6))
    monkeypatch.setattr(workbench, 'validate_labels', lambda *args: [
        {'id': str(UUID(int=5)), 'role': 'primary', 'attributes': {
            'scheme': 'NSFC_APPLICATION_CODE', 'scheme_version': '2026', 'scheme_code': 'H01'}}])
    connection = Connection()
    command = workbench.BatchDecision(task_ids=[task_id], action='approve', reason='核对完成',
                                     expected_updated_at={str(task_id): now.isoformat()})
    workbench.decide(connection, command, actor_id)
    assert len(connection.updates) == 1
    sql, parameters = connection.updates[0]
    assert 'analysis_state_eligible(review_state)' in sql
    assert "scheme_version'=%s" in sql and "scheme'=%s" in sql
    assert parameters == (paper_id, 'NSFC_APPLICATION_CODE', '2026')
    assert "review_state='superseded'" in sql
