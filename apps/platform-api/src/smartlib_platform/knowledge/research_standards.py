"""Versioned, source-preserving import of user-verified MOE standard packages."""
import hashlib
import json
from uuid import UUID, uuid5
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from .research_workbench import evidence, stamp

class Term(BaseModel):
    code: str=Field(min_length=1,max_length=40,pattern=r'^[A-Za-z0-9._-]+$')
    name: str=Field(min_length=2,max_length=200)
    parent_code: str | None=None
    source_locator: dict=Field(default_factory=dict)

class StandardPackage(BaseModel):
    version: str=Field(min_length=4,max_length=60)
    source_url: str=Field(max_length=1500)
    verified_against_official: bool
    terms: list[Term]=Field(min_length=1,max_length=5000)
    source_files: list[dict]=Field(default_factory=list)

def validate_package(p):
    host=urlsplit(p.source_url).hostname or ''
    if not p.verified_against_official or not (host=='moe.gov.cn' or host.endswith('.moe.gov.cn')):
        raise ValueError('必须提供教育部官方来源URL，并确认已按官方文件核对；系统不会把未经核实资料标成权威标准')
    terms={x.code:x for x in p.terms}
    if len(terms)!=len(p.terms):raise ValueError('重复代码，停止导入')
    # Official academic/professional degrees and their parent categories can share
    # names. Identity is (scheme, version, code), never the display name.
    for t in p.terms:
        seen={t.code};parent=t.parent_code
        while parent:
            if parent not in terms:raise ValueError('缺少上级代码：'+parent)
            if parent in seen:raise ValueError('层级存在循环')
            seen.add(parent);parent=terms[parent].parent_code

def import_package(c,p,payload,store,actor):
    validate_package(p);stamp(c,actor,'导入已核对的教育部目录新版本，旧版本不覆盖')
    scheme='MOE_GRADUATE_DISCIPLINE';digest=hashlib.sha256(payload).hexdigest()
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(scheme+':'+p.version,))
    existing=c.execute("SELECT attributes->>'source_checksum' checksum FROM smartlib.knowledge_object WHERE attributes->>'scheme'=%s AND attributes->>'scheme_version'=%s",(scheme,p.version)).fetchall()
    if existing:
        if {r['checksum'] for r in existing}!={digest}:raise ValueError('同版本内容不同，不允许覆盖，请使用新版本号')
        return {'imported':0,'replay':True,'version':p.version}
    key=f'research-standards/moe/{digest}/source.json';saved=store.put_bytes(key,payload,'application/json')
    if hashlib.sha256(store.get_bytes(key)).hexdigest()!=digest:raise ValueError('来源归档校验失败')
    uri='s3://smartlib-reference-data/'+key
    ns=UUID('ccad4960-b651-48b1-9fc1-bc00f0631fb4')
    ids={t.code:uuid5(ns,p.version+':'+t.code) for t in p.terms}
    eids={}
    for t in p.terms:
        attrs={'standard_library':'research-classification','scheme':scheme,'scheme_version':p.version,'scheme_code':t.code,
          'node_type':'category','parent_code':t.parent_code or '', 'source_url':p.source_url,'source_checksum':digest,
          'source_authority':'教育部（由提交者核对官方文件）','official':True,'dataset_id':'research-classification-standards','dataset_version':p.version}
        c.execute("""INSERT INTO smartlib.knowledge_object(object_id,object_type,canonical_name,visibility,quality_state,review_state,attributes,created_by)
          VALUES(%s,'discipline',%s,'campus','validated','approved',%s,%s)""",(ids[t.code],t.name,Jsonb(attrs),actor))
        eids[t.code]=evidence(c,ids[t.code],actor,p.source_url,'教育部目录标准词条：'+t.name,{'archive':uri,'sha256':digest,'version_id':saved.version_id,'term':t.model_dump(),'source_files':p.source_files,'verification':'official_document_checked_by_submitter'})
    for t in p.terms:
        if t.parent_code:
            rid=uuid5(ns,p.version+':parent:'+t.code)
            c.execute("""INSERT INTO smartlib.relation_assertion(relation_id,subject_id,predicate,object_id,fact_class,visibility,review_state,attributes,created_by)
              VALUES(%s,%s,'taxonomy.broader',%s,'literature_fact','campus','approved',%s,%s)""",(rid,ids[t.code],ids[t.parent_code],Jsonb({'dataset_id':'research-classification-standards','dataset_version':p.version,'scheme':scheme}),actor))
            c.execute('INSERT INTO smartlib.relation_evidence(relation_id,evidence_id) VALUES(%s,%s)',(rid,eids[t.code]))
    return {'imported':len(ids),'version':p.version,'archive':uri,'sha256':digest}
