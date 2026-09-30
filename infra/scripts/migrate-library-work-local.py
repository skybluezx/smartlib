"""Local only: backup and validate archive before running the configured Flyway migration."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime

root = Path(__file__).resolve().parents[2]
db, migrator = json.loads(subprocess.check_output(['docker','inspect','smartlib-postgres-1','smartlib-migrate-1']))
db_env = dict(v.split('=',1) for v in db['Config']['Env'])
backup = Path('/private/tmp') / ('smartlib-before-library-work-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.dump')
with backup.open('wb') as output:
    os.chmod(backup,0o600)
    subprocess.run(['docker','exec',db['Name'].lstrip('/'),'pg_dump','-U',db_env['POSTGRES_USER'],'-d',db_env.get('POSTGRES_DB','smartlib'),'-Fc'],stdout=output,check=True)
with backup.open('rb') as stream:
    subprocess.run(['docker','exec','-i',db['Name'].lstrip('/'),'pg_restore','-l'],stdin=stream,stdout=subprocess.DEVNULL,check=True)
print('BACKUP',backup,'SHA256',hashlib.sha256(backup.read_bytes()).hexdigest(),flush=True)
with tempfile.TemporaryDirectory(prefix='smartlib-library-work-migrate-',dir='/private/tmp') as directory:
    env = Path(directory)/'flyway.env'
    env.write_text('\n'.join(v for v in migrator['Config']['Env'] if v.startswith('FLYWAY_'))+'\n');os.chmod(env,0o600)
    subprocess.run(['docker','run','--rm','--network',next(iter(migrator['NetworkSettings']['Networks'])), '--env-file',str(env),'-v',str(root/'database/migrations')+':/flyway/sql:ro',migrator['Config']['Image'],'migrate'],check=True)
