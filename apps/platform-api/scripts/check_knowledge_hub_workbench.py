"""Integration acceptance against a configured local DB. ALL writes are rolled back."""

from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from smartlib_platform.foundation.config import Settings
from smartlib_platform.knowledge_hub import catalog, models, service


def main():
    settings = Settings.from_env()
    actor = settings.dev_actor_id
    code = "hub_check_" + uuid4().hex[:12]
    with psycopg.connect(settings.database_url, row_factory=dict_row) as c:
        before = c.execute("SELECT count(*) n FROM smartlib.knowledge_object").fetchone()["n"]
        with c.transaction(force_rollback=True):
            c.execute("SELECT set_config('smartlib.actor_id',%s,true)", (str(actor),))
            for section in catalog.QUERIES:
                result = catalog.table(c, section)
                assert result["total"] >= len(result["items"])
                print("READ", section, result["total"])
            options = catalog.options(c)
            domain = service.create_domain(
                c,
                models.DomainCommand(
                    code=code, name="验收治理域", description="临时验收，全部回滚", reason="自动验收回滚"
                ),
                actor,
            )["id"]
            assert any(row["id"] == domain for row in catalog.options(c)["domains"])
            source = service.create_source(
                c,
                models.SourceCommand(
                    code=code,
                    name="回滚验收来源",
                    owner_department="图书馆",
                    source_type="file",
                    reason="自动验收回滚",
                ),
                actor,
            )["id"]
            assert (
                c.execute(
                    "SELECT authorization_state FROM smartlib.source_system WHERE source_system_id=%s",
                    (source,),
                ).fetchone()["authorization_state"]
                == "pending"
            )
            asset = service.create_asset(
                c,
                models.AssetCommand(
                    code=code,
                    name="回滚验收资产",
                    source_system_id=source,
                    governance_domain_id=domain,
                    asset_type="dataset",
                    reason="自动验收回滚",
                ),
                actor,
            )["id"]
            schema = models.SchemaCommand(
                data_asset_id=asset,
                base_version=0,
                schema_version="check.1",
                fields=[models.SchemaField(field_path="title", data_type="string")],
                reason="自动验收回滚",
            )
            service.create_schema(c, schema, actor)
            try:
                service.create_schema(c, schema, actor)
            except service.ConflictError:
                pass
            else:
                raise AssertionError("Stale schema was not rejected")
            license_id = service.create_license(
                c,
                models.LicenseCommand(
                    data_asset_id=asset,
                    license_name="验收许可",
                    license_reference="验收材料",
                    allowed_content=["metadata"],
                    allowed_purposes=["analytics"],
                    reason="自动验收回滚",
                ),
                actor,
            )["id"]
            assert (
                c.execute(
                    "SELECT authorization_state FROM smartlib.license_grant WHERE license_grant_id=%s",
                    (license_id,),
                ).fetchone()["authorization_state"]
                == "pending"
            )
            rule = service.create_rule(
                c,
                models.RuleCommand(
                    data_asset_id=asset, code=code, name="摘要完整性", field="abstract", reason="自动验收回滚"
                ),
                actor,
            )["id"]
            assert service.run_rule(c, rule, actor)["state"] == "error"
            # Exercise a real source-scoped check without changing a publication.
            candidate = c.execute("""SELECT sr.source_system_id FROM smartlib.source_reference sr
                JOIN smartlib.publication_metadata m ON m.publication_id=sr.object_id
                JOIN smartlib.knowledge_object o ON o.object_id=m.publication_id
                WHERE o.system_to='infinity' AND o.review_state NOT IN ('rejected','superseded')
                ORDER BY (COALESCE(m.abstract,'')='') DESC LIMIT 1""").fetchone()
            if candidate:
                c.execute("UPDATE smartlib.data_asset SET source_system_id=%s WHERE data_asset_id=%s",
                          (candidate["source_system_id"], asset))
                checked = service.run_rule(c, rule, actor)
                assert checked["total"] > 0
                assert len({row["publication_id"] for row in checked["examples"]}) == len(checked["examples"])
                if checked["missing"]:
                    issue = c.execute("SELECT quality_issue_id id,updated_at FROM smartlib.quality_issue WHERE quality_run_id=%s",
                                      (checked["id"],)).fetchone()
                    assert issue
                    service.change_state(c, "governance", issue["id"], models.StateCommand(
                        state="resolved", base_updated_at=issue["updated_at"], reason="验收处理回滚"), actor)
                print("QUALITY", checked["state"], "papers", checked["total"], "missing", checked["missing"])
            cmd = models.LibraryCommand(
                metric_code=code,
                metric_name="验收指标",
                period="2026-09-01",
                organization="图书馆",
                value=10,
                unit="人次",
                source_reference="验收数据",
                reason="自动验收回滚",
            )
            record = service.create_library(c, cmd, actor)["id"]
            revision = models.LibraryRevision(**{**cmd.model_dump(), "value": 12}, base_version=1)
            service.revise_library(c, record, revision, actor)
            try:
                service.revise_library(c, record, revision, actor)
            except service.ConflictError:
                pass
            else:
                raise AssertionError("Stale library revision was not rejected")
            assert c.execute(
                "SELECT value,version FROM smartlib.library_metric_record WHERE record_id=%s", (record,)
            ).fetchone() == {"value": 12, "version": 2}
            # One invalid row aborts its entire batch, including the prior valid row.
            try:
                with c.transaction():
                    service.create_library(
                        c, cmd.model_copy(update={"period": cmd.period.replace(month=8)}), actor
                    )
                    service.create_library(c, cmd, actor)
            except psycopg.IntegrityError:
                pass
            else:
                raise AssertionError("Duplicate was not rejected")
            assert (
                c.execute(
                    "SELECT count(*) n FROM smartlib.library_metric_record WHERE metric_code=%s", (code,)
                ).fetchone()["n"]
                == 1
            )
            app = service.create_application(
                c,
                models.ApplicationCommand(
                    code=code,
                    name="验收应用",
                    entry_path="/graph-analytics",
                    owner_department="图书馆",
                    reason="自动验收回滚",
                ),
                actor,
            )["id"]
            current = c.execute(
                "SELECT updated_at FROM smartlib.hub_application WHERE application_id=%s", (app,)
            ).fetchone()
            service.change_state(
                c,
                "applications",
                app,
                models.StateCommand(
                    state="active", base_updated_at=current["updated_at"], reason="自动验收回滚"
                ),
                actor,
            )
            setting = c.execute(
                "SELECT version FROM smartlib.hub_setting WHERE code='workbench_notice'"
            ).fetchone()
            version = setting["version"] if setting else 0
            service.save_setting(
                c,
                models.SettingCommand(
                    code="workbench_notice", value="验收公告", base_version=version, reason="自动验收回滚"
                ),
                actor,
            )
            try:
                service.save_setting(
                    c,
                    models.SettingCommand(
                        code="workbench_notice", value="过期改动", base_version=version, reason="自动验收回滚"
                    ),
                    actor,
                )
            except service.ConflictError:
                pass
            else:
                raise AssertionError("Stale setting was not rejected")
            c.execute("SELECT set_config('smartlib.actor_id',%s,true)", (str(uuid4()),))
            assert catalog.table(c, "library")["total"] == 0
            try:
                with c.transaction():
                    service.create_application(
                        c,
                        models.ApplicationCommand(
                            code=code + "_denied",
                            name="无权限",
                            entry_path="/",
                            owner_department="图书馆",
                            reason="权限验收回滚",
                        ),
                        actor,
                    )
            except psycopg.errors.InsufficientPrivilege:
                pass
            else:
                raise AssertionError("RLS did not reject an unprivileged write")
        assert c.execute("SELECT count(*) n FROM smartlib.knowledge_object").fetchone()["n"] == before
        assert (
            c.execute("SELECT count(*) n FROM smartlib.source_system WHERE code=%s", (code,)).fetchone()["n"]
            == 0
        )
    print("PASS: catalogs, writes, license boundary, revisions, atomic batch, RLS; all fixtures rolled back")


if __name__ == "__main__":
    main()
