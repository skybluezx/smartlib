"""Research phase 2: evidence-led suggestions, approval and descriptive analysis."""
import hashlib
import itertools
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from typing import Literal
from .research_profiles import load_profiles

SCHEMES={'NSFC_APPLICATION_CODE','MESH','MOE_GRADUATE_DISCIPLINE'}
METHOD='research-workbench-v1'

class Label(BaseModel):
    standard_id: UUID
    role: Literal['primary','secondary','topic']='secondary'

class Proposal(BaseModel):
    object_id: UUID
    kind: Literal['classification','project']='classification'
    labels: list[Label]=Field(default_factory=list,max_length=40)
    source: str=Field(min_length=2,max_length=1000)
    evidence: str=Field(min_length=10,max_length=20000)
    summary: str=Field(default='',max_length=20000)
    expected_object_version: int=Field(ge=1)

class BatchDecision(BaseModel):
    task_ids: list[UUID]=Field(min_length=1,max_length=100)
    action: Literal['approve','reject']
    reason: str=Field(min_length=2,max_length=2000)
    expected_updated_at: dict[str,str]=Field(default_factory=dict)

class Generate(BaseModel):
    publication_ids: list[UUID]=Field(default_factory=list,max_length=300)

def stamp(c,actor,reason):
    for k,v in [('actor_id',str(actor)),('change_source',METHOD),('change_reason',reason)]:
        c.execute('SELECT set_config(%s,%s,true)',('smartlib.'+k,v))

def objects(c,kind):
    return c.execute("SELECT object_id::text id,canonical_name name,version,attributes FROM smartlib.knowledge_object WHERE object_type=%s AND system_to='infinity' AND review_state NOT IN ('rejected','superseded') ORDER BY canonical_name",(kind,)).fetchall()

def standards(c,scheme=None,query='',version=None,parent=None):
    if scheme and scheme not in SCHEMES: raise ValueError('不支持的分类体系')
    return c.execute("""SELECT object_id::text id,canonical_name name,attributes->>'scheme' scheme,
        attributes->>'scheme_code' code,attributes->>'scheme_version' version,attributes->>'parent_code' parent_code
        FROM smartlib.knowledge_object WHERE attributes->>'standard_library'='research-classification'
        AND system_to='infinity' AND review_state='approved' AND attributes->>'node_type' NOT IN ('root','qualifier')
        AND (%s::text IS NULL OR attributes->>'scheme'=%s)
        AND (%s::text IS NULL OR attributes->>'scheme_version'=%s)
        AND (canonical_name ILIKE %s OR attributes->>'scheme_code' ILIKE %s)
        AND (%s::text IS NULL OR attributes->>'scheme_code' LIKE %s)
        ORDER BY attributes->>'scheme_code',canonical_name LIMIT 100""",
        (scheme,scheme,version,version,'%'+query+'%','%'+query+'%',parent,(parent or '')+'%')).fetchall()

def content(c,pid):
    row=c.execute("SELECT p.title,p.abstract,k.version FROM smartlib.publication_metadata p JOIN smartlib.knowledge_object k ON k.object_id=p.publication_id WHERE p.publication_id=%s AND k.system_to='infinity'",(pid,)).fetchone()
    if not row:raise LookupError('论文不可读取')
    abstract=row['abstract'] or '';basis='题名与结构化摘要' if abstract else '仅题名'
    evidence_id=None
    verified=c.execute("""SELECT evidence_id::text,metadata FROM smartlib.evidence_record
        WHERE object_id=%s AND metadata->>'verification'='primary_source_boundary_checked'
        AND (length(metadata->>'abstract')>30 OR length(metadata->>'body_excerpt')>30)
        ORDER BY created_at DESC LIMIT 1""",(pid,)).fetchone()
    if not abstract and verified:
        meta=verified['metadata'];abstract=meta.get('abstract') or ''
        body=meta.get('body_excerpt') or ''
        basis='题名与已核对的原始摘要' if abstract else '原文未提供常规摘要；使用已核对正文摘录（不是摘要）'
        text=row['title']+'\n'+(abstract or body)
        return {'text':text,'basis':basis,'evidence_id':verified['evidence_id'],'version':row['version'],
                'checksum':hashlib.sha256(text.encode()).hexdigest(),'has_abstract':bool(abstract),
                'has_body_evidence':bool(body),'source_kind':meta.get('source_kind'),
                'abstract_absence_reason':meta.get('abstract_absence_reason')}
    if not abstract:
        evidence=c.execute("""SELECT evidence_id::text,metadata->>'abstract' abstract FROM smartlib.evidence_record
            WHERE object_id=%s AND length(metadata->>'abstract')>30 ORDER BY created_at DESC LIMIT 1""",(pid,)).fetchone()
        if evidence:
            abstract=re.split(r'\n\s*INTRODUCTION\b',evidence['abstract'],flags=re.I)[0][:12000]
            basis='题名与前期审核证据中的摘要候选（需复核）';evidence_id=evidence['evidence_id']
    if not abstract:
        opening=c.execute("SELECT evidence_id::text,metadata->>'pdf_opening_text' text FROM smartlib.evidence_record WHERE object_id=%s AND length(metadata->>'pdf_opening_text')>100 ORDER BY created_at DESC LIMIT 1",(pid,)).fetchone()
        if opening:
            parts=re.split(r'\bABSTRACT\b',opening['text'],maxsplit=1,flags=re.I)
            if len(parts)==2:
                abstract=re.split(r'\bINTRODUCTION\b',parts[1],maxsplit=1,flags=re.I)[0][:12000]
                basis='题名与PDF开篇证据中的摘要候选（需复核）';evidence_id=opening['evidence_id']
    text=row['title']+'\n'+abstract
    return {'text':text,'basis':basis,'evidence_id':evidence_id,'version':row['version'],
            'checksum':hashlib.sha256(text.encode()).hexdigest(),'has_abstract':bool(abstract)}

@lru_cache(maxsize=250000)
def normalized_phrase(phrase):
    return re.sub(r'[^\w]+',' ',phrase.casefold()).strip()

def exact_candidates(text, terms):
    """Mentions are suggestions, never automatically approved semantic classifications."""
    normalized=' '+re.sub(r'[^\w]+',' ',text.casefold())+' '
    words=set(normalized.split())
    matches=[]
    for t in terms:
        a=t['attributes'];phrases=[t['name'],*a.get('aliases',[])]
        for phrase in phrases:
            if not isinstance(phrase,str):continue
            clean=normalized_phrase(phrase)
            if len(clean)<7 or clean.split()[0] not in words:continue
            if (' '+clean+' ') in normalized:
                matches.append({'standard_id':t['id'],'name':t['name'],'code':a['scheme_code'],
                    'scheme':a['scheme'],'version':a['scheme_version'],'role':'topic' if a['scheme']=='MESH' else 'secondary',
                    'matched_phrase':phrase,'note':'词面命中；需判断是否为核心研究内容，不能据此直接确认'})
                break
    return sorted(matches,key=lambda m:(m['scheme'],m['code']))[:30]

def current_labels(c,pid):
    return c.execute("""SELECT r.relation_id::text id,k.object_id::text standard_id,k.canonical_name name,r.version,
        r.attributes->>'scheme' scheme,r.attributes->>'code' code,r.attributes->>'scheme_version' standard_version,
        r.attributes->>'classification_role' role FROM smartlib.relation_assertion r
        JOIN smartlib.knowledge_object k ON k.object_id=r.object_id
        WHERE r.subject_id=%s AND smartlib.analysis_state_eligible(r.review_state) AND r.system_to='infinity'
        AND r.predicate IN ('publication.classified_as_discipline','publication.has_research_topic')
        AND r.attributes->>'scheme'=ANY(%s) ORDER BY r.attributes->>'scheme',r.attributes->>'code'""",(pid,list(SCHEMES))).fetchall()

def enqueue(c,pid,actor,terms):
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('research:'+str(pid),))
    existing=c.execute("SELECT review_task_id,state,machine_suggestion FROM smartlib.review_task WHERE target_id=%s AND issue_type='RESEARCH_CLASSIFICATION' AND state IN ('open','in_review') FOR UPDATE",(pid,)).fetchone()
    if existing and existing['state']=='in_review':return str(existing['review_task_id'])
    ctx=content(c,pid);labels=current_labels(c,pid)
    data={**ctx,'candidates':exact_candidates(ctx['text'],terms),'current_labels':labels,
          'base_relations':{r['id']:r['version'] for r in labels},'method':METHOD,
          'gaps':([] if ctx['has_abstract'] else (['原文未提供常规摘要，已补正文依据；需结合全文审核'] if ctx.get('has_body_evidence') else ['缺少可用摘要，请补充摘要或阅读全文后手工分类'])),
          'guidance':'精细NSFC代码可按现有主方向前缀查询；证据不足时保留原粗分类。'}
    data['gaps']+=['教育部分类需先导入版本化标准'] if not c.execute("SELECT 1 FROM smartlib.knowledge_object WHERE attributes->>'scheme'='MOE_GRADUATE_DISCIPLINE' LIMIT 1").fetchone() else []
    if existing:
        c.execute('UPDATE smartlib.review_task SET machine_suggestion=%s WHERE review_task_id=%s',(Jsonb(data),existing['review_task_id']))
        return str(existing['review_task_id'])
    return str(c.execute("""INSERT INTO smartlib.review_task(issue_type,target_type,target_id,publication_id,object_id,reason_code,description,machine_suggestion,created_by)
       VALUES('RESEARCH_CLASSIFICATION','knowledge_object',%s,%s,%s,'research.classification','分类细化与主题审核',%s,%s) RETURNING review_task_id""",(pid,pid,pid,Jsonb(data),actor)).fetchone()['review_task_id'])

def generate(c,command,actor):
    stamp(c,actor,'生成分类建议，不更改已确认分类')
    ids=command.publication_ids or [UUID(r['id']) for r in objects(c,'publication')]
    terms=c.execute("""SELECT object_id::text id,canonical_name name,attributes FROM smartlib.knowledge_object
      WHERE attributes->>'standard_library'='research-classification' AND attributes->>'scheme'=ANY(%s)
      AND attributes->>'node_type' NOT IN ('root','qualifier') AND review_state='approved' AND system_to='infinity'""",(list(SCHEMES),)).fetchall()
    return {'task_ids':[enqueue(c,pid,actor,terms) for pid in ids],'count':len(ids)}

def task_list(c):
    return c.execute("""SELECT t.review_task_id::text id,t.object_id::text object_id,k.canonical_name name,k.object_type,t.state,
      t.issue_type,t.machine_suggestion,t.decision,t.updated_at,t.reviewed_at FROM smartlib.review_task t
      JOIN smartlib.knowledge_object k ON k.object_id=t.object_id WHERE t.issue_type IN ('RESEARCH_CLASSIFICATION','RESEARCH_PROJECT')
      ORDER BY CASE WHEN t.state IN ('open','in_review') THEN 0 ELSE 1 END,t.updated_at DESC LIMIT 1000""").fetchall()

def validate_labels(c,labels,project=False):
    if len({x.standard_id for x in labels})!=len(labels):raise ValueError('存在重复分类')
    rows=[]
    for label in labels:
        row=c.execute("SELECT object_id::text id,canonical_name name,attributes FROM smartlib.knowledge_object WHERE object_id=%s AND system_to='infinity' AND review_state='approved'",(label.standard_id,)).fetchone()
        if not row or row['attributes'].get('scheme') not in SCHEMES or row['attributes'].get('node_type') in {'root','qualifier'}:raise ValueError('分类词条不可用')
        if project and row['attributes']['scheme']!='NSFC_APPLICATION_CODE':raise ValueError('项目实际代码只能来自国自然标准')
        if row['attributes']['scheme']=='MESH' and label.role!='topic':raise ValueError('MeSH必须使用主题角色')
        rows.append({**row,'role':label.role})
    for scheme in SCHEMES:
        chosen=[r for r in rows if r['attributes']['scheme']==scheme]
        if len({r['attributes']['scheme_version'] for r in chosen})>1:raise ValueError('同一次分类不可混用同体系的多个版本')
        if chosen and scheme!='MESH' and sum(r['role']=='primary' for r in chosen)!=1:raise ValueError('每套所选学科分类必须有且仅有一个主方向')
    return rows

def propose(c,command,actor):
    row=c.execute("SELECT version,object_type FROM smartlib.knowledge_object WHERE object_id=%s AND system_to='infinity' FOR UPDATE",(command.object_id,)).fetchone()
    if not row:raise LookupError('对象不存在或无权读取')
    if row['version']!=command.expected_object_version:raise ValueError('对象已修改，请刷新后重试')
    if row['object_type']!=('project' if command.kind=='project' else 'publication'):raise ValueError('对象类型不符')
    if not command.labels:raise ValueError('请至少选择一项分类；缺少资料时不要提交确认')
    validate_labels(c,command.labels,command.kind=='project')
    if command.kind=='project' and len(command.summary.strip())<10:raise ValueError('请提供权威项目摘要或研究内容，不可使用代表作摘要代替')
    issue='RESEARCH_PROJECT' if command.kind=='project' else 'RESEARCH_CLASSIFICATION'
    c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('research:'+str(command.object_id),))
    data=command.model_dump(mode='json');data['method']='human_proposal'
    if command.kind=='classification':
        ctx=content(c,command.object_id);data['checksum']=ctx['checksum']
        data['base_relations']={r['id']:r['version'] for r in current_labels(c,command.object_id)}
    stamp(c,actor,'提交分类或项目资料建议，待审核')
    existing=c.execute("SELECT review_task_id FROM smartlib.review_task WHERE object_id=%s AND issue_type=%s AND state IN ('open','in_review') FOR UPDATE",(command.object_id,issue)).fetchone()
    if existing:
        c.execute("UPDATE smartlib.review_task SET state='in_review',machine_suggestion=%s WHERE review_task_id=%s",(Jsonb(data),existing['review_task_id']))
        return {'task_id':str(existing['review_task_id'])}
    task=c.execute("""INSERT INTO smartlib.review_task(issue_type,target_type,target_id,object_id,reason_code,description,machine_suggestion,state,created_by)
      VALUES(%s,'knowledge_object',%s,%s,'research.proposal','人工提交，等待审核',%s,'in_review',%s) RETURNING review_task_id""",(issue,command.object_id,command.object_id,Jsonb(data),actor)).fetchone()
    return {'task_id':str(task['review_task_id'])}

def evidence(c,oid,actor,source,text,metadata):
    sid=UUID('da35cce0-6a49-4ab4-92e3-29a03eccfdfc');ref,eid=uuid4(),uuid4()
    c.execute("INSERT INTO smartlib.source_system(source_system_id,code,name,owner_department,source_type,authorization_state) VALUES(%s,'research_workbench','研究方向治理','科研数据治理','manual','approved') ON CONFLICT DO NOTHING",(sid,))
    checksum=hashlib.sha256(json.dumps(metadata,sort_keys=True,default=str).encode()).hexdigest()
    c.execute("INSERT INTO smartlib.source_reference(source_reference_id,object_id,source_system_id,external_id,payload_checksum,metadata) VALUES(%s,%s,%s,%s,%s,%s)",(ref,oid,sid,str(ref),checksum,Jsonb({'source':source,**metadata})))
    c.execute("""INSERT INTO smartlib.evidence_record(evidence_id,object_id,source_reference_id,evidence_type,citation,excerpt,visibility,license_tags,content_checksum,metadata,created_by)
       VALUES(%s,%s,%s,'business_record',%s,%s,'restricted',ARRAY['internal-reference-use'],%s,%s,%s)""",(eid,oid,ref,source,text,checksum,Jsonb(metadata),actor))
    return eid

def decide(c,command,actor):
    stamp(c,actor,command.reason)
    if len(set(command.task_ids))!=len(command.task_ids):raise ValueError('重复任务ID')
    results=[]
    # Whole batch uses one transaction; a stale/missing task aborts all writes.
    for tid in sorted(command.task_ids):
        task=c.execute("SELECT * FROM smartlib.review_task WHERE review_task_id=%s AND issue_type IN ('RESEARCH_CLASSIFICATION','RESEARCH_PROJECT') FOR UPDATE",(tid,)).fetchone()
        if not task:raise LookupError('任务不可读取')
        if task['state'] not in {'open','in_review'}:raise ValueError('任务已处理，请刷新')
        expected=command.expected_updated_at.get(str(tid))
        if not expected or datetime.fromisoformat(expected.replace('Z','+00:00'))!=task['updated_at']:
            raise ValueError('审核任务已更新或缺少版本，请刷新后重试')
        data=task['machine_suggestion'];oid=task['object_id']
        if command.action=='approve':
            if data.get('method')!='human_proposal':raise ValueError('请先核对证据并编辑提交分类，不能直接批量批准词面命中建议')
            p=Proposal.model_validate(data);terms=validate_labels(c,p.labels,p.kind=='project')
            obj=c.execute("SELECT version,attributes FROM smartlib.knowledge_object WHERE object_id=%s AND system_to='infinity' FOR UPDATE",(oid,)).fetchone()
            if not obj or obj['version']!=p.expected_object_version:raise ValueError('对象版本冲突，请重新提交')
            if p.kind=='classification':
                current=current_labels(c,oid)
                if data['base_relations']!={r['id']:r['version'] for r in current} or data['checksum']!=content(c,oid)['checksum']:raise ValueError('论文内容或分类已变化，请重新核对')
            eid=evidence(c,oid,actor,p.source,p.evidence,{'proposal':data,'decision':command.reason,'reviewed_by':str(actor)})
            if p.kind=='project':
                attrs={**obj['attributes'],'official_nsfc_codes':[r['attributes']['scheme_code'] for r in terms],
                    'official_nsfc_version':terms[0]['attributes']['scheme_version'],'official_research_summary':p.summary,'official_research_source':p.source}
                c.execute('UPDATE smartlib.knowledge_object SET attributes=%s WHERE object_id=%s',(Jsonb(attrs),oid))
            else:
                chosen_versions={(r['attributes']['scheme'], r['attributes']['scheme_version']) for r in terms}
                # Replace only the proposed system/version; other versions and InCites remain intact.
                for scheme, version in sorted(chosen_versions):
                    c.execute("""UPDATE smartlib.relation_assertion SET review_state='superseded'
                        WHERE subject_id=%s AND attributes->>'scheme'=%s
                          AND attributes->>'scheme_version'=%s
                          AND smartlib.analysis_state_eligible(review_state) AND system_to='infinity'
                          AND predicate IN ('publication.classified_as_discipline','publication.has_research_topic')""",
                        (oid, scheme, version))
                for t in terms:
                    rid=uuid4();a=t['attributes']
                    attrs={'scheme':a['scheme'],'scheme_version':a['scheme_version'],'code':a['scheme_code'],'classification_role':t['role'],
                        'source_kind':'human_classification','method_version':METHOD,'source_import_batch':METHOD,'reviewed_by':str(actor),
                        'reviewed_at':datetime.now(timezone.utc).isoformat(),'review_note':command.reason,'evidence_excerpt':p.evidence[:4000]}
                    c.execute("""INSERT INTO smartlib.relation_assertion(relation_id,subject_id,predicate,object_id,fact_class,visibility,license_tags,review_state,attributes,created_by)
                      VALUES(%s,%s,%s,%s,'literature_fact','restricted',ARRAY['internal-reference-use'],'approved',%s,%s)""",
                      (rid,oid,'publication.has_research_topic' if a['scheme']=='MESH' else 'publication.classified_as_discipline',UUID(t['id']),Jsonb(attrs),actor))
                    c.execute('INSERT INTO smartlib.relation_evidence(relation_id,evidence_id) VALUES(%s,%s)',(rid,eid))
        c.execute("UPDATE smartlib.review_task SET state=%s,decision=%s,reviewed_by=%s,reviewed_at=clock_timestamp() WHERE review_task_id=%s",('resolved' if command.action=='approve' else 'rejected',Jsonb({'reason':command.reason,'action':command.action}),actor,tid))
        results.append(str(tid))
    return {'processed':results,'profiles':'按当前已确认分类实时更新，原关系及审核历史保留'}

def collaboration_members(c, institution_id):
    """Paper-context author affiliations, including descendant institutions."""
    return {str(r['person_id']): set(r['paper_ids']) for r in c.execute("""
        WITH RECURSIVE units(id) AS (
            SELECT object_id FROM smartlib.knowledge_object
            WHERE object_id=%s AND object_type IN ('organization','department')
              AND system_to='infinity' AND smartlib.analysis_state_eligible(review_state)
            UNION
            SELECT r.subject_id FROM smartlib.analysis_relation r JOIN units u ON r.object_id=u.id
            WHERE r.predicate='organization.part_of'
        )
        SELECT a.subject_id AS person_id, array_agg(DISTINCT a.context_object_id::text) AS paper_ids
        FROM smartlib.analysis_relation a JOIN units u ON a.object_id=u.id
        JOIN smartlib.analysis_relation author ON author.subject_id=a.subject_id
          AND author.object_id=a.context_object_id AND author.predicate='person.authored'
        WHERE a.predicate='person.affiliated_with'
        GROUP BY a.subject_id
    """, (institution_id,)).fetchall()}


def analytics(profiles,entity_id=None,collaboration_memberships=None,scheme="NSFC_APPLICATION_CODE",scheme_version=None):
    papers={k:p for k,p in profiles.items() if p['object_type']=='publication'}
    if entity_id:
        entity=profiles.get(entity_id)
        if not entity:return {'papers':0,'directions':[],'trends':[],'intersections':[],'collaboration':[]}
        eligible={x['publication_id'] for x in entity['papers']};papers={k:v for k,v in papers.items() if k in eligible}
    groups=defaultdict(set);years=defaultdict(set);pairs=defaultdict(set)
    for pid,p in papers.items():
        codes=[]
        for r in p['rows']:
            if r['scheme']!=scheme or (scheme_version is not None and r['scheme_version']!=scheme_version):continue
            key=(r['scheme_version'],r['code'],r['name']);groups[key].add(pid);codes.append(key)
            year=p['papers'][0]['year'];years[(year,*key)].add(pid)
        for pair in itertools.combinations(sorted(set(codes)),2):
            if pair[0][0]==pair[1][0]:pairs[pair].add(pid)
    persons={k:p for k,p in profiles.items() if p['object_type']=='person'}
    if collaboration_memberships is not None:
        persons={k:p for k,p in persons.items() if collaboration_memberships.get(k, set()) & set(papers)}
    people_by_code=defaultdict(set);pids_by_person={} 
    for oid,p in persons.items():
        pids_by_person[oid]={x['publication_id'] for x in p['papers']} & set(papers)
        for code,pids in groups.items():
            if pids & pids_by_person[oid]:people_by_code[code].add(oid)
    candidates=Counter()
    for ids in people_by_code.values():
        for a,b in itertools.combinations(sorted(ids),2):candidates[a,b]+=1
    collaboration=[]
    for (a,b),shared in candidates.most_common():
        common=pids_by_person[a]&pids_by_person[b]
        if common:continue
        # At least two shared topics, and two papers each; still only a candidate, no relation creation.
        if shared<2 or min(len(pids_by_person[a]),len(pids_by_person[b]))<2:continue
        codes=[{'version':k[0],'code':k[1],'name':k[2]} for k,ids in people_by_code.items() if a in ids and b in ids]
        collaboration.append({'a':a,'a_name':persons[a]['name'],'b':b,'b_name':persons[b]['name'],'shared':codes,
            'a_papers':sorted(pids_by_person[a]),'b_papers':sorted(pids_by_person[b]),'note':'本样本未见共同署名；仅方向相近候选，不表示现实中未合作或应当合作'})
        if len(collaboration)>=30:break
    return {'papers':len(papers),'classified':len(set().union(*groups.values())) if groups else 0,
      'directions':[{'version':k[0],'code':k[1],'name':k[2],'count':len(v),'papers':sorted(v)} for k,v in sorted(groups.items(),key=lambda x:-len(x[1]))],
      'trends':[{'year':k[0],'version':k[1],'code':k[2],'name':k[3],'count':len(v),'papers':sorted(v)} for k,v in sorted(years.items(),key=lambda x:str(x[0]))],
      'intersections':[{'a':k[0][2],'b':k[1][2],'version':k[0][0],'count':len(v),'papers':sorted(v)} for k,v in sorted(pairs.items(),key=lambda x:-len(x[1]))],
      'collaboration':collaboration,'paper_titles':{k:v['name'] for k,v in papers.items()},
      'note':'样本内描述性方向分布，不等于学科竞争力或全校趋势；交叉按同一论文多方向计数，不跨版本合并。'}

def projects(c,profiles):
    result=[]
    for p in objects(c,'project'):
        a=p['attributes'];profile=profiles.get(p['id'])
        if not profile and not a.get('official_nsfc_codes'):continue
        codes=a.get('official_nsfc_codes',[]);v=a.get('official_nsfc_version')
        directions=[r for r in (profile or {}).get('rows',[]) if r['scheme']=='NSFC_APPLICATION_CODE']
        missing=[name for key,name in [('official_nsfc_codes','项目实际申请代码'),('official_nsfc_version','代码年度版本'),('official_research_summary','权威项目摘要或研究内容'),('official_research_source','资料来源')] if not a.get(key)]
        comparable=[r for r in directions if r['scheme_version']==v]
        result.append({**p,'directions':directions,'missing':missing,'representative_papers':(profile or {}).get('total_papers',0),
          'comparison': '缺少权威资料，暂不能比较' if missing else '版本不同，未作等价映射' if directions and not comparable else '同版本层级相容' if any(x.startswith(r['code']) or r['code'].startswith(x) for x in codes for r in comparable) else '当前代表作方向未覆盖实际代码（不等于项目不合理）'})
    return result
