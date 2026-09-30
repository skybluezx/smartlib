from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from smartlib_platform.knowledge_hub.http import register
from smartlib_platform.knowledge_hub.models import ApplicationCommand, LibraryCommand, SourceCommand
from smartlib_platform.knowledge_hub.service import parse_library_csv, run_rule

HEADER = "metric_code,metric_name,period,organization,value,unit,source_reference\n"
ROW = "visits,到馆人次,2026-09-01,图书馆,10,人次,月度报告\n"


def test_library_csv_validation_before_persistence():
    assert parse_library_csv((HEADER + ROW).encode())[0].value == 10
    with pytest.raises(ValueError, match="重复"):
        parse_library_csv((HEADER + ROW + ROW).encode())
    with pytest.raises(ValueError, match=r"格式|字段"):
        parse_library_csv((HEADER + ROW.replace("2026-09-01", "2026-09-15")).encode())
    with pytest.raises(ValueError, match="单位不一致"):
        parse_library_csv(
            (HEADER + ROW + ROW.replace("2026-09", "2026-08").replace("人次,月度", "次数,月度")).encode()
        )
    for value in ["NaN", "Infinity", "-1"]:
        with pytest.raises(ValidationError):
            LibraryCommand(
                metric_code="visits",
                metric_name="到馆人次",
                period="2026-09-01",
                organization="图书馆",
                value=value,
                unit="人次",
                source_reference="月报",
                reason="原始报表",
            )


@pytest.mark.parametrize(
    "endpoint", ["https://user:secret@example.org", "https://example.org?token=abc", "file:///etc/passwd"]
)
def test_source_registration_rejects_credentials_and_non_http(endpoint):
    with pytest.raises(ValidationError):
        SourceCommand(
            code="source",
            name="资源",
            owner_department="图书馆",
            source_type="api",
            endpoint=endpoint,
            reason="登记依据",
        )


@pytest.mark.parametrize("path", ["//evil.example", "/\\evil.example", "javascript:alert(1)"])
def test_applications_only_accept_same_origin_paths(path):
    with pytest.raises(ValidationError):
        ApplicationCommand(
            code="app", name="应用", owner_department="图书馆", entry_path=path, reason="登记依据"
        )


@dataclass
class Context:
    actor_id: UUID = field(default_factory=lambda: UUID("00000000-0000-4000-8000-000000000001"))
    trace_id: str = "workbench-test"


class NoDatabase:
    @contextmanager
    def transaction(self, actor):
        raise AssertionError("Authorization must happen before reading or writing data")
        yield


def test_read_and_write_routes_require_backend_permissions():
    app = FastAPI()
    permissions = []

    def deny(context, permission):
        permissions.append(permission)
        raise HTTPException(403, "denied")

    register(app, NoDatabase(), Context, lambda: Context(), deny)
    client = TestClient(app)
    assert client.get("/api/v1/knowledge-hub/workbench/sources").status_code == 403
    assert client.get("/api/v1/knowledge-hub/workbench/audit").status_code == 403
    assert (
        client.post(
            "/api/v1/knowledge-hub/workbench/sources",
            json={
                "code": "source",
                "name": "来源",
                "owner_department": "图书馆",
                "source_type": "file",
                "reason": "测试来源登记",
            },
        ).status_code
        == 403
    )
    assert permissions == ["knowledge_hub.read", "knowledge_hub.audit.read", "knowledge_hub.manage"]


class Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        return self.results.pop(0)


def test_no_scope_is_not_reported_as_a_successful_quality_check():
    c = Connection(
        [
            Cursor(
                row={
                    "enabled": True,
                    "rule_definition": {"engine": "publication_completeness_v1", "field": "abstract"},
                    "source_system_id": str(Context().actor_id),
                }
            ),
            Cursor(rows=[]),
            Cursor(row={"id": str(Context().actor_id)}),
        ]
    )
    result = run_rule(c, Context().actor_id, Context().actor_id)
    assert result["state"] == "error"
    assert result["total"] == 0
    assert len(c.calls) == 3


def test_legacy_or_unsafe_rule_is_never_executed():
    c = Connection(
        [Cursor(row={"enabled": True, "rule_definition": {"engine": "sql", "field": "title; DROP TABLE x"}})]
    )
    with pytest.raises(ValueError, match="执行器"):
        run_rule(c, Context().actor_id, Context().actor_id)
    assert len(c.calls) == 1
