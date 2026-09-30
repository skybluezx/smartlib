"""Read-only S3 retention check; no object or bucket mutations."""
import os
from hashlib import sha256
from xml.etree import ElementTree as ET

from smartlib_platform.storage.s3 import S3ObjectStore

s = S3ObjectStore(os.environ['SMARTLIB_S3_ENDPOINT_URL'], os.environ['SMARTLIB_S3_BUCKET'],
                  os.environ['SMARTLIB_S3_ACCESS_KEY'], os.environ['SMARTLIB_S3_SECRET_KEY'])
r = s._request('GET', '/'+s.bucket, sha256(b'').hexdigest(), query='versioning=')
r.raise_for_status()
assert ET.fromstring(r.content).findtext('{*}Status') == 'Enabled', 'Fulltext bucket versioning is not enabled'
r = s._request('GET', '/'+s.bucket, sha256(b'').hexdigest(), query='lifecycle=')
if r.status_code == 404:
    assert ET.fromstring(r.content).findtext('Code') == 'NoSuchLifecycleConfiguration'
elif r.status_code == 200:
    root = ET.fromstring(r.content)
    assert not any(rule.findtext('{*}Status') == 'Enabled' and
                   (rule.find('{*}Expiration') is not None or rule.find('{*}NoncurrentVersionExpiration') is not None)
                   for rule in root.findall('{*}Rule')), 'Automatic file/version expiry requires explicit review'
else:
    r.raise_for_status()
print('PASS: fulltext versioning enabled; no automatic object/version expiration')
print('This does not prove off-host backup, immutable retention, or recovery of previously deleted versions.')
