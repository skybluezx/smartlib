"""Local DB acceptance; rollback all fixtures and verify access isolation."""

from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from smartlib_platform.foundation.config import Settings
from smartlib_platform.library_work import service
from smartlib_platform.library_work.models import ImportCommit, WorkRevision
from smartlib_platform.knowledge_hub.service import ConflictError

settings = Settings.from_env()
actor = settings.dev_actor_id
with psycopg.connect(settings.database_url, row_factory=dict_row) as c:
    with c.transaction(force_rollback=True):
        c.execute("SELECT set_config('smartlib.actor_id',%s,true)", (str(actor),))
        before = service.overview(c, "demo")["summary"]["records"]
        real_before = service.overview(c, "real")["summary"]["records"]
        data = f"时间,内容,听众人数\n2025-03,回滚验收-{uuid4()},12\n2024,回滚验收-{uuid4()},\n".encode()
        b = service.preview(c, actor, "读者培训.csv", data, "demo")
        assert b["count"] == 2 and not b["errors"]
        assert service.overview(c, "demo")["summary"]["records"] == before
        command = ImportCommit(confirm=True, reason="验收测试全量回滚")
        a = service.commit(c, actor, b["id"], command)
        assert a["count"] == 2 and not a["reused"]
        assert service.commit(c, actor, b["id"], command)["reused"]
        again = service.preview(c, actor, "读者培训.csv", data, "demo")
        assert again["already_imported"] and service.commit(c, actor, again["id"], command)["reused"]
        assert service.overview(c, "demo")["summary"]["records"] == before + 2
        assert service.overview(c, "real")["summary"]["records"] == real_before
        row = c.execute(
            "SELECT record_id FROM smartlib.library_work_record WHERE batch_id=%s LIMIT 1", (b["id"],)
        ).fetchone()
        r = service.detail(c, row["record_id"])
        revision = WorkRevision(
            category=r["category"],
            mode=r["mode"],
            fields=r["fields"],
            base_version=1,
            state="withdrawn",
            reason="撤回测试但保留历史",
        )
        updated = service.revise(c, actor, r["id"], revision)
        assert updated["version"] == 2 and len(service.detail(c, r["id"])["history"]) == 2
        assert service.overview(c, "demo")["summary"]["records"] == before + 1
        try:
            service.revise(c, actor, r["id"], revision)
        except ConflictError:
            pass
        else:
            raise AssertionError("stale revision accepted")
        bad = service.preview(c, actor, "读者培训.csv", "时间,内容\n2025,\n".encode(), "real")
        try:
            service.commit(c, actor, bad["id"], command)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid import committed")
        try:
            service.revise(c, actor, r["id"], revision.model_copy(update={"base_version": 2, "mode": "real"}))
        except ValueError:
            pass
        else:
            raise AssertionError("demo provenance changed")
        c.execute("SELECT set_config('smartlib.actor_id',%s,true)", (str(uuid4()),))
        for table in ("library_work_record", "library_work_batch", "library_work_revision"):
            assert c.execute(f"SELECT count(*) n FROM smartlib.{table}").fetchone()["n"] == 0
        try:
            service.detail(c, r["id"])
        except LookupError:
            pass
        else:
            raise AssertionError("other actor read record")
print(
    "LIBRARY_WORK_DB_PASS: preview, atomic commit, idempotence, separation, revision, withdrawal, owner RLS; all fixtures rolled back"
)
