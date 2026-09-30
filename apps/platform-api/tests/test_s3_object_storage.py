from io import BytesIO
from uuid import UUID

import httpx
import pytest

from smartlib_platform.storage.s3 import (
    InvalidFulltextFile,
    S3ObjectStore,
    inspect_pdf,
    object_key,
    staged_fulltext_key,
    staged_text_key,
)

PUBLICATION_ID = UUID("00000000-0000-4000-8000-000000000123")


def test_pdf_is_validated_and_named_by_publication_and_checksum() -> None:
    stream = BytesIO(b"%PDF-1.7\nexample")
    prepared = inspect_pdf(stream, "论文 全文.pdf", 1024)

    assert prepared.size_bytes == 16
    assert len(prepared.content_checksum) == 64
    assert object_key(PUBLICATION_ID, prepared.content_checksum, prepared.file_name) == (
        f"publications/{PUBLICATION_ID}/fulltext/{prepared.content_checksum}/fulltext.pdf"
    )
    assert stream.tell() == 0
    assert staged_fulltext_key(prepared.content_checksum) == (
        f"intake/publication-fulltexts/{prepared.content_checksum}/fulltext.pdf"
    )
    assert staged_text_key(prepared.content_checksum) == (
        f"intake/publication-fulltexts/{prepared.content_checksum}/derived/fulltext.txt"
    )


@pytest.mark.parametrize(
    ("content", "name", "message"),
    [
        (b"", "paper.pdf", "上传文件为空"),
        (b"not a pdf", "paper.pdf", "文件内容不是有效的 PDF 格式"),
        (b"%PDF-1.7", "paper.txt", "当前阶段只接收 PDF 全文文件"),
    ],
)
def test_invalid_pdf_is_rejected(content: bytes, name: str, message: str) -> None:
    with pytest.raises(InvalidFulltextFile, match=message):
        inspect_pdf(BytesIO(content), name, 1024)


def test_existing_content_addressed_object_is_reused() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"x-amz-version-id": "version-1"})

    prepared = inspect_pdf(BytesIO(b"%PDF-1.7\nexample"), "paper.pdf", 1024)
    store = S3ObjectStore(
        "http://minio:9000",
        "smartlib-publications",
        "access",
        "secretsecret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = store.put_fulltext(PUBLICATION_ID, prepared, BytesIO(b"%PDF-1.7\nexample"))

    assert result.created is False
    assert result.version_id == "version-1"
    assert result.storage_uri.startswith("s3://smartlib-publications/publications/")
    assert [request.method for request in requests] == ["HEAD"]
    assert requests[0].headers["authorization"].startswith("AWS4-HMAC-SHA256")


def test_object_bytes_can_be_read_with_signed_get() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"full text")

    store = S3ObjectStore(
        "http://minio:9000",
        "smartlib-publications",
        "access",
        "secretsecret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert store.get_bytes("publications/example/derived/fulltext.txt") == b"full text"
    assert [request.method for request in requests] == ["GET"]
    assert requests[0].headers["authorization"].startswith("AWS4-HMAC-SHA256")


def test_object_byte_range_is_forwarded_for_pdf_reading() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            206,
            content=b"partial pdf",
            headers={"content-range": "bytes 0-10/100", "etag": '"pdf-version"'},
        )

    store = S3ObjectStore(
        "http://minio:9000",
        "smartlib-publications",
        "access",
        "secretsecret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = store.get_object("publications/example/paper.pdf", "bytes=0-10")

    assert result.status_code == 206
    assert result.content == b"partial pdf"
    assert result.content_range == "bytes 0-10/100"
    assert requests[0].headers["range"] == "bytes=0-10"
