from __future__ import annotations

import hmac
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import PurePath
from typing import BinaryIO
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx


class InvalidFulltextFile(ValueError):
    pass


class ObjectStoreUnavailable(RuntimeError):
    pass


class ObjectRangeNotSatisfiable(ValueError):
    pass


@dataclass(frozen=True)
class PreparedFulltext:
    file_name: str
    content_checksum: str
    size_bytes: int
    mime_type: str


@dataclass(frozen=True)
class StoredObject:
    storage_uri: str
    object_key: str
    created: bool
    version_id: str | None


@dataclass(frozen=True)
class RetrievedObject:
    content: bytes
    status_code: int
    content_length: int
    content_range: str | None = None
    etag: str | None = None


def inspect_pdf(stream: BinaryIO, file_name: str, max_bytes: int) -> PreparedFulltext:
    safe_name = PurePath(file_name or "").name.strip()
    if not safe_name or safe_name in {".", ".."}:
        raise InvalidFulltextFile("文件名不能为空")
    if not safe_name.lower().endswith(".pdf"):
        raise InvalidFulltextFile("当前阶段只接收 PDF 全文文件")

    digest = sha256()
    size = 0
    prefix = b""
    stream.seek(0)
    while chunk := stream.read(1024 * 1024):
        if not prefix:
            prefix = chunk[:5]
        size += len(chunk)
        if size > max_bytes:
            raise InvalidFulltextFile(f"文件超过允许的 {max_bytes // (1024 * 1024)} MB")
        digest.update(chunk)
    stream.seek(0)

    if size == 0:
        raise InvalidFulltextFile("上传文件为空")
    if prefix != b"%PDF-":
        raise InvalidFulltextFile("文件内容不是有效的 PDF 格式")
    return PreparedFulltext(
        file_name=safe_name,
        content_checksum=digest.hexdigest(),
        size_bytes=size,
        mime_type="application/pdf",
    )


def object_key(publication_id: UUID, checksum: str, file_name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", PurePath(file_name).stem).strip("-_")
    if not stem:
        stem = "fulltext"
    return f"publications/{publication_id}/fulltext/{checksum}/{stem[:120]}.pdf"


def staged_fulltext_key(checksum: str) -> str:
    if not re.fullmatch(r"[A-Fa-f0-9]{64}", checksum):
        raise ValueError("全文校验和格式无效")
    return f"intake/publication-fulltexts/{checksum.lower()}/fulltext.pdf"


def staged_text_key(checksum: str) -> str:
    if not re.fullmatch(r"[A-Fa-f0-9]{64}", checksum):
        raise ValueError("全文校验和格式无效")
    return f"intake/publication-fulltexts/{checksum.lower()}/derived/fulltext.txt"


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), sha256).digest()


class S3ObjectStore:
    def __init__(
        self,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self._client = client

    def _headers(
        self, method: str, path: str, payload_hash: str, canonical_query: str = ""
    ) -> dict[str, str]:
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        host = urlsplit(self.endpoint_url).netloc
        canonical_headers = (
            f"host:{host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            [method, path, canonical_query, canonical_headers, signed_headers, payload_hash]
        )
        scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            ["AWS4-HMAC-SHA256", amz_date, scope, sha256(canonical_request.encode()).hexdigest()]
        )
        date_key = _sign(("AWS4" + self.secret_key).encode(), date_stamp)
        region_key = _sign(date_key, self.region)
        service_key = _sign(region_key, "s3")
        signing_key = _sign(service_key, "aws4_request")
        signature = hmac.new(signing_key, string_to_sign.encode(), sha256).hexdigest()
        return {
            "Authorization": (
                f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            ),
            "Host": host,
            "X-Amz-Content-Sha256": payload_hash,
            "X-Amz-Date": amz_date,
        }

    def _request(
        self,
        method: str,
        object_path: str,
        payload_hash: str,
        content: Iterator[bytes] | None = None,
        extra_headers: dict[str, str] | None = None,
        query: str = "",
    ) -> httpx.Response:
        client = self._client or httpx.Client(timeout=httpx.Timeout(60, connect=5))
        close_client = self._client is None
        try:
            return client.request(
                method,
                f"{self.endpoint_url}{object_path}{f'?{query}' if query else ''}",
                headers={
                    **self._headers(method, object_path, payload_hash, query),
                    **(extra_headers or {}),
                },
                content=content,
            )
        except httpx.HTTPError as exc:
            raise ObjectStoreUnavailable("对象存储当前不可用") from exc
        finally:
            if close_client:
                client.close()

    def put_fulltext(
        self,
        publication_id: UUID,
        prepared: PreparedFulltext,
        stream: BinaryIO,
    ) -> StoredObject:
        key = object_key(publication_id, prepared.content_checksum, prepared.file_name)
        return self.put_prepared(key, prepared, stream)

    def head_object(self, key: str) -> dict[str, str] | None:
        path = "/" + quote(f"{self.bucket}/{key}", safe="/")
        response = self._request("HEAD", path, sha256(b"").hexdigest())
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise ObjectStoreUnavailable(f"对象存储检查失败 (HTTP {response.status_code})")
        return dict(response.headers)

    def get_bytes(self, key: str) -> bytes:
        return self.get_object(key).content

    def get_object(self, key: str, range_header: str | None = None) -> RetrievedObject:
        path = "/" + quote(f"{self.bucket}/{key}", safe="/")
        response = self._request(
            "GET",
            path,
            sha256(b"").hexdigest(),
            extra_headers={"Range": range_header} if range_header else None,
        )
        if response.status_code == 404:
            raise FileNotFoundError(key)
        if response.status_code == 416:
            raise ObjectRangeNotSatisfiable(range_header or "")
        if response.status_code not in {200, 206}:
            raise ObjectStoreUnavailable(f"对象存储读取失败 (HTTP {response.status_code})")
        return RetrievedObject(
            content=response.content,
            status_code=response.status_code,
            content_length=len(response.content),
            content_range=response.headers.get("content-range"),
            etag=response.headers.get("etag"),
        )

    def put_prepared(
        self,
        key: str,
        prepared: PreparedFulltext,
        stream: BinaryIO,
    ) -> StoredObject:
        path = "/" + quote(f"{self.bucket}/{key}", safe="/")
        head = self.head_object(key)
        if head is not None:
            return StoredObject(
                f"s3://{self.bucket}/{key}", key, False, head.get("x-amz-version-id")
            )

        stream.seek(0)

        def chunks() -> Iterator[bytes]:
            while chunk := stream.read(1024 * 1024):
                yield chunk

        response = self._request(
            "PUT",
            path,
            prepared.content_checksum,
            content=chunks(),
            extra_headers={
                "Content-Type": prepared.mime_type,
                "Content-Length": str(prepared.size_bytes),
            },
        )
        if response.status_code not in {200, 201}:
            raise ObjectStoreUnavailable(f"对象存储写入失败 (HTTP {response.status_code})")
        return StoredObject(
            f"s3://{self.bucket}/{key}", key, True, response.headers.get("x-amz-version-id")
        )

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        checksum = sha256(data).hexdigest()
        path = "/" + quote(f"{self.bucket}/{key}", safe="/")
        head = self.head_object(key)
        if head is not None:
            return StoredObject(
                f"s3://{self.bucket}/{key}", key, False, head.get("x-amz-version-id")
            )
        stream = BytesIO(data)

        def chunks() -> Iterator[bytes]:
            while chunk := stream.read(1024 * 1024):
                yield chunk

        response = self._request(
            "PUT", path, checksum, content=chunks(),
            extra_headers={"Content-Type": content_type, "Content-Length": str(len(data))},
        )
        if response.status_code not in {200, 201}:
            raise ObjectStoreUnavailable(f"对象存储写入失败 (HTTP {response.status_code})")
        return StoredObject(
            f"s3://{self.bucket}/{key}", key, True, response.headers.get("x-amz-version-id")
        )

    def delete_version(self, key: str, version_id: str) -> None:
        path = "/" + quote(f"{self.bucket}/{key}", safe="/")
        query = "versionId=" + quote(version_id, safe="-_.~")
        response = self._request("DELETE", path, sha256(b"").hexdigest(), query=query)
        if response.status_code != 204:
            raise ObjectStoreUnavailable(f"对象存储清理失败 (HTTP {response.status_code})")
