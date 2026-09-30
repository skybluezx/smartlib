"""Apply accepted audit deltas only; default rolls back, deterministic/idempotent."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from smartlib_platform.storage.s3 import S3ObjectStore

NS = UUID('9169d229-af08-414a-94c9-b12cb9da8cb4')
ACTOR = UUID('00000000-0000-4000-8000-000000000001')
BATCH = 'paper-classification-audit-269-20260909-v2'


def uid(s):
    return uuid5(NS, s)


def run(root, apply):
    payload = (root / 'audit_results.json').read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    data = json.loads(payload)
    papers = data['papers']
    assert len(papers) == 269
    targets = [p for p in papers if p['status'] == '建议调整']
    assert len(targets) == 112
    archive = {'uri': f's3://smartlib-reference-data/paper-classifications/{BATCH}/{digest}/audit_results.json', 'sha256': digest}
    with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'], row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=not apply):
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (BATCH,))
            for k,v in [('actor_id',str(ACTOR)),('trace_id',BATCH),('change_source','user-authorized-classification-audit'),('change_reason','用户执行112篇明确审核建议；C195待确认不动；保留来源和历史；不批量批准')]:
                conn.execute('SELECT set_config(%s,%s,true)', ('smartlib.'+k,v))
            checksum = "SELECT md5(string_agg(md5(to_jsonb(k)::text),'' ORDER BY object_id)) value FROM smartlib.knowledge_object k"
            before = conn.execute(checksum).fetchone()['value']
            old = {str(r['relation_id']):r for r in conn.execute("SELECT relation_id,attributes,review_state,to_jsonb(r) snapshot FROM smartlib.relation_assertion r WHERE attributes->>'source_import_batch'='paper-classification-269-20260909-v1' FOR UPDATE")}
            assert len(old) == 2898
            standards = {(r['attributes']['scheme'],r['attributes']['scheme_code']):r for r in conn.execute("SELECT object_id,attributes FROM smartlib.knowledge_object WHERE attributes->>'standard_library'='research-classification' AND system_to='infinity'")}
            baseline = json.loads((root / 'live_readback.json').read_text())
            baseline = {r['id']:r for r in baseline}
            already = conn.execute("SELECT metadata FROM smartlib.source_system WHERE source_system_id=%s", (uid('source-system'),)).fetchone()
            if already:
                assert already['metadata']['sha256'] == digest, 'Applied audit has changed'
            else:
                for rid,r in old.items():
                    assert r['attributes'] == baseline[rid]['attributes'] and r['review_state'] == 'pending', 'Baseline changed; stop'
            for p in papers:
                current = conn.execute('SELECT publication_id::text,content_checksum FROM smartlib.publication_fulltext_resource WHERE fulltext_resource_id=%s', (UUID(p['fulltext_resource_id']),)).fetchone()
                assert current == {'publication_id':p['publication_id'], 'content_checksum':p['pdf_sha256']}
            if apply:
                store = S3ObjectStore(os.environ['SMARTLIB_S3_ENDPOINT_URL'],'smartlib-reference-data',os.environ['SMARTLIB_S3_ACCESS_KEY'],os.environ['SMARTLIB_S3_SECRET_KEY'],os.environ.get('SMARTLIB_S3_REGION','us-east-1'))
                key = archive['uri'].split('smartlib-reference-data/',1)[1]
                saved = store.put_bytes(key,payload,'application/json') if not already else None
                assert hashlib.sha256(store.get_bytes(key)).hexdigest() == digest
                if saved: archive['version_id'] = saved.version_id
            conn.execute("""INSERT INTO smartlib.source_system(source_system_id,code,name,owner_department,source_type,authorization_state,metadata)
                VALUES(%s,%s,'269篇论文分类内容审核第二版','科研数据治理','repository','approved',%s) ON CONFLICT DO NOTHING""",
                (uid('source-system'),BATCH,Jsonb({'sha256':digest,'deferred':['C195'],'scope':'112篇明确建议；原关系保持可追溯'})))
            counts = collections.Counter()
            changed = []
            expected = {}
            for p in targets:
                publication = UUID(p['publication_id'])
                ref,eid = uid('ref:'+str(publication)),uid('evidence:'+str(publication))
                reason = p['audit']['note']
                conn.execute("""INSERT INTO smartlib.source_reference(source_reference_id,object_id,source_system_id,external_id,source_version,payload_checksum,raw_object_uri,metadata)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (ref,publication,uid('source-system'),f"C{p['n']:03d}",BATCH,digest,archive['uri'],Jsonb(archive)))
                conn.execute("""INSERT INTO smartlib.evidence_record(evidence_id,object_id,source_reference_id,evidence_type,citation,excerpt,visibility,license_tags,content_checksum,metadata,created_by)
                    VALUES(%s,%s,%s,'business_record',%s,%s,'campus',ARRAY['internal-reference-use'],%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (eid,publication,ref,p['fulltext_url'],reason,digest,Jsonb({'audit':p['audit'],'abstract':p['abstract'],'keywords':p['keywords_candidates'],'source_scope':p['abstract_source'],'pdf_sha256':p['pdf_sha256'],'followup_evidence':p['followup_evidence'],'archive':archive,'user_instruction':'执行你的审核建议','review_kind':'AI建议经用户授权实施，非逐篇人工标引'}),ACTOR))
                desired = {('NSFC_APPLICATION_CODE',p['proposed_primary']):'primary'}
                desired.update({('NSFC_APPLICATION_CODE',c):'secondary' for c in p['proposed_secondary']})
                existing = {(r['scheme'],r['code']):r for r in p['classifications']}
                for r in p['classifications']:
                    action = None
                    if r['scheme'] == 'NSFC_APPLICATION_CODE':
                        if (r['scheme'],r['code']) not in desired: action = ('superseded',None)
                        elif desired[r['scheme'],r['code']] != r['role']: action = ('pending',desired[r['scheme'],r['code']])
                    elif r['scheme'] == 'MESH' and r['name'] in p['audit'].get('mesh_remove',[]):
                        assert r['source'] == 'algorithmic_inference'
                        action = ('superseded',None)
                    elif r['scheme'] == 'MESH' and r['name'] in p['audit'].get('external_scope_flag',[]):
                        action = ('rejected',None)
                    if action:
                        state,role = action
                        attributes = baseline[r['id']]['attributes'].copy()
                        attributes['review_note'] = reason + '；执行批次：'+BATCH
                        if role: attributes['classification_role'] = role
                        row = conn.execute('SELECT attributes,review_state FROM smartlib.relation_assertion WHERE relation_id=%s',(UUID(r['id']),)).fetchone()
                        if row['attributes'] != attributes or row['review_state'] != state:
                            assert not already, 'Idempotency mismatch'
                            conn.execute('UPDATE smartlib.relation_assertion SET attributes=%s,review_state=%s WHERE relation_id=%s',(Jsonb(attributes),state,UUID(r['id'])))
                            counts['updated_'+state] += 1
                        expected[r['id']] = (attributes,state)
                        changed.append(r['id'])
                        conn.execute('INSERT INTO smartlib.relation_evidence(relation_id,evidence_id) VALUES(%s,%s) ON CONFLICT DO NOTHING',(UUID(r['id']),eid))
                additions = [(scheme,code,role) for (scheme,code),role in desired.items() if (scheme,code) not in existing]
                additions += [('MESH',t['code'],'topic') for t in p['mesh_add_resolved']]
                for scheme,code,role in additions:
                    standard = standards[scheme,code]
                    rid = uid(f'{publication}:{scheme}:{code}')
                    attributes = {'scheme':scheme,'scheme_version':standard['attributes']['scheme_version'],'code':code,'classification_role':role,
                                  'source_kind':'algorithmic_inference','method_version':BATCH,'source_import_batch':BATCH,
                                  'evidence_excerpt':reason,'fulltext_resource_id':p['fulltext_resource_id'],'fulltext_checksum':p['pdf_sha256'],
                                  'review_note':'用户授权执行AI审核建议；未作逐篇人工标引确认','content_basis':p['abstract_source'],
                                  'score_interpretation':'未给校准概率；confidence留空'}
                    predicate = 'publication.has_research_topic' if scheme == 'MESH' else 'publication.classified_as_discipline'
                    row = conn.execute('SELECT attributes,review_state FROM smartlib.relation_assertion WHERE relation_id=%s',(rid,)).fetchone()
                    if not row:
                        conn.execute("""INSERT INTO smartlib.relation_assertion(relation_id,subject_id,predicate,object_id,fact_class,confidence,visibility,license_tags,review_state,model_version,attributes,created_by)
                            VALUES(%s,%s,%s,%s,'algorithmic_inference',NULL,'campus',ARRAY['internal-reference-use'],'pending',%s,%s,%s)""",
                            (rid,publication,predicate,standard['object_id'],BATCH,Jsonb(attributes),ACTOR))
                        counts['inserted_'+scheme] += 1
                    else: assert row['attributes']==attributes and row['review_state']=='pending'
                    expected[str(rid)] = (attributes,'pending')
                    changed.append(str(rid))
                    conn.execute('INSERT INTO smartlib.relation_evidence(relation_id,evidence_id) VALUES(%s,%s) ON CONFLICT DO NOTHING',(rid,eid))
            # Read-back every touched row, source link, and actual active classification set.
            for rid,(attributes,state) in expected.items():
                row = conn.execute('SELECT attributes,review_state,version FROM smartlib.relation_assertion WHERE relation_id=%s',(UUID(rid),)).fetchone()
                assert row['attributes']==attributes and row['review_state']==state
                assert conn.execute('SELECT count(*) n FROM smartlib.relation_evidence WHERE relation_id=%s',(UUID(rid),)).fetchone()['n']
                conn.execute("""INSERT INTO smartlib.outbox_event(event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
                    VALUES(%s,'relation_assertion',%s,'knowledge.relation.updated',%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (uid('outbox:'+rid),UUID(rid),row['version'],Jsonb({'relation_id':rid,'version':row['version']}),BATCH))
            for p in papers:
                active = conn.execute("SELECT attributes,review_state FROM smartlib.relation_assertion WHERE subject_id=%s AND attributes->>'scheme'='NSFC_APPLICATION_CODE' AND system_to='infinity' AND smartlib.analysis_state_eligible(review_state)",(UUID(p['publication_id']),)).fetchall()
                actual = {(r['attributes']['code'],r['attributes']['classification_role']) for r in active}
                wanted = {(r['code'],r['role']) for r in p['classifications'] if r['scheme']=='NSFC_APPLICATION_CODE'}
                if p['status']=='建议调整': wanted = {(p['proposed_primary'],'primary')} | {(s,'secondary') for s in p['proposed_secondary']}
                assert actual == wanted, (p['n'],actual,wanted)
                active_mesh=conn.execute("SELECT attributes FROM smartlib.relation_assertion WHERE subject_id=%s AND attributes->>'scheme'='MESH' AND system_to='infinity' AND smartlib.analysis_state_eligible(review_state)",(UUID(p['publication_id']),)).fetchall()
                wanted_mesh={r['code'] for r in p['classifications'] if r['scheme']=='MESH'}
                if p['status']=='建议调整':
                    removed=set(p['audit'].get('mesh_remove',[])+p['audit'].get('external_scope_flag',[]))
                    wanted_mesh-={r['code'] for r in p['classifications'] if r['scheme']=='MESH' and r['name'] in removed}
                    wanted_mesh|={r['code'] for r in p['mesh_add_resolved']}
                assert {r['attributes']['code'] for r in active_mesh}==wanted_mesh, ('MeSH',p['n'])
                assert len(active_mesh)==len(wanted_mesh), ('duplicate MeSH',p['n'])
            # All baseline records outside the exact mutation manifest remain byte-for-byte unchanged.
            for rid,r in old.items():
                if rid not in expected:
                    row=conn.execute('SELECT to_jsonb(r) value FROM smartlib.relation_assertion r WHERE relation_id=%s',(UUID(rid),)).fetchone()['value']
                    assert row == r['snapshot']
                    assert row['attributes']==baseline[rid]['attributes'] and row['review_state']=='pending'
            after=conn.execute(checksum).fetchone()['value']; assert before==after
            result={'applied':apply,'batch':BATCH,'changed_papers':len(targets),'deferred':['C195'],'mutations_this_run':dict(counts),'manifest_relations':len(expected),
                    'objects_unchanged':True,'object_checksum':after,'all_269_nsfc_sets_verified':True,'all_269_mesh_sets_verified':True,'evidence_links_verified':True,'history_verification':'requires_admin_readback',
                    'relation_manifest':sorted(expected),
                    'archive':archive,'new_relations_review_state':'pending','formal_profiles_generated':False,'idempotent_replay':bool(already)}
        receipts=Path('/tmp/classification_audit_apply_receipts');receipts.mkdir(exist_ok=True)
        receipts.joinpath('apply_receipt.json' if apply else 'apply_dryrun.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='relation_manifest'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();run(args.root,args.apply)
