"""Publication-based profiles; display review status without changing stored decisions."""
from collections import defaultdict

BATCHES = ['paper-classification-269-20260909-v1', 'paper-classification-audit-269-20260909-v2']
POLICY = 'approved-and-pending-paper-profile-v2'
DISPLAY_CLASSIFICATION_STATES = ('approved', 'pending')


def build_profiles(objects, papers, memberships, assignments, start_year=None, end_year=None):
    allowed = {pid for pid,p in papers.items() if (start_year is None and end_year is None) or
               (p['year'] is not None and (start_year is None or p['year'] >= start_year) and
                (end_year is None or p['year'] <= end_year))}
    linked = defaultdict(lambda: defaultdict(set))
    for m in memberships:
        if m['kind'] not in {'person', 'organization', 'project'}:
            continue
        if m['kind']=='person' and m['basis']!='person.authored':
            continue
        if m['kind']=='project' and m['basis']!='project.has_representative_publication':
            continue
        if m['publication_id'] in allowed and m['review_state'] in DISPLAY_CLASSIFICATION_STATES:
            if m['kind']=='organization' and (m['basis']!='publication_snapshot' or not m['evidence_ids']):
                continue
            linked[m['entity_id']][m['publication_id']].add(m['relation_id'])
    for pid in allowed:
        if pid in objects: linked[pid][pid]
    by_paper = defaultdict(list)
    for a in assignments:
        if a['review_state'] in DISPLAY_CLASSIFICATION_STATES and a['publication_id'] in allowed and a['evidence_ids']:
            by_paper[a['publication_id']].append(a)
    profiles = {}
    for entity,pids in linked.items():
        if entity not in objects: continue
        groups = {}
        for pid in pids:
            for a in by_paper[pid]:
                key=(a['scheme'],a['scheme_version'],a['code'])
                row=groups.setdefault(key,{'scheme':key[0],'scheme_version':key[1],'code':key[2],'name':a['name'],
                    'publication_ids':set(),'pending_publication_ids':set(),'primary_publication_ids':set(),'relation_ids':set(),'evidence_ids':set(),'source_kinds':set()})
                row['publication_ids'].add(pid)
                if a['review_state']=='pending': row['pending_publication_ids'].add(pid)
                if a['role']=='primary': row['primary_publication_ids'].add(pid)
                row['relation_ids'].add(a['relation_id']);row['evidence_ids'].update(a['evidence_ids']);row['source_kinds'].add(a['source_kind'])
        rows=[]
        for row in groups.values():
            row={k:sorted(v) if isinstance(v,set) else v for k,v in row.items()}
            row['paper_count']=len(row['publication_ids']);row['primary_paper_count']=len(row['primary_publication_ids'])
            rows.append(row)
        years=[papers[pid]['year'] for pid in pids if papers[pid]['year'] is not None]
        profiles[entity]={'object_id':entity,**objects[entity],'policy_version':POLICY,'counting_unit':'distinct_publication',
            'derived_not_formal_affiliation':True,'multi_label_non_additive':True,'total_papers':len(pids),
            'start_year':min(years) if years else None,'end_year':max(years) if years else None,
            'unknown_year_papers':sum(papers[pid]['year'] is None for pid in pids),
            'coverage':{s:sum(any(a['scheme']==s for a in by_paper[pid]) for pid in pids) for s in ['NSFC_APPLICATION_CODE','MESH','INCITES_WOS','MOE_GRADUATE_DISCIPLINE']},
            'rows':sorted(rows,key=lambda r:(r['scheme'],-r['paper_count'],r['code'])),
            'papers':[{'publication_id':pid,**papers[pid],'membership_relation_ids':sorted(pids[pid])} for pid in sorted(pids)]}
    return profiles


def load_profiles(connection, object_id=None, start_year=None, end_year=None, publication_ids=None):
    # All visible publications; new publications enter coverage even before classification.
    scope=connection.execute("""SELECT k.object_id::text id,k.canonical_name title,m.publication_year AS "year"
        FROM smartlib.knowledge_object k
        JOIN smartlib.publication_metadata m ON m.publication_id=k.object_id
        WHERE k.system_to='infinity' AND k.review_state NOT IN ('superseded','rejected')""").fetchall()
    papers={p['id']:{'title':p['title'],'year':p['year']} for p in scope}
    if publication_ids is not None:
        papers={k:v for k,v in papers.items() if k in set(map(str, publication_ids))}
    if not papers:return {}
    members=connection.execute("""SELECT r.relation_id::text,r.subject_id::text,r.object_id::text,r.context_object_id::text,
        r.predicate,r.review_state,COALESCE(array_agg(DISTINCT e.evidence_id::text) FILTER(WHERE e.evidence_id IS NOT NULL),'{}') evidence_ids
        FROM smartlib.relation_assertion r
        LEFT JOIN smartlib.relation_evidence re ON re.relation_id=r.relation_id
        LEFT JOIN smartlib.evidence_record e ON e.evidence_id=re.evidence_id
        WHERE smartlib.analysis_state_eligible(r.review_state) AND r.system_to='infinity' AND (
          (r.predicate IN ('person.authored','project.has_representative_publication') AND r.object_id::text=ANY(%s)) OR
          (r.predicate='person.affiliated_with' AND r.context_object_id::text=ANY(%s)
           AND EXISTS(SELECT 1 FROM smartlib.publication_relation_provenance p JOIN smartlib.publication_authorship a
               ON a.publication_authorship_id=p.publication_authorship_id WHERE p.relation_id=r.relation_id
               AND a.publication_id=r.context_object_id AND a.person_object_id=r.subject_id)))
        AND (%s::uuid IS NULL OR CASE WHEN r.predicate='person.affiliated_with' THEN r.object_id ELSE r.subject_id END=%s::uuid)
        GROUP BY r.relation_id""",(list(papers),list(papers),object_id,object_id)).fetchall()
    memberships=[]
    for r in members:
        org=r['predicate']=='person.affiliated_with'
        memberships.append({'entity_id':r['object_id'] if org else r['subject_id'],
            'publication_id':r['context_object_id'] if org else r['object_id'],
            'kind':'organization' if org else ('person' if r['predicate']=='person.authored' else 'project'),
            'basis':'publication_snapshot' if org else r['predicate'],'relation_id':r['relation_id'],
            'evidence_ids':r['evidence_ids'],'review_state':r['review_state']})
    ids={m['entity_id'] for m in memberships}|({str(object_id)} if object_id else set(papers))
    objects={r['id']:{'name':r['canonical_name'],'object_type':r['object_type']} for r in connection.execute(
        "SELECT object_id::text id,canonical_name,object_type FROM smartlib.knowledge_object WHERE object_id::text=ANY(%s) AND system_to='infinity' AND review_state NOT IN ('rejected','superseded')",(list(ids),))}
    assignments=connection.execute("""SELECT r.relation_id::text,r.subject_id::text publication_id,r.review_state,k.canonical_name name,
        r.attributes->>'scheme' scheme,r.attributes->>'scheme_version' scheme_version,r.attributes->>'code' code,
        r.attributes->>'classification_role' role,r.attributes->>'source_kind' source_kind,
        array_agg(DISTINCT e.evidence_id::text) evidence_ids
        FROM smartlib.relation_assertion r JOIN smartlib.knowledge_object k ON k.object_id=r.object_id
        JOIN smartlib.relation_evidence re ON re.relation_id=r.relation_id JOIN smartlib.evidence_record e ON e.evidence_id=re.evidence_id
        WHERE r.predicate IN ('publication.classified_as_discipline','publication.has_research_topic')
        AND r.attributes->>'scheme' IN ('NSFC_APPLICATION_CODE','MESH','INCITES_WOS','MOE_GRADUATE_DISCIPLINE')
        AND r.review_state=ANY(%s) AND r.system_to='infinity'
        AND k.system_to='infinity' AND k.review_state NOT IN ('rejected','superseded')
        GROUP BY r.relation_id,k.canonical_name""", (list(DISPLAY_CLASSIFICATION_STATES),)).fetchall()
    return build_profiles(objects,papers,memberships,assignments,start_year,end_year)
