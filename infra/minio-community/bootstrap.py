"""Idempotently create the SmartLib bucket and enable object versioning.

The script uses only Python's standard library and AWS Signature Version 4 so the
bootstrap job does not introduce a second object-storage client image.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


ENDPOINT = os.environ.get("SMARTLIB_S3_ENDPOINT_URL", "http://minio:9000").rstrip("/")
ACCESS_KEY = os.environ["SMARTLIB_S3_ACCESS_KEY"]
SECRET_KEY = os.environ["SMARTLIB_S3_SECRET_KEY"]
REGION = os.environ.get("SMARTLIB_S3_REGION", "us-east-1")
BUCKETS = tuple(
    dict.fromkeys(
        (
            os.environ.get("SMARTLIB_S3_BUCKET", "smartlib-publications"),
            os.environ.get("SMARTLIB_REFERENCE_DATA_BUCKET", "smartlib-reference-data"),
        )
    )
)


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _request(method: str, path: str, query: str = "", body: bytes = b"") -> tuple[int, bytes]:
    now = dt.datetime.now(dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    parsed = urllib.parse.urlsplit(ENDPOINT)
    host = parsed.netloc
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical_query = query
    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        [method, path, canonical_query, canonical_headers, signed_headers, payload_hash]
    )
    scope = f"{date_stamp}/{REGION}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    date_key = _sign(("AWS4" + SECRET_KEY).encode("utf-8"), date_stamp)
    region_key = _sign(date_key, REGION)
    service_key = _sign(region_key, "s3")
    signing_key = _sign(service_key, "aws4_request")
    signature = hmac.new(
        signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={ACCESS_KEY}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    url = f"{ENDPOINT}{path}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(
        url,
        data=body if method in {"PUT", "POST"} else None,
        method=method,
        headers={
            "Authorization": authorization,
            "Host": host,
            "X-Amz-Content-Sha256": payload_hash,
            "X-Amz-Date": amz_date,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        response_body = exc.read()
        if exc.code == 409 and method == "PUT" and not query:
            return exc.code, response_body
        raise RuntimeError(
            f"S3 request failed: {method} {path} ({exc.code}) "
            f"{response_body.decode('utf-8', errors='replace')}"
        ) from exc


def main() -> None:
    results = []
    for bucket in BUCKETS:
        bucket_path = "/" + urllib.parse.quote(bucket, safe="")
        for attempt in range(1, 13):
            try:
                create_status, _ = _request("PUT", bucket_path)
                break
            except (OSError, RuntimeError) as exc:
                if attempt == 12:
                    raise
                print(f"MinIO 尚未可写（第 {attempt} 次）：{exc}", flush=True)
                time.sleep(2)

        versioning_body = (
            b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            b"<Status>Enabled</Status></VersioningConfiguration>"
        )
        versioning_status, _ = _request(
            "PUT", bucket_path, query="versioning=", body=versioning_body
        )
        head_status, _ = _request("HEAD", bucket_path)
        get_status, versioning_result = _request("GET", bucket_path, query="versioning=")
        if b"<Status>Enabled</Status>" not in versioning_result:
            raise RuntimeError(f"Bucket {bucket} exists, but versioning is not Enabled")
        results.append(
            {
                "bucket": bucket,
                "bucket_create_status": create_status,
                "bucket_head_status": head_status,
                "versioning_put_status": versioning_status,
                "versioning_get_status": get_status,
                "versioning": "Enabled",
            }
        )

    print(json.dumps({"endpoint": ENDPOINT, "buckets": results}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
