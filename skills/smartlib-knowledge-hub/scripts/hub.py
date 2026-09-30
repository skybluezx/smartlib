"""Allowlisted SmartLib workflows. Run using the target project's Python environment."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import posixpath
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

ROOT = Path(
    os.environ.get(
        "SMARTLIB_PROJECT_ROOT", "/Users/zhaixiao/Workplace/smartlib_knowledge_platform"
    )
)
HUB = "/api/v1/knowledge-hub"
LIB = HUB + "/library-work"
GRAPH = "/api/v1/scholar-graph"
MAX_UPLOAD = 20 * 1024 * 1024
MODULES = [
    "journals",
    "funding",
    "disciplines",
    "people_collaboration",
    "institution_collaboration",
]
SECTIONS = [
    "sources",
    "domains",
    "resources",
    "licenses",
    "rules",
    "governance",
    "metadata",
    "library",
    "applications",
    "settings",
    "jobs",
    "audit",
    "access",
    "journals",
]


class WorkflowError(Exception):
    pass


class ApiError(WorkflowError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(f"HTTP {status}: {detail}")


class BeforeWriteError(WorkflowError):
    """Local validation failed before a mutation was sent."""


def now():
    return datetime.now(UTC).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else canonical(value).encode()
    ).hexdigest()


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".receipt-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, indent=2)
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def uuid_text(value):
    return str(UUID(value))


def strict_model(model, value):
    if not isinstance(value, dict) or set(value) - set(model.model_fields):
        raise WorkflowError("存在未知字段或 JSON 不是对象；请先核查当前接口模型")
    return model.model_validate(value).model_dump(mode="json", exclude_none=True)


class Hub:
    def __init__(self, base_url, project, output, *, transport=None):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise WorkflowError("服务地址必须是无凭据、无路径的 HTTP(S) origin")
        if parsed.scheme == "http" and parsed.hostname not in (
            "127.0.0.1",
            "localhost",
            "::1",
        ):
            raise WorkflowError("远端服务必须使用 HTTPS；不能明文传输业务数据或凭据")
        self.base = base_url.rstrip("/")
        self.project, self.output = Path(project), Path(output)
        # State does not move when the user chooses a different report output directory.
        self.state_dir = self.project / "outputs/knowledge-hub-skill/state"
        self.session = None
        self.traces = []
        self.active_receipt = None
        headers = {}
        token, actor = (
            os.environ.get("SMARTLIB_HUB_TOKEN"),
            os.environ.get("SMARTLIB_HUB_ACTOR_ID"),
        )
        if token:
            headers["Authorization"] = "Bearer " + token
        if actor:
            headers["X-Smartlib-Actor-Id"] = uuid_text(actor)
        self.requested_actor = actor
        self.client = httpx.Client(
            base_url=self.base,
            headers=headers,
            timeout=180,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def request(self, method, path, **kwargs):
        trace = str(uuid4())
        trace_record = {
            "method": method,
            "path": path,
            "status": "pending",
            "trace_id": trace,
        }
        self.traces.append(trace_record)
        if self.active_receipt and method != "GET":
            pending = read_json(self.active_receipt)
            pending["request_trace_id"] = trace
            private_write(self.active_receipt, pending)
        try:
            response = self.client.request(
                method, path, headers={"X-Trace-Id": trace}, **kwargs
            )
        except httpx.RequestError as exc:
            trace_record["status"] = "unknown"
            impact = (
                "本次为只读查询；请检查本地服务和网络执行权限"
                if method == "GET"
                else "写请求结果可能未知，请查看状态回执"
            )
            raise WorkflowError(
                f"连接失败或超时（{type(exc).__name__}）；{impact}"
            ) from exc
        trace_record.update(
            status=response.status_code,
            trace_id=response.headers.get("x-trace-id", trace),
        )
        if response.is_redirect:
            raise ApiError(response.status_code, "禁止重定向；核实服务地址后再操作")
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError(
                response.status_code, "接口未返回 JSON；可能地址或部署版本不匹配"
            ) from exc
        if not response.is_success:
            raise ApiError(
                response.status_code,
                data.get("detail", "请求失败")
                if isinstance(data, dict)
                else "请求失败",
            )
        return data

    def authenticate(self):
        if self.session is None:
            self.session = self.request("GET", HUB + "/session")
            if not self.session.get("actor_id") or not isinstance(
                self.session.get("permissions"), list
            ):
                raise WorkflowError("身份接口返回不完整，停止执行")
            if (
                self.requested_actor
                and uuid_text(self.requested_actor) != self.session["actor_id"]
            ):
                raise WorkflowError(
                    "服务端实际身份与指定身份不符，停止执行；不要绕过代理身份配置"
                )
        return self.session

    def require(self, *permissions):
        actual = self.authenticate()["permissions"]
        missing = sorted(set(permissions) - set(actual))
        if missing:
            raise WorkflowError("当前身份缺少权限：" + ", ".join(missing))

    def pages(self, path, params=None):
        items, page, expected = [], 1, None
        while True:
            result = self.request("GET", path, params={**(params or {}), "page": page})
            if (
                not isinstance(result, dict)
                or not isinstance(result.get("items"), list)
                or "total" not in result
            ):
                raise WorkflowError("分页接口契约不匹配，不能宣称读取完整")
            if expected is not None and expected != result["total"]:
                raise WorkflowError(
                    "分页过程中总数发生变化，请重新读取；本次不作为完整导出"
                )
            expected = result["total"]
            rows = result["items"]
            items.extend(rows)
            if len(items) == expected:
                break
            if not rows or len(items) > expected or page > 10000:
                raise WorkflowError("分页不完整或重复，请检查接口")
            page += 1
        ids = [row.get("id", row.get("record_id")) for row in items]
        if all(ids) and len(set(ids)) != len(ids):
            raise WorkflowError("分页中出现重复 ID，当前数据可能变化，请重读")
        return {"items": items, "total": expected, "pages": page}

    def mutation(self, operation, identity, write, verify):
        """No automatic replay of a possibly committed non-idempotent write."""
        actor = self.authenticate()["actor_id"]
        key = digest([self.base, actor, operation, identity])
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_dir / (key + ".json")
        lock_fd = os.open(
            self.state_dir / (key + ".lock"), os.O_CREAT | os.O_RDWR, 0o600
        )
        with os.fdopen(lock_fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            previous = read_json(path) if path.exists() else None
            if previous and previous["status"] in ("pending", "unknown"):
                raise WorkflowError(
                    f"上次写入结果未知，禁止重复提交。先查系统批次/审计：{path}"
                )
            reused = bool(previous and "response" in previous)
            if reused:
                response = previous["response"]
            else:
                previous = {
                    "operation": operation,
                    "identity_hash": digest(identity),
                    "target": self.base,
                    "actor_id": actor,
                    "started_at": now(),
                    "status": "pending",
                }
                private_write(path, previous)
                try:
                    self.active_receipt = path
                    response = write()
                except Exception as exc:
                    # Only explicit, ordinary client rejections permit a fresh attempt.
                    certain = isinstance(exc, BeforeWriteError) or (
                        isinstance(exc, ApiError)
                        and exc.status
                        in (
                            400,
                            401,
                            403,
                            404,
                            409,
                            413,
                            415,
                            422,
                        )
                    )
                    previous = read_json(path)
                    previous["status"] = "rejected" if certain else "unknown"
                    private_write(path, previous)
                    raise
                finally:
                    self.active_receipt = None
                previous = read_json(path)
                previous.update(status="write_succeeded", response=response)
                private_write(path, previous)
            verified = verify(response)
            previous.update(status="complete", verified_at=now())
            private_write(path, previous)
            return {
                "response": response,
                "verification": verified,
                "receipt_reused": reused,
                "operation_receipt": str(path),
            }

    def close(self):
        self.client.close()


def load_upload(path, suffixes):
    path = Path(path).resolve()
    if path.suffix.lower() not in suffixes or path.stat().st_size > MAX_UPLOAD:
        raise WorkflowError("文件类型不支持或超过20 MB")
    data = path.read_bytes()
    if not data or len(data) > MAX_UPLOAD:
        raise WorkflowError("文件为空或超过20 MB")
    return path, data


def publication_preflight(path, data):
    from smartlib_platform.library_work.parser import safe_zip, xml
    from smartlib_platform.publications.intake import (
        FIELD_ALIASES,
        automatic_eligibility,
        records_from_rows,
        records_from_xlsx,
    )

    if path.suffix.lower() == ".csv":
        matrix = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    else:
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with safe_zip(data) as archive:
            book = xml(archive.read("xl/workbook.xml"))
            sheet = book.find("s:sheets/s:sheet", ns)
            if sheet is None:
                raise WorkflowError("XLSX 没有工作表")
            rel_id = sheet.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            )
            relations = xml(archive.read("xl/_rels/workbook.xml.rels"))
            rel = next(
                (
                    r
                    for r in relations
                    if r.get("Id") == rel_id and r.get("TargetMode") != "External"
                ),
                None,
            )
            if rel is None:
                raise WorkflowError("无法定位论文首个工作表")
            target = rel.get("Target", "")
            target = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath("xl/" + target)
            )
            if not target.startswith("xl/"):
                raise WorkflowError("工作表路径不安全")
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared = [
                    "".join(node.itertext())
                    for node in xml(archive.read("xl/sharedStrings.xml")).findall(
                        "s:si", ns
                    )
                ]
            matrix = []
            root = xml(archive.read(target))
            if root.findall(".//s:f", ns):
                raise WorkflowError("论文工作表含公式；请先另存已核对的纯值副本")
            for row in root.findall(".//s:row", ns):
                values = {}
                for cell in row.findall("s:c", ns):
                    match = re.match(r"[A-Z]+", cell.get("r", "A1"))
                    if not match:
                        raise WorkflowError("工作表单元格坐标无效")
                    index = 0
                    for char in match.group():
                        index = index * 26 + ord(char) - 64
                    if index > 1000 or index in values:
                        raise WorkflowError("工作表列数超限或坐标重复")
                    value = cell.find("s:v", ns)
                    raw = value.text if value is not None else ""
                    if cell.get("t") == "s":
                        raw = shared[int(raw)] if raw else ""
                    elif cell.get("t") == "inlineStr":
                        raw = "".join(cell.itertext())
                    values[index] = raw
                if values:
                    matrix.append(
                        [values.get(index, "") for index in range(1, max(values) + 1)]
                    )
    if not matrix or len(matrix) > 5001:
        raise WorkflowError("空文件或超过5000数据行")
    aliases = {
        a.casefold(): name for name, variants in FIELD_ALIASES.items() for a in variants
    }
    headers = [h.strip() for h in matrix[0]]
    canonical_headers = [aliases.get(h.casefold(), h.casefold()) for h in headers if h]
    if len(canonical_headers) != len(set(canonical_headers)):
        raise WorkflowError("同义字段或列名重复，不能静默覆盖")
    rows = []
    for number, row in enumerate(matrix[1:], 2):
        if len(row) > len(headers) and any(row[len(headers) :]):
            raise WorkflowError(f"第{number}行存在表头以外的数据")
        if any(value and not headers[i] for i, value in enumerate(row[: len(headers)])):
            raise WorkflowError(f"第{number}行存在无标题列数据")
        mapped = dict(zip(headers, row, strict=False))
        for key, value in mapped.items():
            if (
                aliases.get(key.casefold()) == "publication_year"
                and value.strip()
                and not re.fullmatch(r"\d{4}(?:\.0+)?", value.strip())
            ):
                raise WorkflowError(f"第{number}行年份必须为整数，不能截断或猜测")
        rows.append(mapped)
    records = records_from_rows(rows)
    if path.suffix.lower() == ".xlsx":
        # Use precisely the same numeric and cell interpretation as the server,
        # after the bounded archive/header/formula checks above.
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as temporary:
            temporary.write(data)
            temporary.flush()
            records = records_from_xlsx(Path(temporary.name))
    seen, seen_dois = set(), set()
    for record in records:
        item_hash = digest(record.model_dump(mode="json"))
        if item_hash in seen or (record.doi and record.doi in seen_dois):
            raise WorkflowError("文件中有完全重复记录或重复 DOI，请先核对")
        seen.add(item_hash)
        if record.doi:
            seen_dois.add(record.doi)
    eligibility = [automatic_eligibility(record) for record in records]
    return {
        "accepted_count": len(records),
        "automatic_eligible_count": sum(ok for ok, _ in eligibility),
        "manual_review_count": sum(not ok for ok, _ in eligibility),
        "sha256": digest(data),
        "columns": headers,
        "items": [
            {"title": record.title, "eligibility_reasons": reasons}
            for record, (_, reasons) in zip(records, eligibility, strict=True)
        ],
        "note": "预检未入库；自动核验资格不代表核验通过或发布",
    }


def definition(path):
    from smartlib_platform.graph_analytics.models import (
        AnalysisDefinition,
        InstitutionAnalysisSettings,
    )

    value = read_json(path) if path else {}
    if value.get("graph_query") and value.get("custom_scope_id"):
        raise WorkflowError("图查询和已保存范围不能同时使用")
    if "institution_settings" in value:
        strict_model(InstitutionAnalysisSettings, value["institution_settings"])
        for group in value["institution_settings"].get("groups", []):
            if set(group) - {"name", "member_ids"}:
                raise WorkflowError("机构组合存在未知字段")
    return strict_model(AnalysisDefinition, value)


def analyze(hub, scope, module):
    # These settings affect result formation; accepting and dropping them would be misleading.
    if scope.get("workspace_settings") or scope.get("comparison"):
        raise WorkflowError(
            "当前即时分析接口不接受工作台展示/比较设置；需要保留这些设置时请保存快照"
        )
    params = {
        key: val
        for key, val in scope.items()
        if key
        in {
            "start_year",
            "end_year",
            "project_kind_ids",
            "organization_ids",
            "scholar_ids",
            "custom_scope_id",
            "minimum_publication_count",
            "edge_limit",
            "people_focus_id",
            "people_organization_id",
            "people_include_external",
        }
    }
    params["institution_settings"] = canonical(scope["institution_settings"])
    if module:
        params["selected_module"] = module
    if scope.get("graph_query"):
        return hub.request(
            "POST",
            GRAPH + "/analytics/custom",
            json={**params, "graph_query": scope["graph_query"]},
        )
    return hub.request("GET", GRAPH + "/analytics", params=params)


def library_filters(args):
    return {
        key: getattr(args, key)
        for key in ("mode", "category", "year", "department", "q")
        if getattr(args, key, None) not in ("", None)
    }


def commit_library(hub, batch_id, reason):
    if not reason or len(reason.strip()) < 3:
        raise WorkflowError("提交须提供至少3字的业务原因")
    preview = hub.request("GET", LIB + "/batches/" + batch_id)
    if preview["errors"] or not preview["count"]:
        raise WorkflowError("预检有阻断错误或无有效事项，不能提交")
    response = hub.request(
        "POST",
        LIB + "/batches/" + batch_id + "/commit",
        json={"confirm": True, "reason": reason},
    )
    actual = hub.request("GET", LIB + "/batches/" + str(response["id"]))
    if (
        actual["state"] != "imported"
        or actual["count"] != response["count"]
        or actual["count"] != preview["count"]
        or actual["mode"] != preview["mode"]
    ):
        raise WorkflowError("提交后的批次回读不一致，不能报告入库成功")
    return {
        "response": response,
        "verification": {
            "id": actual["id"],
            "state": actual["state"],
            "count": actual["count"],
            "mode": actual["mode"],
        },
    }


def execute(hub, args):
    command = args.command
    hub.authenticate()
    if command == "status":
        hub.require("knowledge_hub.read")
        return {
            "session": hub.session,
            "overview": hub.request("GET", HUB + "/overview"),
        }
    read_paths = {
        "library-catalog": LIB + "/catalog",
        "hub-options": HUB + "/workbench/options",
        "analysis-options": GRAPH + "/analytics/scope-options",
        "scopes": GRAPH + "/analytics/custom-scopes",
        "analyses": GRAPH + "/analyses",
    }
    if command in read_paths:
        hub.require("knowledge_hub.read")
        return hub.request("GET", read_paths[command])
    details = {
        "library-detail": LIB + "/records/",
        "publication-detail": "/api/v1/publications/intake/",
        "analysis-detail": GRAPH + "/analyses/",
        "change-detail": "/api/v1/changes/",
    }
    if command in details:
        hub.require(
            "publication_verification.read"
            if command == "publication-detail"
            else "knowledge_hub.read"
        )
        return hub.request("GET", details[command] + args.id)
    if command in ("library-list", "library-report"):
        hub.require("knowledge_hub.read")
        params = library_filters(args)
        if command == "library-list":
            return hub.pages(LIB + "/records", params)
        return {
            "filters": params,
            **hub.request("GET", LIB + "/overview", params=params),
        }
    if command == "hub-list":
        hub.require(
            "knowledge_hub.audit.read"
            if args.section == "audit"
            else "knowledge_hub.read"
        )
        return hub.pages(
            HUB + "/workbench/" + args.section, {"q": args.q, "page_size": 100}
        )
    if command == "publication-list":
        hub.require("publication_verification.read")
        return hub.pages(
            "/api/v1/publications/intake", {"query": args.q, "page_size": 100}
        )
    if command == "register":
        from smartlib_platform.knowledge_hub.models import (
            AssetCommand,
            DomainCommand,
            RuleCommand,
            SourceCommand,
        )

        models = {
            "sources": SourceCommand,
            "domains": DomainCommand,
            "resources": AssetCommand,
            "rules": RuleCommand,
        }
        hub.require("knowledge_hub.manage", "knowledge_hub.read")
        payload = strict_model(models[args.kind], read_json(args.file))
        if not args.apply:
            return {"stage": "planned", "payload": payload}

        def verify_registration(response):
            matches = hub.pages(
                HUB + "/workbench/" + args.kind,
                {"q": payload["code"], "page_size": 100},
            )
            row = next((r for r in matches["items"] if r["id"] == response["id"]), None)
            if not row or row["code"] != payload["code"]:
                raise WorkflowError("登记结果无法从工作台回读")
            return row

        return hub.mutation(
            "register-" + args.kind,
            payload,
            lambda: hub.request("POST", HUB + "/workbench/" + args.kind, json=payload),
            verify_registration,
        )
    if command == "library-import":
        hub.require("knowledge_hub.manage", "knowledge_hub.read")
        path, data = load_upload(args.file, {".csv", ".xlsx", ".zip"})
        preview = hub.request(
            "POST",
            LIB + "/preview",
            data={"mode": args.mode, "category": args.category},
            files={"file": (path.name, data, "application/octet-stream")},
        )
        result = {"file_sha256": digest(data), "preview": preview, "stage": "preview"}
        if args.apply:
            if preview["errors"] or not preview["count"]:
                # Preserve structured diagnostics and batch ID in the receipt.
                result["stage"] = "blocked"
            else:
                result.update(
                    commit_library(hub, str(preview["id"]), args.reason),
                    stage="imported",
                )
        return result
    if command == "library-commit":
        hub.require("knowledge_hub.manage", "knowledge_hub.read")
        if not args.apply:
            return {
                "stage": "preview",
                "preview": hub.request("GET", LIB + "/batches/" + args.id),
            }
        return commit_library(hub, args.id, args.reason)
    if command in ("publication-preview", "publication-import"):
        path, data = load_upload(args.file, {".csv", ".xlsx"})
        preview = publication_preflight(path, data)
        if command == "publication-preview" or not args.apply:
            return preview
        hub.require("publication_intake.submit", "publication_verification.read")
        if not args.source_label or len(args.source_label) > 500:
            raise WorkflowError("论文导入必须有明确来源名称，最多500字")

        def verify_publications(response):
            items = response["items"]
            if (
                response["accepted_count"] != preview["accepted_count"]
                or len(items) != preview["accepted_count"]
            ):
                raise WorkflowError("服务端接受数量与预检不一致")
            checked = []
            for item in items:
                detail = hub.request(
                    "GET", "/api/v1/publications/intake/" + item["record_id"]
                )
                if (
                    detail.get("record_id") != item["record_id"]
                    or detail.get("batch_id") != response["batch_id"]
                    or detail.get("normalized_payload", {}).get("title")
                    != item["title"]
                ):
                    raise WorkflowError("论文入库回读 ID 或题名不符")
                checked.append(item["record_id"])
            if len(set(checked)) != len(checked):
                raise WorkflowError("返回重复采集记录 ID")
            return {
                "batch_id": response["batch_id"],
                "read_back_count": len(checked),
                "note": "已进入采集队列，不代表核验通过或正式发布",
            }

        result = hub.mutation(
            "publication-import",
            {"sha256": digest(data)},
            lambda: hub.request(
                "POST",
                "/api/v1/ingestion/publications/file",
                data={"source_label": args.source_label},
                files={"file": (path.name, data, "application/octet-stream")},
            ),
            verify_publications,
        )
        return {"preview": preview, **result}
    if command == "library-revise":
        hub.require("knowledge_hub.manage", "knowledge_hub.read")
        patch = read_json(args.patch)
        if (
            not isinstance(patch, dict)
            or not patch
            or not all(isinstance(v, str) for v in patch.values())
        ):
            raise WorkflowError("修订补丁必须是非空的字段到字符串对象")
        identity = {
            "id": args.id,
            "version": args.base_version,
            "patch": patch,
            "reason": args.reason,
        }

        def prepare():
            from smartlib_platform.library_work.models import WorkRevision

            old = hub.request("GET", LIB + "/records/" + args.id)
            if old["version"] != args.base_version:
                raise BeforeWriteError("记录版本已变化，先重新核对依据，不能覆盖")
            if set(patch) - set(old["fields"]):
                raise BeforeWriteError("补丁存在当前记录中不存在的字段")
            payload = {
                "category": old["category"],
                "mode": old["mode"],
                "state": old["state"],
                "base_version": args.base_version,
                "fields": {**old["fields"], **patch},
                "reason": args.reason,
            }
            try:
                return strict_model(WorkRevision, payload)
            except ValueError as exc:
                raise BeforeWriteError(str(exc)) from exc

        def verify_revision(response):
            actual = hub.request("GET", LIB + "/records/" + args.id)
            versions = {r["version"] for r in actual.get("history", [])}
            if (
                response["version"] != args.base_version + 1
                or response["version"] not in versions
            ):
                raise WorkflowError("未找到提交版本的修订历史")
            if any(
                response["fields"].get(key) != value.strip()
                for key, value in patch.items()
            ):
                raise WorkflowError("提交结果与补丁不一致")
            return {
                "id": args.id,
                "submitted_version": response["version"],
                "current_version": actual["version"],
            }

        if not args.apply:
            return {"stage": "planned", "payload": prepare()}
        return hub.mutation(
            "library-revise",
            identity,
            lambda: hub.request(
                "POST", LIB + "/records/" + args.id + "/revision", json=prepare()
            ),
            verify_revision,
        )
    if command == "quality-run":
        hub.require("knowledge_hub.manage", "knowledge_hub.read")
        if not args.apply:
            return {"stage": "planned", "rule_id": args.id, "reason": args.reason}

        def verify_run(response):
            rows = hub.request("GET", HUB + "/quality-runs/" + args.id)
            if not any(
                str(r.get("id", r.get("run_id"))) == str(response["id"]) for r in rows
            ):
                raise WorkflowError("未能从检查历史回读此轮结果")
            return {
                "id": response["id"],
                "state": response["state"],
                "note": "检查已执行，不表示数据通过或已修复",
            }

        return hub.mutation(
            "quality-run",
            {"id": args.id, "run_key": args.run_key},
            lambda: hub.request(
                "POST",
                HUB + "/workbench/rules/" + args.id + "/run",
                json={"reason": args.reason},
            ),
            verify_run,
        )
    if command == "change-submit":
        from smartlib_platform.changes.service import ProposalInput, SubmissionInput

        hub.require("change.submit")
        payload = read_json(args.file)
        for proposal in payload.get("proposals", []):
            strict_model(ProposalInput, proposal)
        payload = strict_model(SubmissionInput, payload)
        if not args.apply:
            return {"stage": "planned", "payload": payload}
        return hub.mutation(
            "change-submit",
            payload,
            lambda: hub.request("POST", "/api/v1/changes", json=payload),
            lambda response: hub.request(
                "GET", "/api/v1/changes/" + response["submission_id"]
            ),
        )
    if command in ("analyze", "analysis-save"):
        hub.require("knowledge_hub.read")
        scope = definition(args.definition)
        if command == "analyze":
            return {"definition": scope, "result": analyze(hub, scope, args.module)}
        from smartlib_platform.graph_analytics.models import AnalysisSaveCommand

        payload = strict_model(
            AnalysisSaveCommand,
            {"name": args.name, "kind": args.kind, "definition": scope},
        )
        if not args.apply:
            return {"stage": "planned", "payload": payload}

        def verify_analysis(response):
            detail = hub.request("GET", GRAPH + "/analyses/" + response["analysis_id"])
            if detail["kind"] != args.kind or detail["name"] != args.name:
                raise WorkflowError("分析记录回读不一致")
            if args.kind == "snapshot" and (
                not detail.get("result") or not detail.get("result_hash")
            ):
                raise WorkflowError("快照缺少结果或结果摘要")
            return detail

        return hub.mutation(
            "analysis-save",
            {"run_key": args.run_key, "payload": payload},
            lambda: hub.request("POST", GRAPH + "/analyses", json=payload),
            verify_analysis,
        )
    raise WorkflowError("未实现的工作流")


def short_result(result):
    if isinstance(result, list):
        return {"items": len(result)}
    keys = [
        "stage",
        "summary",
        "total",
        "accepted_count",
        "automatic_eligible_count",
        "manual_review_count",
        "analysis_id",
        "result_hash",
        "kind",
        "receipt_reused",
        "operation_receipt",
    ]
    short = {key: result[key] for key in keys if key in result}
    for key in ("preview", "response", "verification", "result"):
        value = result.get(key)
        if isinstance(value, dict):
            keep = [
                "id",
                "batch_id",
                "state",
                "count",
                "mode",
                "reused",
                "accepted_count",
                "analysis_id",
                "kind",
                "read_back_count",
                "warning_count",
                "result_hash",
                "scope",
                "coverage",
            ]
            short[key] = {k: value[k] for k in keep if k in value}
            if "errors" in value:
                short[key]["blocking_errors"] = len(value["errors"])
    if not short:
        short = {"result_keys": list(result)}
    return short


def markdown_report(command, result, metadata):
    def cell(value):
        return (
            str(value if value is not None else "缺失")
            .replace("|", "\\|")
            .replace("\n", " ")
        )

    lines = [
        "# 知识中台任务回执",
        "",
        f"- 任务：{command}",
        f"- 时间：{metadata['checked_at']}",
        f"- 服务：{metadata['target']}",
        f"- 状态：{metadata['status']}",
        "- 原始结果与条件见同名 JSON；本回执不代表核验通过或正式发布。",
        "",
    ]
    if command == "library-report":
        lines += [
            "## 馆务统计",
            "",
            result["scope_note"],
            "",
            f"用途：{'模拟数据' if result['mode'] == 'demo' else '正式台账'}。",
            (
                f"事项 {result['summary']['records']}；类型 {result['summary']['categories']}；"
                f"日期缺失 {result['summary']['unknown_dates']}；系统预警记录 {result['summary']['needs_attention']}。"
            ),
            "系统预警只覆盖已配置的日期、人数等检查，不等于全部字段缺失；要求检查其他字段时，需结合目录和逐条台账核对。",
            "",
            "| 类型 | 事项数 | 人数有效记录 | 已记录人次 |",
            "| --- | ---: | ---: | ---: |",
        ]
        for row in result["categories"]:
            audience = row["audience_total"] if row["audience_field"] else "不适用"
            lines.append(
                f"| {cell(row['name'])} | {row['records']} | {row['audience_covered']} | {cell(audience)} |"
            )
        lines += [
            "",
            "人次不代表去重人数，不跨不同业务口径累加。",
            "",
            "| 年份 | 事项数 |",
            "| --- | ---: |",
        ]
        for row in result["years"]:
            lines.append(f"| {cell(row['year'])} | {row['records']} |")
    else:
        detail = result.get("verification", result) if isinstance(result, dict) else {}
        analysis = detail.get("result") if isinstance(detail, dict) else None
        if analysis:
            lines += [
                "## 分析范围与覆盖",
                "",
                f"范围论文：{analysis['scope']['publication_count']} 篇。",
                "",
                "| 项目 | 数量 |",
                "| --- | ---: |",
            ]
            for key, label in [
                ("publications_with_authors", "有作者关系"),
                ("publications_with_affiliations", "有机构关系"),
                ("publications_with_disciplines", "有学科关系"),
            ]:
                lines.append(f"| {label} | {analysis['coverage'][key]} |")
            lines += [
                "",
                "以上是数据可用性，不是质量评分；深度结论须继续核对具体论文和指标覆盖。",
            ]
            if detail.get("result_hash"):
                lines += ["", f"服务端快照摘要：{detail['result_hash']}"]
        else:
            lines += [
                "```json",
                json.dumps(short_result(result), ensure_ascii=False, indent=2),
                "```",
            ]
    return "\n".join(lines) + "\n"


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, default=ROOT)
    p.add_argument(
        "--base-url",
        default=os.environ.get("SMARTLIB_HUB_BASE_URL", "http://127.0.0.1:18080"),
    )
    p.add_argument("--output-dir", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    for name in (
        "status",
        "library-catalog",
        "hub-options",
        "analysis-options",
        "scopes",
        "analyses",
    ):
        sub.add_parser(name)
    for name in (
        "library-detail",
        "publication-detail",
        "analysis-detail",
        "change-detail",
    ):
        q = sub.add_parser(name)
        q.add_argument("--id", type=uuid_text, required=True)
    for name in ("library-list", "library-report"):
        q = sub.add_parser(name)
        q.add_argument("--mode", choices=["real", "demo"], required=True)
        q.add_argument("--category", default="")
        q.add_argument("--year", type=int)
        q.add_argument("--department", default="")
        q.add_argument("--q", default="")
    q = sub.add_parser("hub-list")
    q.add_argument("--section", choices=SECTIONS, required=True)
    q.add_argument("--q", default="")
    sub.add_parser("publication-list").add_argument("--q", default="")
    q = sub.add_parser("register")
    q.add_argument(
        "--kind", choices=["sources", "domains", "resources", "rules"], required=True
    )
    q.add_argument("--file", type=Path, required=True)
    q.add_argument("--apply", action="store_true")
    q = sub.add_parser("library-import")
    q.add_argument("--file", type=Path, required=True)
    q.add_argument("--mode", choices=["real", "demo"], required=True)
    q.add_argument("--category", default="")
    q.add_argument("--reason")
    q.add_argument("--apply", action="store_true")
    q = sub.add_parser("library-commit")
    q.add_argument("--id", type=uuid_text, required=True)
    q.add_argument("--reason")
    q.add_argument("--apply", action="store_true")
    for name in ("publication-preview", "publication-import"):
        q = sub.add_parser(name)
        q.add_argument("--file", type=Path, required=True)
        if name == "publication-import":
            q.add_argument("--source-label")
            q.add_argument("--apply", action="store_true")
    q = sub.add_parser("library-revise")
    q.add_argument("--id", type=uuid_text, required=True)
    q.add_argument("--patch", type=Path, required=True)
    q.add_argument("--base-version", type=int, required=True)
    q.add_argument("--reason", required=True)
    q.add_argument("--apply", action="store_true")
    q = sub.add_parser("quality-run")
    q.add_argument("--id", type=uuid_text, required=True)
    q.add_argument("--run-key", required=True)
    q.add_argument("--reason", required=True)
    q.add_argument("--apply", action="store_true")
    q = sub.add_parser("change-submit")
    q.add_argument("--file", type=Path, required=True)
    q.add_argument("--apply", action="store_true")
    for name in ("analyze", "analysis-save"):
        q = sub.add_parser(name)
        q.add_argument("--definition", type=Path)
        if name == "analyze":
            q.add_argument("--module", choices=MODULES)
        else:
            q.add_argument("--name", required=True)
            q.add_argument("--kind", choices=["template", "snapshot"], required=True)
            q.add_argument("--run-key", required=True)
            q.add_argument("--apply", action="store_true")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    project = args.project_root.resolve()
    source = project / "apps/platform-api/src"
    if not (source / "smartlib_platform").is_dir():
        raise SystemExit(
            "找不到项目源码；用 --project-root 指定实际项目，不要使用其他项目环境"
        )
    sys.path.insert(0, str(source))
    output = (
        args.output_dir or project / "outputs/knowledge-hub-skill/receipts"
    ).resolve()
    hub = None
    receipt = {"command": args.command, "checked_at": now()}
    status_code = 0
    try:
        hub = Hub(args.base_url, project, output)
        receipt.update(target=hub.base)
        result = execute(hub, args)
        blocked = isinstance(result, dict) and result.get("stage") == "blocked"
        receipt.update(status="blocked" if blocked else "completed", result=result)
        status_code = 2 if blocked else 0
    except (WorkflowError, ValueError, OSError, KeyError) as exc:
        receipt.update(status="failed_or_unverified", error=str(exc))
        status_code = 2
    finally:
        if hub:
            receipt["actor_id"] = hub.session.get("actor_id") if hub.session else None
            receipt["requests"] = hub.traces
            hub.close()
    stem = (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        + "-"
        + args.command
        + "-"
        + uuid4().hex[:8]
    )
    json_path = output / (stem + ".json")
    private_write(json_path, receipt)
    message = {"status": receipt["status"], "receipt": str(json_path)}
    if "result" in receipt:
        message["summary"] = short_result(receipt["result"])
        report = json_path.with_suffix(".md")
        private_write(report, markdown_report(args.command, receipt["result"], receipt))
        message["report"] = str(report)
    else:
        message["error"] = receipt["error"]
    print(json.dumps(message, ensure_ascii=False, indent=2))
    return status_code


if __name__ == "__main__":
    sys.exit(main())
