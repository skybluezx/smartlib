"""Run the Skill against real FastAPI routes/DB, rolling back every test write."""

import importlib.util
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from smartlib_platform.entrypoints import http
from smartlib_platform.foundation.config import Settings

settings = Settings.from_env()
if settings.environment != "development":
    raise RuntimeError("This rollback test is restricted to the local development environment")
skill_path = Path("/skills/smartlib-knowledge-hub/scripts/hub.py")
if not skill_path.exists():
    skill_path = Path(__file__).resolve().parents[3] / "skills/smartlib-knowledge-hub/scripts/hub.py"
spec = importlib.util.spec_from_file_location("hub_skill", skill_path)
skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill)
tables = [
    "library_work_record",
    "library_work_batch",
    "library_work_revision",
    "publication_intake_record",
    "change_submission",
    "quality_rule",
    "quality_run",
    "data_asset",
    "source_system",
    "saved_analysis",
    "governance_domain",
]
checks = []

with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:

    def counts():
        return {
            table: connection.execute("SELECT count(*) n FROM smartlib." + table).fetchone()["n"]
            for table in tables
        }

    connection.execute("SELECT set_config('smartlib.actor_id',%s,false)", (str(settings.dev_actor_id),))
    before = counts()
    connection.commit()
    with connection.transaction(force_rollback=True), tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        @contextmanager
        def transaction(actor_id, *, repeatable_read=False):
            with connection.transaction():
                connection.execute("SELECT set_config('smartlib.actor_id',%s,true)", (str(actor_id),))
                yield connection

        api = TestClient(http.app)

        def route(request):
            result = api.request(
                request.method,
                request.url.raw_path.decode(),
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx.Response(result.status_code, content=result.content, headers=dict(result.headers))

        with patch.object(http.database, "transaction", transaction):
            hub = skill.Hub(
                "http://127.0.0.1:18080", root, root / "receipts", transport=httpx.MockTransport(route)
            )

            def run(*values):
                return skill.execute(hub, skill.parser().parse_args(list(values)))

            def file(name, value):
                path = root / name
                path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                return str(path)

            library = root / "读者培训.csv"
            library.write_text(f"时间,内容,听众人数\n2025-03,Skill回滚验收-{uuid4()},12\n")
            imported = run(
                "library-import",
                "--file",
                str(library),
                "--mode",
                "demo",
                "--reason",
                "Skill回滚验收",
                "--apply",
            )
            assert imported["verification"]["count"] == 1
            assert run(
                "library-import",
                "--file",
                str(library),
                "--mode",
                "demo",
                "--reason",
                "Skill回滚验收",
                "--apply",
            )["response"]["reused"]
            rows = run("library-list", "--mode", "demo", "--q", "Skill回滚验收")["items"]
            row = rows[0]
            patch_path = file("patch.json", {"听众人数": "24"})
            revised = run(
                "library-revise",
                "--id",
                row["id"],
                "--base-version",
                "1",
                "--patch",
                patch_path,
                "--reason",
                "模拟证据修正验收",
                "--apply",
            )
            assert revised["verification"]["submitted_version"] == 2
            assert run("library-detail", "--id", row["id"])["audience"] == 24
            checks.extend(["library import/commit/readback", "library idempotence", "versioned revision"])

            paper = root / "publications.csv"
            paper.write_text("title,publication_year\nSkill rollback publication,2025\n")
            imported = run(
                "publication-import", "--file", str(paper), "--source-label", "Skill回滚验收", "--apply"
            )
            assert imported["verification"]["read_back_count"] == 1
            assert imported["response"]["manual_review_count"] == 1
            assert run(
                "publication-import", "--file", str(paper), "--source-label", "Skill回滚验收", "--apply"
            )["receipt_reused"]
            checks.append("publication intake/pending/readback/no duplicate")

            code = "skill_check_" + uuid4().hex[:8]
            source = run(
                "register",
                "--kind",
                "sources",
                "--file",
                file(
                    "source.json",
                    {
                        "code": code,
                        "name": "回滚验收来源",
                        "owner_department": "图书馆",
                        "source_type": "file",
                        "reason": "仅回滚验收",
                    },
                ),
                "--apply",
            )["response"]
            domain = run(
                "register",
                "--kind",
                "domains",
                "--file",
                file(
                    "domain.json",
                    {"code": code, "name": "回滚验收域", "description": "仅回滚验收", "reason": "仅回滚验收"},
                ),
                "--apply",
            )["response"]
            asset = run(
                "register",
                "--kind",
                "resources",
                "--file",
                file(
                    "asset.json",
                    {
                        "code": code,
                        "name": "回滚验收资产",
                        "source_system_id": source["id"],
                        "governance_domain_id": domain["id"],
                        "asset_type": "dataset",
                        "reason": "仅回滚验收",
                    },
                ),
                "--apply",
            )["response"]
            rule = run(
                "register",
                "--kind",
                "rules",
                "--file",
                file(
                    "rule.json",
                    {
                        "data_asset_id": asset["id"],
                        "code": code,
                        "name": "回滚验收摘要检查",
                        "field": "abstract",
                        "reason": "仅回滚验收",
                    },
                ),
                "--apply",
            )["response"]
            quality = run(
                "quality-run", "--id", rule["id"], "--run-key", code, "--reason", "仅回滚验收", "--apply"
            )
            assert quality["response"]["total"] == 0 and quality["response"]["state"] == "error"
            checks.append("registry/rule/run/history/empty is not passed")

            target = connection.execute(
                "SELECT object_id,version FROM smartlib.knowledge_object WHERE object_type='organization' AND system_to='infinity' ORDER BY object_id LIMIT 1"
            ).fetchone()
            payload = {
                "context_object_id": str(target["object_id"]),
                "source_label": "回滚验收来源",
                "reason": "仅提交不采纳的回滚验收",
                "proposals": [
                    {
                        "target_kind": "object",
                        "target_id": str(target["object_id"]),
                        "field_path": "description",
                        "proposed_value": "仅回滚验收",
                        "base_version": target["version"],
                    }
                ],
            }
            proposal = run("change-submit", "--file", file("proposal.json", payload), "--apply")
            assert proposal["verification"]["status"] == "needs_review"
            assert (
                connection.execute(
                    "SELECT version FROM smartlib.knowledge_object WHERE object_id=%s AND system_to='infinity'",
                    (target["object_id"],),
                ).fetchone()["version"]
                == target["version"]
            )
            checks.append("change proposal/readback/no implicit approval")

            scope = file("scope.json", {"start_year": 2199, "end_year": 2200})
            snapshot = run(
                "analysis-save",
                "--definition",
                scope,
                "--name",
                "Skill回滚快照",
                "--kind",
                "snapshot",
                "--run-key",
                code,
                "--apply",
            )
            assert snapshot["verification"]["result_hash"]
            assert snapshot["verification"]["result"]["scope"]["publication_count"] == 0
            assert (
                run("analysis-detail", "--id", snapshot["response"]["analysis_id"])["result_hash"]
                == snapshot["verification"]["result_hash"]
            )
            checks.append("snapshot/server calculation/hash/readback")
            hub.close()
            api.close()
    after = counts()
    assert before == after, (before, after)
print(
    json.dumps({"status": "passed", "checks": checks, "rollback_counts_unchanged": True}, ensure_ascii=False)
)
