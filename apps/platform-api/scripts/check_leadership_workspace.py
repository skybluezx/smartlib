"""Exercise real storage/analytics within a rollback-only transaction."""
from datetime import date
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from smartlib_platform.foundation.config import Settings
from smartlib_platform.leadership.models import MatterCommand, ReportCommand, Scope
from smartlib_platform.leadership import service
from smartlib_platform.graph_analytics.service import get_scholar_graph_analytics

settings=Settings.from_env()
with psycopg.connect(settings.database_url,row_factory=dict_row) as c:
    before=c.execute('SELECT count(*) n FROM smartlib.knowledge_object').fetchone()['n']
    record_before=c.execute('SELECT count(*) n FROM smartlib.leadership_record').fetchone()['n']
    with c.transaction(force_rollback=True):
        c.execute("SELECT set_config('smartlib.actor_id',%s,true)",(str(settings.dev_actor_id),))
        scope=Scope();ids=service.paper_ids(c,scope);summary=service.dashboard(c,scope,ids)
        assert summary['coverage']['publications']==len(ids)
        print('SUMMARY',summary['coverage'])
        print('RESOURCES',len(service.resources(c)))
        empty=Scope(start_year=1500,end_year=1500)
        assert service.dashboard(c,empty,service.paper_ids(c,empty))['coverage']['publications']==0
        command=MatterCommand(category='cultivation',title='回滚验收支持事项',question='核实合作结构与研究基础',evidence='本地验收来源，全部回滚',responsible_unit='验收单位',next_step='核实数据后回看',review_on=date(2026,12,1),object_ids=ids[:1])
        first=service.save_matter(c,command,settings.dev_actor_id)
        revised=command.model_copy(update={'supersedes_id':first['record_id'],'status':'tracking'})
        second=service.save_matter(c,revised,settings.dev_actor_id)
        assert service.get_record(c,first['record_id'])['payload']['status']=='proposed'
        assert service.get_record(c,second['record_id'])['payload']['status']=='tracking'
        try: service.save_matter(c,revised,settings.dev_actor_id)
        except ValueError: pass
        else: raise AssertionError('Stale matter revision was accepted')
        journals=get_scholar_graph_analytics(c,graph_backend=settings.graph_backend,selected_module='journals',custom_publication_ids=ids).journals
        report=service.save_report(c,ReportCommand(title='回滚验收简报'),settings.dev_actor_id,summary,journals)
        saved=service.get_record(c,report['record_id'])
        assert saved['result_hash']==report['result_hash']
        assert saved['payload']['summary']['coverage']==summary['coverage']
        c.execute("SELECT set_config('smartlib.actor_id',%s,true)",(str(uuid4()),))
        assert not service.list_records(c,'report')
        try: service.get_record(c,report['record_id'])
        except LookupError: pass
        else: raise AssertionError('Cross-actor report leaked')
        c.execute("SELECT set_config('smartlib.actor_id',%s,true)",(str(settings.dev_actor_id),))
    assert c.execute('SELECT count(*) n FROM smartlib.knowledge_object').fetchone()['n']==before
    assert c.execute('SELECT count(*) n FROM smartlib.leadership_record').fetchone()['n']==record_before
    print('PASS: real summary, resources, empty range, matter versions, stale conflict, frozen report, cross-actor RLS; all writes rolled back')
