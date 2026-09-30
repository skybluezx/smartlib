"""Queue the current corpus for refinement without changing confirmed content."""
import json
import os
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from smartlib_platform.knowledge.research_workbench import SCHEMES,objects,enqueue,stamp
actor=UUID('00000000-0000-4000-8000-000000000001')
with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],row_factory=dict_row) as c:
    stamp(c,actor,'初始化第二期细化审核队列，保留全部已确认分类')
    papers=objects(c,'publication')
    terms=c.execute("""SELECT object_id::text id,canonical_name name,attributes FROM smartlib.knowledge_object
      WHERE attributes->>'standard_library'='research-classification' AND attributes->>'scheme'=ANY(%s)
      AND attributes->>'node_type' NOT IN ('root','qualifier') AND review_state='approved' AND system_to='infinity'""",(list(SCHEMES),)).fetchall()
    c.commit()
    for i,p in enumerate(papers,1):
        with c.transaction():
            stamp(c,actor,'初始化第二期细化审核队列，保留全部已确认分类')
            enqueue(c,UUID(p['id']),actor,terms)
        if i%25==0:print(json.dumps({'queued':i,'total':len(papers)}),flush=True)
    print(json.dumps({'queued':len(papers),'done':True}),flush=True)
