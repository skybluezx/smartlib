"""Exercise identity tables and review integration on a disposable database."""
import os
from uuid import UUID, uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from smartlib_platform.changes import service as changes
from smartlib_platform.identities import service as identities
from smartlib_platform.knowledge.service import get_object_detail, list_object_catalog
from smartlib_platform.scholars.service import list_scholars

db=os.environ['SMARTLIB_TEST_DATABASE'];assert db.endswith('_test')
actor=UUID(os.environ['SMARTLIB_DEV_ACTOR_ID'])
with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],dbname=db,row_factory=dict_row) as c:
 try:
  c.execute("SELECT set_config('smartlib.actor_id',%s,true)",(str(actor),))
  ids={kind:uuid4() for kind in ['person','organization','department']}
  for kind,oid in ids.items():
   attributes={} if kind in ('person','department') else {'source':'identity-integration-test','identity_resolution_status':'name_only'}
   c.execute('''INSERT INTO smartlib.knowledge_object(object_id,object_type,canonical_name,attributes,created_by)
                VALUES(%s,%s,%s,%s,%s)''',(oid,kind,'Identity '+kind,Jsonb(attributes),actor))
   profile=identities.get_identity(c,oid);assert profile['names'][0]['name']=='Identity '+kind
  def submit(oid,items):
   row=identities.get_identity(c,oid)
   command=changes.SubmissionInput(context_object_id=oid,source_label='Verified identity source',reason='Check source',
    proposals=[changes.ProposalInput(target_kind='object',target_id=oid,field_path=path,proposed_value=value,base_version=row['version']) for path,value in items])
   s=changes.submit(c,command,actor,'identity-test')
   return changes.decide(c,s['submission_id'],changes.DecisionInput(decision='accept',reason='Source reviewed'),actor,'identity-test')
  person=ids['person'];org=ids['organization']
  r=submit(person,[('profile.given_name','Ada'),('profile.family_name','Example'),('profile.preferred_language','en'),('identifiers.orcid','https://orcid.org/0000-0002-1825-0097'),('identity.aliases',['A. Example','Ada Example'])])
  assert all(p['application_state']=='applied' for p in r['proposals'])
  profile=identities.get_identity(c,person)
  assert profile['profile']['given_name']=='Ada' and profile['identifiers'][0]['normalized_value']=='0000-0002-1825-0097'
  assert profile['version']==2,profile['version']
  assert profile['profile']['submission_id'] and profile['profile']['evidence_id']
  assert list_scholars(c,query='A. Example')
  assert list_object_catalog(c,query='0000-0002-1825-0097').items
  assert get_object_detail(c,person).identifiers[0].identifier_type=='orcid'
  assert person in [o.object_id for o in list_object_catalog(c,query='A. Example').items]
  assert 'A. Example' in c.execute('SELECT smartlib.identity_search_aliases(%s) aliases',(person,)).fetchone()['aliases']
  submit(org,[('profile.country_code','cn'),('profile.organization_type','hospital'),('identifiers.ror','https://ror.org/03yrm5c26'),('identity.aliases',['机构测试简称'])])
  assert identities.get_identity(c,org)['profile']['country_code']=='CN'
  submit(ids['department'],[('profile.organization_type','department')])
  # Retire an identifier without deleting its history.
  submit(person,[('identifiers.orcid',None),('identity.aliases',['Ada Example'])])
  assert identities.get_identity(c,person)['identifiers']==[]
  assert len(identities.get_identity(c,person)['names'])==2
  submit(person,[('identifiers.orcid','0000-0002-1825-0097')])
  try:
   with c.transaction():
    c.execute("INSERT INTO smartlib.person_identifier(object_id,identifier_type,normalized_value,created_by) SELECT object_id,'orcid','0000-0002-1825-0097',%s FROM smartlib.person_profile WHERE object_id<>%s LIMIT 1",(actor,person))
  except psycopg.errors.UniqueViolation:pass
  else:raise AssertionError('Duplicate ORCID assigned to two people')
  try:
   with c.transaction():
    c.execute('INSERT INTO smartlib.person_profile(object_id,created_by) VALUES(%s,%s)',(org,actor))
  except psycopg.errors.CheckViolation:pass
  else:raise AssertionError('Wrong profile object type accepted')
  try:identities.normalize(c,'person','identifiers.orcid','0000-0002-1825-0098')
  except ValueError:pass
  else:raise AssertionError('Invalid checksum accepted')
  c.execute("SELECT set_config('smartlib.actor_id',%s,true)",(str(uuid4()),))
  assert c.execute('SELECT * FROM smartlib.person_profile WHERE object_id=%s',(person,)).fetchone() is None
  print('PASS auto profiles, person/organization/department details, reviewed fields, identifiers, aliases, catalog and search, retirement, uniqueness, type guard, checksum and RLS')
 finally:c.rollback()
