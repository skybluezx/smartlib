"""Exercise Skill workflows against HTTP contracts, including uncertain writes."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "skills/smartlib-knowledge-hub/scripts/hub.py"
spec = importlib.util.spec_from_file_location("hub_skill", SCRIPT)
skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill)
ACTOR = "00000000-0000-4000-8000-000000000001"
IDENT = "00000000-0000-4000-8000-000000000002"
PERMS = [
    "knowledge_hub.read",
    "knowledge_hub.manage",
    "publication_intake.submit",
    "publication_verification.read",
    "change.submit",
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("SMARTLIB_HUB_ACTOR_ID", raising=False)
    monkeypatch.delenv("SMARTLIB_HUB_TOKEN", raising=False)
    clients = []

    def make(handler, permissions=PERMS):
        calls = []

        def route(request):
            calls.append(request)
            if request.url.path.endswith("/session"):
                return httpx.Response(200, json={"actor_id": ACTOR, "permissions": permissions})
            response = handler(request)
            return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)

        hub = skill.Hub(
            "http://127.0.0.1:18080", tmp_path, tmp_path / "receipts", transport=httpx.MockTransport(route)
        )
        clients.append(hub)
        return hub, calls

    yield make
    for item in clients:
        item.close()


def args(*values):
    return skill.parser().parse_args(list(values))


def test_library_preview_never_commits_and_apply_stops_on_errors(client, tmp_path):
    path = tmp_path / "读者培训.csv"
    path.write_text("时间,内容\n2025,测试\n")
    hub, calls = client(lambda _: {"id": IDENT, "errors": [{"message": "坏数据"}], "count": 1})
    preview = skill.execute(hub, args("library-import", "--file", str(path), "--mode", "demo"))
    blocked = skill.execute(
        hub, args("library-import", "--file", str(path), "--mode", "demo", "--apply", "--reason", "测试导入")
    )
    assert preview["stage"] == "preview" and blocked["stage"] == "blocked"
    assert all(not r.url.path.endswith("/commit") for r in calls)


def test_library_commit_readback_uses_actual_reused_batch(client):
    other = "00000000-0000-4000-8000-000000000003"

    def handler(request):
        if request.method == "POST":
            return {"id": other, "count": 2, "reused": True}
        return {
            "id": request.url.path.split("/")[-1],
            "count": 2,
            "errors": [],
            "state": "imported",
            "mode": "demo",
        }

    hub, calls = client(handler)
    result = skill.execute(hub, args("library-commit", "--id", IDENT, "--reason", "测试恢复", "--apply"))
    assert result["verification"]["id"] == other
    assert calls[-1].url.path.endswith(other)


def test_permission_denial_sends_no_file(client, tmp_path):
    path = tmp_path / "读者培训.csv"
    path.write_text("时间,内容\n2025,测试\n")
    hub, calls = client(lambda _: pytest.fail("must not upload"), ["knowledge_hub.read"])
    with pytest.raises(skill.WorkflowError, match="权限"):
        skill.execute(hub, args("library-import", "--file", str(path), "--mode", "real", "--apply"))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url", ["http://example.com", "https://a:b@example.com", "https://example.com/path", "file:///tmp/x"]
)
def test_unsafe_service_addresses_rejected(tmp_path, url):
    with pytest.raises(skill.WorkflowError):
        skill.Hub(url, tmp_path, tmp_path)


def test_redirect_does_not_forward_credentials(client):
    hub, calls = client(lambda _: httpx.Response(302, headers={"location": "https://other.example/"}))
    with pytest.raises(skill.ApiError, match="重定向"):
        hub.request("GET", "/api/v1/knowledge-hub/overview")
    assert len(calls) == 1


def test_requested_actor_mismatch_stops(client, monkeypatch):
    monkeypatch.setenv("SMARTLIB_HUB_ACTOR_ID", IDENT)
    hub, _ = client(lambda _: {})
    with pytest.raises(skill.WorkflowError, match="身份不符"):
        hub.authenticate()


def test_unknown_mutation_not_retried_and_state_is_private(client):
    hub, _ = client(lambda _: {})
    writes = []

    def write():
        writes.append(1)
        raise skill.WorkflowError("timeout")

    with pytest.raises(skill.WorkflowError, match="timeout"):
        hub.mutation("test", {"file": "x"}, write, lambda x: x)
    with pytest.raises(skill.WorkflowError, match="禁止重复"):
        hub.mutation("test", {"file": "x"}, write, lambda x: x)
    assert len(writes) == 1
    path = next(hub.state_dir.glob("*.json"))
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["status"] == "unknown"


def test_received_write_response_is_reused_after_failed_readback(client):
    hub, _ = client(lambda _: {})
    writes = []

    def write():
        writes.append(1)
        return {"id": IDENT}

    def failed_verify(_):
        raise skill.WorkflowError("readback unavailable")

    with pytest.raises(skill.WorkflowError):
        hub.mutation("test", {"same": "input"}, write, failed_verify)
    result = hub.mutation("test", {"same": "input"}, write, lambda x: x)
    assert result["receipt_reused"] and writes == [1]


def test_explicit_rejection_can_retry_but_server_error_cannot(client):
    hub, _ = client(lambda _: {})
    for status, allowed in [(422, True), (500, False)]:

        def fail(status=status):
            raise skill.ApiError(status, "failed")

        with pytest.raises(skill.ApiError):
            hub.mutation("reject", status, fail, lambda x: x)
        if allowed:
            assert hub.mutation("reject", status, lambda: {"ok": True}, lambda x: x)["verification"]["ok"]
        else:
            with pytest.raises(skill.WorkflowError, match="禁止重复"):
                hub.mutation("reject", status, lambda: {}, lambda x: x)


def test_pagination_reads_all_pages_and_refuses_drift(client):
    def stable(req):
        return {"items": [{"id": str(req.url.params["page"])}], "total": 3}

    hub, _ = client(stable)
    assert hub.pages("/records")["total"] == 3
    hub, _ = client(lambda r: {"items": [{"id": "one"}], "total": 3 if r.url.params["page"] == "1" else 4})
    with pytest.raises(skill.WorkflowError, match="总数发生变化"):
        hub.pages("/records")


def test_publication_missing_identifiers_allowed_but_not_approved(tmp_path):
    path = tmp_path / "publications.csv"
    result = skill.publication_preflight(path, "题名,年份,DOI,作者\n甲,2025,10.1/a,A;B\n乙,,,\n".encode())
    assert result["accepted_count"] == 2 and result["manual_review_count"] == 1
    assert result["automatic_eligible_count"] == 1


@pytest.mark.parametrize(
    "content",
    [
        "title,题名\na,b\n",
        "title\na,extra\n",
        "title,year\na,2025.8\n",
        "title,doi\na,10.1/test\nb,https://doi.org/10.1/test\n",
        "title,doi\na,\na,\n",
        "title,,year\na,hidden,2025\n",
        "title,year\na,2025\n,2024\n",
    ],
)
def test_publication_preflight_blocks_loss_and_bad_rows(tmp_path, content):
    with pytest.raises((skill.WorkflowError, ValueError)):
        skill.publication_preflight(tmp_path / "x.csv", content.encode())


def test_publication_import_verifies_every_record_and_deduplicates_renamed_file(client, tmp_path):
    path = tmp_path / "论文.csv"
    path.write_text("title\n测试论文\n")
    batch = "00000000-0000-4000-8000-000000000003"

    def handler(request):
        if request.method == "POST":
            return {
                "batch_id": batch,
                "accepted_count": 1,
                "items": [{"record_id": IDENT, "title": "测试论文"}],
            }
        return {"record_id": IDENT, "batch_id": batch, "normalized_payload": {"title": "测试论文"}}

    hub, calls = client(handler)
    result = skill.execute(
        hub, args("publication-import", "--file", str(path), "--source-label", "证据", "--apply")
    )
    new_path = path.with_name("另一个名字.csv")
    new_path.write_bytes(path.read_bytes())
    repeated = skill.execute(
        hub, args("publication-import", "--file", str(new_path), "--source-label", "改名来源", "--apply")
    )
    assert result["verification"]["read_back_count"] == 1 and repeated["receipt_reused"]
    assert sum(r.method == "POST" for r in calls) == 1


def test_stale_library_revision_never_posts(client, tmp_path):
    patch = tmp_path / "patch.json"
    patch.write_text('{"听众人数":"42"}')
    hub, calls = client(lambda _: {"version": 2})
    with pytest.raises(skill.WorkflowError, match="版本已变化"):
        skill.execute(
            hub,
            args(
                "library-revise",
                "--id",
                IDENT,
                "--base-version",
                "1",
                "--patch",
                str(patch),
                "--reason",
                "测试原因",
                "--apply",
            ),
        )
    assert not any(r.method == "POST" for r in calls)


def test_library_revision_preserves_fields_mode_and_history(client, tmp_path):
    patch = tmp_path / "patch.json"
    patch.write_text('{"听众人数":"42"}')
    row = {
        "id": IDENT,
        "version": 1,
        "mode": "demo",
        "category": "reader_training",
        "state": "active",
        "fields": {"内容": "测试", "听众人数": "12"},
        "history": [{"version": 1}],
    }

    def handler(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["fields"] == {"内容": "测试", "听众人数": "42"}
            assert payload["mode"] == "demo" and payload["state"] == "active"
            row.update(version=2, fields=payload["fields"], history=[{"version": 2}, {"version": 1}])
        return row

    hub, calls = client(handler)
    command = args(
        "library-revise",
        "--id",
        IDENT,
        "--base-version",
        "1",
        "--patch",
        str(patch),
        "--reason",
        "测试原因",
        "--apply",
    )
    skill.execute(hub, command)
    assert skill.execute(hub, command)["receipt_reused"]
    assert sum(r.method == "POST" for r in calls) == 1


def test_analysis_scope_validates_unknown_and_conflicting_parameters(tmp_path):
    path = tmp_path / "scope.json"
    for payload in [
        {"typo_year": 2026},
        {"graph_query": "g.V()", "custom_scope_id": IDENT},
        {"start_year": 2026, "end_year": 2020},
        {"institution_settings": {"typo": "internal"}},
    ]:
        path.write_text(json.dumps(payload))
        with pytest.raises((ValueError, skill.WorkflowError)):
            skill.definition(path)


def test_scope_filters_forwarded_without_changing_denominator(client, tmp_path):
    path = tmp_path / "scope.json"
    path.write_text(
        json.dumps(
            {
                "start_year": 2024,
                "end_year": 2026,
                "organization_ids": [IDENT],
                "people_include_external": False,
                "custom_scope_id": IDENT,
            }
        )
    )
    hub, calls = client(lambda _: {"scope": {"publication_count": 269}, "coverage": {}})
    skill.execute(hub, args("analyze", "--definition", str(path), "--module", "people_collaboration"))
    query = calls[-1].url.params
    assert query["organization_ids"] == IDENT and query["custom_scope_id"] == IDENT
    assert query["selected_module"] == "people_collaboration" and query["people_include_external"] == "false"
    assert query["start_year"] == "2024"


def test_snapshot_report_uses_readback_not_preview(client):
    def handler(request):
        if request.method == "POST":
            return {"analysis_id": IDENT, "kind": "snapshot", "name": "测试快照"}
        return {
            "analysis_id": IDENT,
            "kind": "snapshot",
            "name": "测试快照",
            "result_hash": "serverhash",
            "result": {"scope": {"publication_count": 3}},
        }

    hub, calls = client(handler)
    result = skill.execute(
        hub,
        args("analysis-save", "--name", "测试快照", "--kind", "snapshot", "--run-key", "check", "--apply"),
    )
    assert result["verification"]["result_hash"] == "serverhash"
    assert result["verification"]["result"]["scope"]["publication_count"] == 3
    assert not any(r.url.path.endswith("/analytics") for r in calls)


def test_quality_run_is_not_silent_repair(client):
    def handler(request):
        if request.method == "POST":
            return {"id": IDENT, "state": "failed", "missing": 3, "total": 10}
        return [{"id": IDENT, "run_state": "failed"}]

    hub, calls = client(handler)
    result = skill.execute(
        hub, args("quality-run", "--id", IDENT, "--run-key", "test", "--reason", "检查缺项", "--apply")
    )
    assert result["verification"]["state"] == "failed"
    assert sum(r.method == "POST" for r in calls) == 1


def test_proposal_does_not_accept_or_publish(client, tmp_path):
    payload = {
        "context_object_id": IDENT,
        "source_label": "证据",
        "reason": "测试修正",
        "proposals": [
            {
                "target_kind": "object",
                "target_id": IDENT,
                "field_path": "canonical_name",
                "proposed_value": "修正名",
                "base_version": 2,
            }
        ],
    }
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(payload))
    hub, calls = client(lambda _: {"submission_id": IDENT, "status": "needs_review"})
    result = skill.execute(hub, args("change-submit", "--file", str(path), "--apply"))
    assert result["verification"]["status"] == "needs_review"
    assert [r.url.path for r in calls if r.method == "POST"] == ["/api/v1/changes"]


def test_local_validation_failure_not_reported_as_uncertain_write(client, tmp_path):
    patch = tmp_path / "patch.json"
    patch.write_text('{"听众人数":"42"}')
    hub, _ = client(lambda _: {"version": 2})
    command = args(
        "library-revise",
        "--id",
        IDENT,
        "--base-version",
        "1",
        "--patch",
        str(patch),
        "--reason",
        "测试原因",
        "--apply",
    )
    for _ in range(2):
        with pytest.raises(skill.BeforeWriteError, match="版本已变化"):
            skill.execute(hub, command)
    state = json.loads(next(hub.state_dir.glob("*.json")).read_text())
    assert state["status"] == "rejected"


def test_unknown_write_keeps_trace_for_server_reconciliation(client):
    def disconnected(request):
        raise httpx.ReadTimeout("network", request=request)

    hub, _ = client(disconnected)
    with pytest.raises(skill.WorkflowError):
        hub.mutation(
            "network", {"file": "digest"}, lambda: hub.request("POST", "/write", json={}), lambda x: x
        )
    saved = json.loads(next(hub.state_dir.glob("*.json")).read_text())
    assert saved["request_trace_id"] == hub.traces[-1]["trace_id"]
    assert hub.traces[-1]["status"] == "unknown"


def test_register_rule_checks_schema_and_reads_back(client, tmp_path):
    payload = {
        "data_asset_id": IDENT,
        "code": "test.abstract",
        "name": "摘要完整性",
        "field": "abstract",
        "reason": "测试登记",
    }
    path = tmp_path / "rule.json"
    path.write_text(json.dumps(payload))

    def handler(req):
        if req.method == "POST":
            return {"id": IDENT}
        return {"items": [{"id": IDENT, "code": payload["code"]}], "total": 1}

    hub, calls = client(handler)
    assert skill.execute(hub, args("register", "--kind", "rules", "--file", str(path)))["stage"] == "planned"
    assert not any(r.method == "POST" for r in calls)
    result = skill.execute(hub, args("register", "--kind", "rules", "--file", str(path), "--apply"))
    assert result["verification"]["code"] == "test.abstract"


def test_xlsx_preflight_matches_backend_and_rejects_formulas(tmp_path):
    import io
    import zipfile

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relns = "http://schemas.openxmlformats.org/package/2006/relationships"

    def workbook(formula):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            z.writestr(
                "xl/workbook.xml",
                f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="论文" sheetId="1" r:id="a"/><sheet name="备注" sheetId="2" r:id="b"/></sheets></workbook>',
            )
            z.writestr(
                "xl/_rels/workbook.xml.rels",
                f'<Relationships xmlns="{relns}"><Relationship Id="a" Target="worksheets/sheet1.xml"/><Relationship Id="b" Target="worksheets/sheet2.xml"/></Relationships>',
            )
            z.writestr(
                "xl/worksheets/sheet1.xml",
                f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>title</t></is></c><c r="B1" t="inlineStr"><is><t>year</t></is></c></row><row r="2"><c r="A2"><v>123.0</v></c><c r="B2">'
                + ("<f>2025</f>" if formula else "")
                + "<v>2025</v></c></row></sheetData></worksheet>",
            )
        return stream.getvalue()

    result = skill.publication_preflight(tmp_path / "data.xlsx", workbook(False))
    assert result["items"][0]["title"] == "123"
    with pytest.raises(skill.WorkflowError, match="公式"):
        skill.publication_preflight(tmp_path / "data.xlsx", workbook(True))


def test_read_only_network_failure_does_not_suggest_unknown_business_write(client):
    def disconnected(request):
        raise httpx.ConnectError("network", request=request)

    hub, _ = client(disconnected)
    with pytest.raises(skill.WorkflowError) as caught:
        hub.request("GET", "/read")
    assert "只读查询" in str(caught.value) and "写请求结果可能未知" not in str(caught.value)
