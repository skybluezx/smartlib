"""Confirm the user's C195 decision, preserving earlier profile snapshots."""
import argparse
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid5
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from smartlib_platform.knowledge.research_profiles import BATCHES, load_profiles
from smartlib_platform.storage.s3 import S3ObjectStore

BATCH='c195-h19-user-confirmation-20260909-v1'
ACTOR=UUID('00000000-0000-4000-8000-000000000001')
PAPER='c1d432a4-e692-5f3d-8105-e1b28b714738'
RID=UUID('0d5593f6-ab76-59c0-a44b-3bfe8f704abb')
def uid(s): return uuid5(RID,BATCH+':'+s)

def run(apply, output):
    reason='用户明确确认：以“老年护理，归入 H19 老年医学”作为主方向；不增加G04或H28。'
    with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=not apply):
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(BATCH,))
            for key,value in [('actor_id',str(ACTOR)),('trace_id',BATCH),('change_source','explicit-user-classification-confirmation'),('change_reason',reason)]:
                conn.execute('SELECT set_config(%s,%s,true)',('smartlib.'+key,value))
            old=conn.execute('SELECT metadata FROM smartlib.source_system WHERE source_system_id=%s',(uid('system'),)).fetchone()
            if old:return {'applied':False,'replay':True,**old['metadata']}
            before=conn.execute('SELECT to_jsonb(r) data FROM smartlib.relation_assertion r WHERE relation_id=%s FOR UPDATE',(RID,)).fetchone()['data']
            assert before['subject_id']==PAPER and before['review_state']=='pending'
            assert before['attributes']['code']=='H19' and before['attributes']['classification_role']=='primary'
            original=load_profiles(conn)
            checksum="SELECT md5(string_agg(md5(to_jsonb(k)::text),'' ORDER BY object_id)) value FROM smartlib.knowledge_object k"
            object_hash=conn.execute(checksum).fetchone()['value']
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            attrs={**before['attributes'],'reviewed_by':str(ACTOR),'reviewed_at':timestamp,'review_note':reason}
            version=conn.execute("UPDATE smartlib.relation_assertion SET review_state='approved',attributes=%s WHERE relation_id=%s RETURNING version",(Jsonb(attrs),RID)).fetchone()['version']
            # Add human decision evidence separately from the derived profile, avoiding circular support.
            decision={'paper':PAPER,'relation_id':str(RID),'decision':reason,'actor_id':str(ACTOR),'timestamp':timestamp,'before':before}
            conn.execute("INSERT INTO smartlib.source_system(source_system_id,code,name,owner_department,source_type,authorization_state,metadata) VALUES(%s,%s,'C195人工确认与画像更新','科研数据治理','repository','approved','{}')",(uid('system'),BATCH))
            ref,eid=uid('decision-ref'),uid('decision-evidence')
            decision_hash=hashlib.sha256(json.dumps(decision,sort_keys=True).encode()).hexdigest()
            conn.execute("INSERT INTO smartlib.source_reference(source_reference_id,object_id,source_system_id,external_id,source_version,payload_checksum,metadata) VALUES(%s,%s,%s,'C195-decision',%s,%s,%s)", (ref,UUID(PAPER),uid('system'),BATCH,decision_hash,Jsonb(decision)))
            conn.execute("""INSERT INTO smartlib.evidence_record(evidence_id,object_id,source_reference_id,evidence_type,citation,excerpt,visibility,license_tags,content_checksum,metadata,created_by)
                VALUES(%s,%s,%s,'business_record','当前会话用户明确确认',%s,'campus',ARRAY['internal-reference-use'],%s,%s,%s)""",(eid,UUID(PAPER),ref,reason,decision_hash,Jsonb(decision),ACTOR))
            conn.execute('INSERT INTO smartlib.relation_evidence(relation_id,evidence_id) VALUES(%s,%s)',(RID,eid))
            profiles=load_profiles(conn)
            changed={k:v for k,v in profiles.items() if v!=original.get(k)}
            assert changed and PAPER in changed
            assert all(PAPER in {p['publication_id'] for p in v['papers']} for v in changed.values())
            rows=[r for r in profiles[PAPER]['rows'] if r['scheme']=='NSFC_APPLICATION_CODE']
            assert len(rows)==1 and rows[0]['code']=='H19' and rows[0]['primary_paper_count']==1
            coverage=sum(p['coverage']['NSFC_APPLICATION_CODE'] for p in profiles.values() if p['object_type']=='publication')
            assert coverage==269
            assert conn.execute(checksum).fetchone()['value']==object_hash
            pending=conn.execute("SELECT count(*) n FROM smartlib.relation_assertion WHERE attributes->>'source_import_batch'=ANY(%s) AND review_state='pending' AND system_to='infinity'",(BATCHES,)).fetchone()['n']
            assert pending==0
            payload=json.dumps({'batch':BATCH,'decision':decision,'profiles':changed},ensure_ascii=False,sort_keys=True).encode()
            digest=hashlib.sha256(payload).hexdigest();key=f'research-profiles/{BATCH}/{digest}/profiles.json'
            archive={'uri':'s3://smartlib-reference-data/'+key,'sha256':digest}
            if apply:
                store=S3ObjectStore(os.environ['SMARTLIB_S3_ENDPOINT_URL'],'smartlib-reference-data',os.environ['SMARTLIB_S3_ACCESS_KEY'],os.environ['SMARTLIB_S3_SECRET_KEY'],os.environ.get('SMARTLIB_S3_REGION','us-east-1'))
                archive['version_id']=store.put_bytes(key,payload,'application/json').version_id
                assert hashlib.sha256(store.get_bytes(key)).hexdigest()==digest
            for oid,p in changed.items():
                ref=uid('profile-ref:'+oid)
                conn.execute("""INSERT INTO smartlib.source_reference(source_reference_id,object_id,source_system_id,external_id,source_version,payload_checksum,raw_object_uri,metadata)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",(ref,UUID(oid),uid('system'),oid,BATCH,digest,archive['uri'],Jsonb({'json_pointer':'/profiles/'+oid,**archive})))
                conn.execute("""INSERT INTO smartlib.evidence_record(evidence_id,object_id,source_reference_id,evidence_type,citation,excerpt,visibility,license_tags,content_checksum,metadata,created_by)
                    VALUES(%s,%s,%s,'business_record',%s,%s,'campus',ARRAY['internal-reference-use'],%s,%s,%s)""",(uid('profile-evidence:'+oid),UUID(oid),ref,archive['uri'],reason,digest,Jsonb({'record_kind':'derived_research_profile','profile':p,'archive':archive}),ACTOR))
            conn.execute("""INSERT INTO smartlib.outbox_event(event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
                VALUES(%s,'relation_assertion',%s,'knowledge.relation.updated',%s,%s,%s)""",(uid('outbox'),RID,version,Jsonb({'relation_id':str(RID),'version':version}),BATCH))
            receipt={'batch':BATCH,'approved':1,'pending':pending,'nsfc_papers':coverage,'updated_profiles':dict(collections.Counter(p['object_type'] for p in changed.values())),'archive':archive,'knowledge_objects_checksum':object_hash}
            conn.execute('UPDATE smartlib.source_system SET metadata=%s WHERE source_system_id=%s',(Jsonb(receipt),uid('system')))
            output.mkdir(parents=True,exist_ok=True);(output/'profiles.json').write_bytes(payload)
            return {'applied':apply,**receipt}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=run(a.apply,a.output);a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
