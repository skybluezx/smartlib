"""Exercise history and reviewed restore on isolated fixture rows; ALWAYS rollback."""
import os
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from smartlib_platform.changes import history, service

actor = UUID(os.environ['SMARTLIB_DEV_ACTOR_ID'])
with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'], row_factory=dict_row) as c:
    try:
        c.execute("SELECT set_config('smartlib.actor_id',%s,true)", (str(actor),))
        oid = c.execute("""INSERT INTO smartlib.knowledge_object(object_type,canonical_name,attributes,created_by)
           VALUES('organization','__history_isolated_fixture__',
           '{"source":"history-test","identity_resolution_status":"test"}',%s) RETURNING object_id""", (actor,)).fetchone()['object_id']
        rows = history.list_history(c, oid)['items']
        initial = next(r for r in rows if r['entity_table'] == 'knowledge_object')
        assert initial['change_id'] and initial['before_value'] is None
        command = service.SubmissionInput(context_object_id=oid,source_label='history test',reason='first revision',
           proposals=[service.ProposalInput(target_kind='object',target_id=oid,field_path='description',proposed_value='reviewed',base_version=1)])
        s = service.submit(c,command,actor,'history-test')
        assert c.execute('SELECT description FROM smartlib.knowledge_object WHERE object_id=%s',(oid,)).fetchone()['description'] is None
        service.decide(c,s['submission_id'],service.DecisionInput(decision='accept',reason='verified'),actor,'history-test')
        r = history.restore(c,oid,history.RestoreInput(revision_id=initial['revision_id'],field_path='description',base_version=2,reason='Restore original description'),actor,'history-test')
        assert r['status']=='needs_review'
        assert c.execute('SELECT description FROM smartlib.knowledge_object WHERE object_id=%s',(oid,)).fetchone()['description']=='reviewed'
        service.decide(c,r['submission_id'],service.DecisionInput(decision='accept',reason='reviewed restoration'),actor,'history-test')
        current=c.execute('SELECT description,version FROM smartlib.knowledge_object WHERE object_id=%s',(oid,)).fetchone()
        assert current == {'description': None,'version': 3}
        rows=history.list_history(c,oid)['items']
        object_rows=[r for r in rows if r['entity_table']=='knowledge_object']
        assert len(object_rows)==3 and object_rows[0]['submission_id']
        assert len({r['change_id'] for r in rows})==1
        try:
            history.restore(c,oid,history.RestoreInput(revision_id=initial['revision_id'],field_path='description',base_version=1,reason='stale'),actor,'test')
        except ValueError:
            pass
        else:
            raise AssertionError('Stale restore accepted')
        with c.transaction():
            c.execute("SELECT set_config('smartlib.actor_id',%s,true)",(str(uuid4()),))
            try:
                with c.transaction():
                    history.list_history(c,oid)
            except psycopg.errors.InsufficientPrivilege:
                pass
            else:
                raise AssertionError('Unauthorized history disclosure')
        print('PASS: snapshot capture, shared change ID, reviewed restoration, version 1→2→3, stale conflict, permission isolation')
    finally:
        c.rollback()
        print('All fixture rows and audit/history changes rolled back')
