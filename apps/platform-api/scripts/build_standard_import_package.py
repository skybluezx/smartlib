from __future__ import annotations
import hashlib
import json
import shutil
from pathlib import Path
from uuid import UUID, uuid5

SRC=Path('outputs/research_classification_20260909')
OUT=Path('outputs/standard_library_20260909')
NS=UUID('f7a1411b-971a-40d6-91a4-cde552496414')
DATASET='research-classification-standards'
BATCH='2026-09-09-v1'

def uid(*parts): return str(uuid5(NS, ':'.join(parts)))
def digest(data): return hashlib.sha256(data).hexdigest()

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    if json.loads((SRC/'nsfc_issues.json').read_text()): raise ValueError('NSFC issues unresolved')
    mesh=json.loads((SRC/'mesh_standard.json').read_text())
    nsfc=json.loads((SRC/'nsfc_structured.json').read_text())
    cells=json.loads((SRC/'wos_officecli_cells.json').read_text())['data']['results']
    wos=[{'code':r['text'],'name':r['text'],'source_locator':{'cell':r['path']}}
         for r in cells if r.get('text') and r['text']!='RESEARCH AREAS']
    if len({r['code'] for r in wos})!=len(wos):raise ValueError('Duplicate WOS label')
    schemes=[('NSFC_APPLICATION_CODE','2026','国家自然科学基金申请代码（2026）','nsfc','国家自然科学基金委员会',
              'sources/nsfc/index.html',nsfc),
             ('MESH','2026','MeSH医学主题词（2026）','nlm','US National Library of Medicine',
              'sources/desc2026.gz',mesh['terms']),
             ('INCITES_WOS','snapshot-2026-09-09','InCites Web of Science分类（官方清单快照）','clarivate','Clarivate',
              'sources/incites_wos_research_areas.xlsx',wos)]
    objects=[]; relations=[]; sources={}
    for scheme,version,title,authority_code,authority,root_file,terms in schemes:
        root_id=uid('term',scheme,version,'__scheme__')
        for term in [{'code':'__scheme__','name':title,'node_type':'scheme'},*terms]:
            code=term['code']; is_root=code=='__scheme__'
            path=term.get('source_path',root_file)
            if scheme=='MESH' and term.get('node_type')=='qualifier':path='sources/qual2026.xml'
            paths=[path]
            if term.get('additional_source_path'):paths.append(term['additional_source_path'])
            for original_path in paths:
                if original_path in sources:continue
                original=SRC/original_path
                receipt=json.loads(original.with_suffix(original.suffix+'.source.json').read_text())
                data=original.read_bytes()
                if digest(data)!=receipt['sha256']:raise ValueError('Source checksum changed')
                sources[original_path]={**receipt,'path':original_path}
                target=OUT/original_path; target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(original,target)
            source=sources[path]
            notes=[]
            if scheme=='MESH' and code in {'D047991','D048013'}:
                notes=['官方2026 XML中的3个树位置重复；保留不同DescriptorUI，不按树位置合并。']
            if scheme=='NSFC_APPLICATION_CODE':
                notes=['官方图片OCR、结构检查及疑点图像核验；不是逐条人工签署。']
                if code.startswith('T') and len(code)>1:notes.append('交叉科学部受理代码，不是独立申请代码。')
            attributes={'standard_library':'research-classification','dataset_id':DATASET,'dataset_version':BATCH,
                        'scheme':scheme,'scheme_version':version,'scheme_code':code,
                        'node_type':term.get('node_type','department' if len(code)==1 else 'category'),
                        'code_kind':'source_label_key' if scheme=='INCITES_WOS' else
                            ('acceptance_code' if scheme=='NSFC_APPLICATION_CODE' and code.startswith('T') and len(code)>1 and not is_root
                             else 'official_code'),
                        'source_authority':authority,'source_url':source['url'],'source_checksum':source['sha256'],
                        'source_locator':term.get('source_locator',{'code':code,'file':path}),
                        'standard_quality_notes':notes,'official':True,'synthetic':False}
            if 'aliases' in term:attributes['aliases']=term['aliases']
            if 'tree_numbers' in term:attributes['tree_numbers']=term['tree_numbers']
            if 'allowable_qualifiers' in term:attributes['allowable_qualifiers']=term['allowable_qualifiers']
            if term.get('level'):attributes['level']=term['level']
            oid=uid('term',scheme,version,code)
            objects.append({'id':oid,'name':term['name'],
                            'type':'concept' if is_root or scheme=='MESH' else 'discipline',
                            'attributes':attributes,'quality':'warning' if notes else 'validated',
                            'source_id':uid('source_system',authority_code),
                            'source_code':'research_standard_'+authority_code,
                            'source_name':authority,'source_path':path,
                            'reference_id':uid('reference',oid),'evidence_id':uid('evidence',oid),
                            'evidence':term,'checksum':digest(json.dumps(term,ensure_ascii=False,sort_keys=True).encode())})
            if not is_root:
                relations.append({'id':uid('contains',root_id,oid),'subject':root_id,'object':oid,
                                  'predicate':'taxonomy.contains','evidence_id':uid('evidence',oid),
                                  'attributes':{'dataset_id':DATASET,'dataset_version':BATCH,'scheme':scheme}})
            parent=term.get('parent_code')
            if parent:
                relations.append({'id':uid('broader',oid,parent),'subject':oid,'object':uid('term',scheme,version,parent),
                                  'predicate':'taxonomy.broader','evidence_id':uid('evidence',oid),
                                  'attributes':{'dataset_id':DATASET,'dataset_version':BATCH,'scheme':scheme}})
    for child,parent in mesh['broader']:
        cid=uid('term','MESH','2026',child);pid=uid('term','MESH','2026',parent)
        relations.append({'id':uid('broader',cid,parent),'subject':cid,'object':pid,
                          'predicate':'taxonomy.broader','evidence_id':uid('evidence',cid),
                          'attributes':{'dataset_id':DATASET,'dataset_version':BATCH,'scheme':'MESH'}})
    ids={r['id'] for r in objects}
    assert len(ids)==len(objects) and len({r['id'] for r in relations})==len(relations)
    assert all(r['subject'] in ids and r['object'] in ids and r['subject']!=r['object'] for r in relations)
    assert all(r['name'].strip() for r in objects)
    # Include official definitions, corrections and quality receipts in the archival manifest.
    for relative in ['sources/incites_wos_definition.html','nsfc_visual_corrections.json',
                     'nsfc_structured.json','mesh_tree_conflicts.json']:
        path=SRC/relative; data=path.read_bytes();target=OUT/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        receipt=path.with_suffix(path.suffix+'.source.json')
        sources[relative]=({'path':relative,**json.loads(receipt.read_text())} if receipt.exists() else
                           {'path':relative,'url':'local-generated:standard-quality-audit','sha256':digest(data),'bytes':len(data)})
        sources[relative]['path']=relative
    package={'batch':BATCH,'dataset_id':DATASET,'objects':objects,'relations':relations,'sources':list(sources.values())}
    (OUT/'package.json').write_text(json.dumps(package,ensure_ascii=False))
    print(json.dumps({'objects':len(objects),'relations':len(relations),'source_files':len(sources)},ensure_ascii=False))

if __name__=='__main__':build()
