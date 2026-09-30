"""Restore drill: source database is READ ONLY; isolated target is never reused."""
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

target = 'smartlib_restore_' + uuid4().hex
container = 'smartlib-postgres-1'

def sql(statement, database=None):
    command = 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d ' + (database or '"$POSTGRES_DB"') + ' -At'
    return subprocess.run(['docker','exec','-i',container,'sh','-c',command],
                          input=statement,text=True,capture_output=True,check=True).stdout.strip()

created = False
with tempfile.TemporaryDirectory(prefix='smartlib-restore-') as tmp:
    dump = Path(tmp)/'verification.dump'
    os.chmod(tmp,0o700)
    with dump.open('wb') as out:
        subprocess.run(['docker','exec',container,'sh','-c',
          'pg_dump -Fc --no-password -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],stdout=out,check=True)
    try:
        sql('CREATE DATABASE '+target+' TEMPLATE template0;', 'postgres')
        created = True
        with dump.open('rb') as source:
            subprocess.run(['docker','exec','-i',container,'sh','-c',
                'pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d '+target],
                stdin=source,check=True,capture_output=True)
        query="""SELECT count(*)::text || ':' || md5(COALESCE(string_agg(h,'' ORDER BY h),''))
                 FROM (SELECT md5(to_jsonb(t)::text) h FROM smartlib.knowledge_object t) h;"""
        assert sql(query)==sql(query,target), 'Restored objects differ from source (concurrent edits may require a quiet retry)'
        assert sql("SELECT to_regclass('smartlib.entity_revision') IS NOT NULL AND to_regclass('smartlib.change_event') IS NOT NULL;",target)=='t'
        print('PASS: isolated restore, object checksums, history and change-event schema; source untouched')
    finally:
        if created:
            sql('DROP DATABASE '+target+';', 'postgres')
            print('Removed only the uniquely named temporary restore database; temporary dump also cleaned up')
