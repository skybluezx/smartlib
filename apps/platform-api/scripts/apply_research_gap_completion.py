"""Archive primary sources and add checked workflow evidence; preserve all labels."""
import argparse, hashlib, json, os
from pathlib import Path
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from smartlib_platform.storage.s3 import S3ObjectStore
from smartlib_platform.knowledge.research_standards import StandardPackage,import_package
from smartlib_platform.knowledge.research_workbench import evidence,stamp,content

ACTOR=UUID('00000000-0000-4000-8000-000000000001')
BATCH='research-gap-completion-20260909-v1'
def run(root,apply):
    rows=json.loads((root/'abstracts_and_exceptions.json').read_text());assert len(rows)==86
    store=S3ObjectStore(os.environ['SMARTLIB_S3_ENDPOINT_URL'],'smartlib-reference-data',os.environ['SMARTLIB_S3_ACCESS_KEY'],os.environ['SMARTLIB_S3_SECRET_KEY'],os.environ.get('SMARTLIB_S3_REGION','us-east-1'))
    archives={}
    prior=json.loads((root/'apply_receipt.json').read_text()).get('archives',{}) if (root/'apply_receipt.json').exists() else {}
    def archive(path,mime):
        data=path.read_bytes();sha=hashlib.sha256(data).hexdigest();key=f'research-gap-completion/{sha}/{path.name}'
        if apply and path.name in prior:
            item=prior[path.name];assert item['sha256']==sha
            assert hashlib.sha256(store.get_bytes(key)).hexdigest()==sha
            archives[path.name]=item;return item
        if apply:
            saved=store.put_bytes(key,data,mime)
            assert hashlib.sha256(store.get_bytes(key)).hexdigest()==sha
            version=saved.version_id
        else:version='dry-run'
        item={'uri':'s3://smartlib-reference-data/'+key,'sha256':sha,'version_id':version,'filename':path.name}
        archives[path.name]=item;return item
    archive(root/'abstracts_and_exceptions.json','application/json')
    pdf=archive(root/'教育部研究生目录2022原件.pdf','application/pdf')
    pdf['url']='https://www.moe.gov.cn/srcsite/A22/moe_833/202209/W020220914572994461110.pdf'
    notice=archive(root/'教育部目录发布通知.html','text/html')
    for p in (root/'sources').iterdir():archive(p,'application/xml')
    package=json.loads((root/'moe_package.json').read_text());package['source_files']=[pdf,notice]
    payload=json.dumps(package,ensure_ascii=False,sort_keys=True).encode()
    class DryStore:
        def put_bytes(self,key,data,mime):self.data=data;return type('Saved',(),{'version_id':'dry-run'})()
        def get_bytes(self,key):return self.data
    with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],row_factory=dict_row) as c:
        with c.transaction(force_rollback=not apply):
            stamp(c,ACTOR,'用户要求补齐教育部目录与86篇摘要；不修改已确认分类或论文原字段')
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(BATCH,))
            frozen=c.execute("SELECT object_id FROM smartlib.knowledge_object").fetchall();ids=[r['object_id'] for r in frozen]
            queries={
                'existing_objects':("SELECT md5(string_agg(to_jsonb(k)::text,'' ORDER BY object_id)) value FROM smartlib.knowledge_object k WHERE object_id=ANY(%s)",(ids,)),
                'publication_metadata':("SELECT md5(string_agg(to_jsonb(p)::text,'' ORDER BY publication_id)) value FROM smartlib.publication_metadata p",()),
                'classifications':("SELECT md5(string_agg(to_jsonb(r)::text,'' ORDER BY relation_id)) value FROM smartlib.relation_assertion r WHERE attributes->>'scheme' IN ('NSFC_APPLICATION_CODE','MESH','INCITES_WOS','MOE_GRADUATE_DISCIPLINE') AND predicate<>'taxonomy.broader'",())}
            before={k:c.execute(q,p).fetchone()['value'] for k,(q,p) in queries.items()}
            moe=import_package(c,StandardPackage.model_validate(package),payload,store if apply else DryStore(),ACTOR)
            inserted=0;checks=[]
            for r in rows:
                existing=c.execute("SELECT metadata FROM smartlib.evidence_record WHERE object_id=%s AND metadata->>'completion_batch'=%s",(r['publication_id'],BATCH)).fetchone()
                if existing:
                    assert existing['metadata']['abstract']==r['abstract'] and existing['metadata']['body_excerpt']==r['body_excerpt']
                else:
                    ft=c.execute('SELECT content_checksum FROM smartlib.publication_fulltext_resource WHERE fulltext_resource_id=%s AND publication_id=%s',(r['fulltext_resource_id'],r['publication_id'])).fetchone()
                    assert ft and ft['content_checksum']==r['content_checksum'],r['n']
                    metadata={k:v for k,v in r.items() if k not in ('pdf_path','source_file')}
                    metadata.update(completion_batch=BATCH,archive=archives['abstracts_and_exceptions.json'])
                    if r.get('source_file'):metadata['original_source_archive']=archives[r['source_sha256']+Path(r['source_file']).suffix]
                    else:metadata['original_source_archive']={'uri':r['storage_uri'],'sha256':r['content_checksum']}
                    if r['n']==165:metadata['pubmed_absence_check']=archives['pubmed-40967537-no-abstract.xml']
                    evidence(c,UUID(r['publication_id']),ACTOR,r['source_url'],r['abstract'] or r['body_excerpt'],metadata);inserted+=1
                ctx=content(c,UUID(r['publication_id']))
                assert ctx['has_abstract']==bool(r['abstract']),r['n']
                assert ctx.get('has_body_evidence')==bool(r['body_excerpt']),r['n']
                checks.append({'n':r['n'],'id':r['publication_id'],'has_abstract':ctx['has_abstract'],'has_body_evidence':ctx.get('has_body_evidence'),'basis':ctx['basis']})
            after={k:c.execute(q,p).fetchone()['value'] for k,(q,p) in queries.items()};assert before==after,(before,after)
            result={'applied':apply,'moe':moe,'evidence_inserted':inserted,'unchanged_checks':before,'papers':checks,'archives':archives}
    (root/('apply_receipt.json' if apply else 'dry_run_receipt.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ('papers','archives')},ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args();run(a.root,a.apply)
