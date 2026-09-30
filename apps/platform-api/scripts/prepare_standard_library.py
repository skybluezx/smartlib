"""Prepare versioned standards; all work is staging until controlled import succeeds."""
from __future__ import annotations
import collections
import gzip
import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path('outputs/research_classification_20260909')

def save(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def nsfc():
    records, issues = [], []
    departments = dict(zip('ABCDEFGHT', ['数学物理科学部','化学科学部','生命科学部','地球科学部',
                          '工程与材料科学部','信息科学部','管理科学部','医学科学部','交叉科学部']))
    for letter, name in departments.items():
        records.append({'code': letter, 'name': name, 'parent_code': None, 'level': 1,
                        'source_path': 'sources/nsfc/index.html', 'evidence': '官方目录科学部标题'})
    for file in sorted((ROOT / 'nsfc_ocr').glob('*.json')):
        rows = json.loads(file.read_text())
        for row in rows:
            if file.name == 'd8_image2.jpg.json' and row['text'] == 'H009':
                row['original_text'] = row['text']; row['text'] = 'H0109'
            if file.name == 'd8_image7.jpg.json' and row['text'] == 'H135':
                row['original_text'] = row['text']; row['text'] = 'H35'
        for column in (0, 1):
            items = [r for r in rows if (r['x'] >= .5) == bool(column)
                     and not (file.name == 'd9_image2.jpg.json' and r['y'] < .3)]
            codes = []
            for row in items:
                match = re.match(r'^([A-HT][0-9OIl]{2}(?:[0-9OIl]{2})?)(?![0-9OIl])(.*)', row['text'])
                if match:
                    code = match[1][0] + match[1][1:].translate(str.maketrans('OIl','011'))
                    codes.append((row, code, match[2].strip(' .；;')))
            codes.sort(key=lambda r: -(r[0]['y'] + r[0]['height']/2))
            used = set()
            for i, (row, code, suffix) in enumerate(codes):
                center = row['y'] + row['height']/2
                bottom = codes[i+1][0]['y'] + codes[i+1][0]['height']/2 if i+1 < len(codes) else -1
                parts = [suffix] if suffix else []
                evidence = [row]
                for j, other in enumerate(items):
                    cy = other['y'] + other['height']/2
                    if other['x'] <= row['x'] + .01 or any(other is c[0] for c in codes):
                        continue
                    if bottom + .008 < cy <= center + .015 and not re.search(r'科学部$', other['text']):
                        parts.append(other['text']); evidence.append(other); used.add(j)
                name = ''.join(parts).strip()
                records.append({'code': code, 'name': name, 'level': 2 if len(code)==3 else 3,
                                'parent_code': code[0] if len(code)==3 else code[:3],
                                'source_path': 'sources/nsfc/' + file.name.removesuffix('.json'),
                                'evidence': evidence})
                if not name:
                    issues.append({'code': code, 'problem': 'empty_name', 'file':file.name})
            for j, row in enumerate(items):
                if j not in used and not any(row is c[0] for c in codes) and not re.search(r'科学部|申请代码|国家自然科学|^[A-HT]\.$',row['text']):
                    issues.append({'problem':'unassigned_text','file':file.name,'text':row['text']})
    corrections = json.loads((ROOT / 'nsfc_visual_corrections.json').read_text())
    for row in records:
        if row['code'] in corrections:
            row['ocr_name_before_review'] = row['name']
            row['name'] = corrections[row['code']]
            row['review_method'] = 'source_image_visual_verification'
        if row['code']=='A1701':
            row['additional_source_path']='sources/nsfc/d1_image4.jpg'
    issues = [i for i in issues if not (i.get('file')=='d1_image4.jpg.json'
                                       and i.get('text')=='天体的探测与性质')]
    counts = collections.Counter(r['code'] for r in records)
    for code, count in counts.items():
        if count>1: issues.append({'code':code,'problem':'duplicate_code','count':count})
    for row in records:
        if row['parent_code'] and row['parent_code'] not in counts:
            issues.append({'code':row['code'],'problem':'missing_parent','parent':row['parent_code']})
    save('nsfc_structured.json',records); save('nsfc_issues.json',issues)
    return records, issues

def mesh():
    terms = json.loads((ROOT / 'mesh_descriptors_2026.json').read_text())
    for term in terms:
        term['node_type']='descriptor'
    root = ET.parse(ROOT / 'sources/qual2026.xml').getroot()
    qualifiers=[]
    for q in root.findall('QualifierRecord'):
        qualifiers.append({'code':q.findtext('QualifierUI'),'name':q.findtext('QualifierName/String'),
                           'tree_numbers':[t.text for t in q.findall('TreeNumberList/TreeNumber')],
                           'aliases':sorted({t.text for t in q.findall('ConceptList/Concept/TermList/Term/String')
                                             if t.text and t.text != q.findtext('QualifierName/String')}),
                           'node_type':'qualifier','scheme':'MESH','version':'2026'})
    qualifier_ids = {q['code'] for q in qualifiers}
    descriptor_by_id = {d['code']:d for d in terms}
    with gzip.open(ROOT / 'sources/desc2026.gz') as stream:
        for _, n in ET.iterparse(stream,events=('end',)):
            if n.tag != 'DescriptorRecord': continue
            allowed = [q.findtext('QualifierUI') for q in n.findall('AllowableQualifiersList/AllowableQualifier/QualifierReferredTo')]
            if set(allowed)-qualifier_ids: raise ValueError('Missing allowable qualifier')
            descriptor_by_id[n.findtext('DescriptorUI')]['allowable_qualifiers']=allowed
            n.clear()
    trees = collections.defaultdict(set)
    for row in terms+qualifiers:
        for tree in row['tree_numbers']:
            key=(row['node_type'],tree)
            trees[key].add(row['code'])
    save('mesh_tree_conflicts.json',[{'node_type':k[0],'tree_number':k[1],'codes':sorted(v)}
                                    for k,v in trees.items() if len(v)>1])
    edges=set(); root_positions=[]
    for row in terms+qualifiers:
        for tree in row['tree_numbers']:
            parent = tree.rsplit('.',1)[0] if '.' in tree else None
            if parent and (row['node_type'],parent) not in trees:
                raise ValueError(f'Missing MeSH tree parent {tree}')
            if parent:
                if len(trees[(row['node_type'],parent)])!=1:
                    raise ValueError(f'Ambiguous MeSH parent {parent}; quarantine relation before import')
                edges.add((row['code'],next(iter(trees[(row['node_type'],parent)]))))
            else: root_positions.append(tree)
    save('mesh_standard.json',{'terms':terms+qualifiers,'broader':sorted(edges),'root_positions':root_positions})
    return len(terms),len(qualifiers),len(edges)

def wos():
    env = {**os.environ,'OFFICECLI_NO_AUTO_RESIDENT':'1'}
    result = subprocess.run(['officecli','query',str(ROOT/'sources/incites_wos_research_areas.xlsx'),
                             'cell','--json'],env=env,text=True,capture_output=True,check=True)
    payload=json.loads(result.stdout)
    save('wos_officecli_cells.json',payload)
    return payload

if __name__=='__main__':
    rows,issues=nsfc()
    print('NSFC:',len(rows),'issues:',len(issues),collections.Counter(r['problem'] for r in issues))
    print('MeSH descriptor/qualifier/broader:',mesh())
    wos()
