from smartlib_platform.knowledge.research_profiles import build_profiles

def fixture():
    objects={x:{'name':x,'object_type':t} for x,t in [('p','publication'),('q','publication'),('s','person'),('o','organization'),('g','project')]}
    papers={'p':{'title':'P','year':2024},'q':{'title':'Q','year':None}}
    memberships=[{'entity_id':e,'publication_id':p,'kind':k,'basis':b,'relation_id':e+p+str(n),'evidence_ids':['e'],'review_state':'approved'} for n,(e,p,k,b) in enumerate([
        ('s','p','person','person.authored'),('s','q','person','person.authored'),('o','p','organization','publication_snapshot'),
        ('o','p','organization','publication_snapshot'),('g','p','project','project.has_representative_publication')])]
    assignments=[{'publication_id':p,'scheme':'NSFC_APPLICATION_CODE','scheme_version':v,'code':'H01','name':'心脏','role':role,
      'source_kind':'algorithmic_inference','relation_id':p+v,'evidence_ids':['ev'],'review_state':state} for p,v,role,state in [('p','2026','primary','approved'),('p','2025','secondary','approved'),('q','2026','primary','pending')]]
    return objects,papers,memberships,assignments

def test_counts_scope_versions_and_pending():
    profiles=build_profiles(*fixture())
    assert profiles['o']['total_papers']==1
    assert len(profiles['o']['rows'])==2
    assert all(r['paper_count']==1 for r in profiles['o']['rows'])
    assert profiles['s']['coverage']['NSFC_APPLICATION_CODE']==2
    assert profiles['s']['total_papers']==2
    assert profiles['q']['rows'][0]['pending_publication_ids']==['q']
    assert profiles['g']['total_papers']==1

def test_excluded_states_and_pending_deduplication():
    o,p,m,a=fixture()
    a.append({**a[0], 'review_state':'pending', 'relation_id':'duplicate'})
    result=build_profiles(o,p,m,a)
    row=next(r for r in result['s']['rows'] if r['scheme_version']=='2026')
    assert row['paper_count']==2
    assert row['pending_publication_ids']==['p','q']
    for item in a:item['review_state']='rejected'
    a[0]['review_state']='superseded'
    assert build_profiles(o,p,m,a)['s']['rows']==[]

def test_reject_hr_and_unrelated_project_memberships():
    o,p,m,a=fixture()
    for r in m: r['basis']='employment'
    profiles=build_profiles(o,p,m,a)
    assert set(profiles)=={'p','q'}

def test_year_filter_and_missing_evidence():
    o,p,m,a=fixture()
    assert build_profiles(o,p,m,a,2024,2026)['s']['total_papers']==1
    for r in m:r['evidence_ids']=[]
    for r in a:r['evidence_ids']=[]
    profiles=build_profiles(o,p,m,a)
    assert 'o' not in profiles and profiles['s']['rows']==[]
