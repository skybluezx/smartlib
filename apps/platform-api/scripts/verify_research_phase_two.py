"""Transactional live-data QA. All test mutations are rolled back."""
import json
import os
from uuid import UUID,uuid4
import psycopg
from psycopg.rows import dict_row
from smartlib_platform.knowledge import research_workbench as w
from smartlib_platform.knowledge.research_profiles import load_profiles
from smartlib_platform.knowledge.research_standards import StandardPackage,import_package

actor=UUID('00000000-0000-4000-8000-000000000001')
pid=UUID('c1d432a4-e692-5f3d-8105-e1b28b714738')
class Store:
    def put_bytes(self,key,data,mime):self.data=data;return type('Saved',(),{'version_id':'rollback-only'})()
    def get_bytes(self,key):return self.data

with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],row_factory=dict_row) as c:
    with c.transaction(force_rollback=True):
        w.stamp(c,actor,'本轮功能验收，事务结束全部回滚')
        generated=w.generate(c,w.Generate(publication_ids=[pid]),actor)
        assert generated['count']==1
        taskid=generated['task_ids'][0]
        task=next(x for x in w.task_list(c) if x['id']==taskid)
        assert task['machine_suggestion']['has_abstract']
        terms=w.standards(c,'NSFC_APPLICATION_CODE','H19','2026')
        term=next(t for t in terms if t['code']=='H19')
        version=c.execute('SELECT version FROM smartlib.knowledge_object WHERE object_id=%s',(pid,)).fetchone()['version']
        proposal=w.Proposal(object_id=pid,labels=[w.Label(standard_id=term['id'],role='primary')],source='验收模拟，不保留',evidence='老年护理主方向测试；本事务必须回滚。',expected_object_version=version)
        w.propose(c,proposal,actor)
        def decision(tid):
            updated=c.execute('SELECT updated_at FROM smartlib.review_task WHERE review_task_id=%s',(UUID(tid),)).fetchone()['updated_at'].isoformat()
            return w.BatchDecision(task_ids=[tid],action='approve',reason='回滚验收，不改变正式资料',expected_updated_at={tid:updated})
        result=w.decide(c,decision(taskid),actor)
        assert len(result['processed'])==1
        profile=load_profiles(c)[str(pid)]
        assert profile['coverage']['NSFC_APPLICATION_CODE']==1
        with c.transaction(force_rollback=True):
            try:w.decide(c,w.BatchDecision(task_ids=[taskid],action='approve',reason='重复审核测试'),actor)
            except ValueError:pass
            else:raise AssertionError('Repeated approval accepted')
        project=w.projects(c,load_profiles(c))[0]
        pp=w.Proposal(object_id=project['id'],kind='project',labels=[w.Label(standard_id=term['id'],role='primary')],source='回滚测试权威资料',evidence='仅功能验收测试，不保存为真实项目资料。',summary='仅功能验收测试研究内容，不保存到系统中。',expected_object_version=project['version'])
        pt=w.propose(c,pp,actor)
        w.decide(c,decision(pt['task_id']),actor)
        assert not next(p for p in w.projects(c,load_profiles(c)) if p['id']==project['id'])['missing']
        package=StandardPackage(version='qa-rollback',source_url='https://www.moe.gov.cn/qa',verified_against_official=True,terms=[{'code':'QA','name':'测试上级'},{'code':'QA01','name':'测试下级','parent_code':'QA'}])
        imported=import_package(c,package,package.model_dump_json().encode(),Store(),actor)
        assert imported['imported']==2
        assert import_package(c,package,package.model_dump_json().encode(),Store(),actor)['replay']
        new_id=uuid4()
        c.execute("INSERT INTO smartlib.knowledge_object(object_id,object_type,canonical_name,visibility,quality_state,review_state,attributes,created_by) VALUES(%s,'publication','回滚验收用论文','restricted','unverified','pending','{}',%s)",(new_id,actor))
        c.execute("INSERT INTO smartlib.publication_metadata(publication_id,title,attributes,created_by) VALUES(%s,'Nursing care validation only','{}',%s)",(new_id,actor))
        assert c.execute("SELECT 1 FROM smartlib.review_task WHERE object_id=%s AND issue_type='RESEARCH_CLASSIFICATION' AND machine_suggestion='{}'",(new_id,)).fetchone()
        w.generate(c,w.Generate(publication_ids=[new_id]),actor)
        c.execute("UPDATE smartlib.publication_metadata SET title='Updated nursing care validation only' WHERE publication_id=%s",(new_id,))
        assert c.execute("SELECT 1 FROM smartlib.review_task WHERE object_id=%s AND machine_suggestion='{}'",(new_id,)).fetchone()
        print(json.dumps({'rollback':True,'checks':['candidate_generation','manual_proposal','approval','duplicate_guard','project_authoritative_fields','versioned_standard_import','standard_replay','profile_refresh']},ensure_ascii=False))
