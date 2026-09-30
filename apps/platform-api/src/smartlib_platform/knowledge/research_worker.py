"""Generate suggestions for newly queued publications. Never approve classifications."""
import os
import time
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from .research_workbench import generate, Generate

def once():
    actor=UUID(os.environ.get('SMARTLIB_DEV_ACTOR_ID','00000000-0000-4000-8000-000000000001'))
    with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],row_factory=dict_row) as c:
        c.execute("SELECT set_config('smartlib.actor_id',%s,true)",(str(actor),))
        ids=[r['object_id'] for r in c.execute("SELECT object_id FROM smartlib.review_task WHERE issue_type='RESEARCH_CLASSIFICATION' AND state='open' AND machine_suggestion='{}'::jsonb ORDER BY created_at LIMIT 10")]
        if ids:generate(c,Generate(publication_ids=ids),actor)
        return len(ids)

if __name__=='__main__':
    while True:
        try:print({'generated':once()},flush=True)
        except Exception as e:print({'error':type(e).__name__,'message':str(e)[:300]},flush=True)
        time.sleep(30)
