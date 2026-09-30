import csv
import io

from psycopg import sql
from psycopg.types.json import Jsonb

from .models import LibraryCommand


class ConflictError(ValueError):
    pass


def create_domain(c, cmd, actor):
    return c.execute(
        """INSERT INTO smartlib.governance_domain(code,name,description,created_by)
        VALUES (%s,%s,%s,%s) RETURNING governance_domain_id id""",
        (cmd.code, cmd.name, cmd.description, actor),
    ).fetchone()


def create_source(c, cmd, actor):
    return c.execute(
        """INSERT INTO smartlib.source_system(code,name,owner_department,source_type,metadata)
      VALUES (%s,%s,%s,%s,%s) RETURNING source_system_id id""",
        (
            cmd.code,
            cmd.name,
            cmd.owner_department,
            cmd.source_type,
            Jsonb(
                {
                    "registered_endpoint": cmd.endpoint,
                    "connection_state": "not_configured",
                    "registration_note": cmd.reason,
                }
            ),
        ),
    ).fetchone()


def create_asset(c, cmd, actor):
    return c.execute(
        """INSERT INTO smartlib.data_asset(code,name,description,source_system_id,
      governance_domain_id,asset_type,lifecycle_state,visibility,created_by)
      VALUES (%s,%s,%s,%s,%s,%s,'draft','campus',%s) RETURNING data_asset_id id""",
        (
            cmd.code,
            cmd.name,
            cmd.description,
            cmd.source_system_id,
            cmd.governance_domain_id,
            cmd.asset_type,
            actor,
        ),
    ).fetchone()


def create_license(c, cmd, actor):
    # A registry submission is not authorization. Approval remains a separate review.
    return c.execute(
        """INSERT INTO smartlib.license_grant(data_asset_id,license_name,license_reference,
        allowed_content,allowed_purposes,prohibited_purposes,terms_metadata,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING license_grant_id id""",
        (
            cmd.data_asset_id,
            cmd.license_name,
            cmd.license_reference,
            cmd.allowed_content,
            cmd.allowed_purposes,
            cmd.prohibited_purposes,
            Jsonb({"registration_reason": cmd.reason}),
            actor,
        ),
    ).fetchone()


def create_rule(c, cmd, actor):
    return c.execute(
        """INSERT INTO smartlib.quality_rule(data_asset_id,code,name,rule_kind,severity,rule_definition,created_by)
      VALUES (%s,%s,%s,'completeness',%s,%s,%s) RETURNING quality_rule_id id""",
        (
            cmd.data_asset_id,
            cmd.code,
            cmd.name,
            cmd.severity,
            Jsonb(
                {
                    "engine": "publication_completeness_v1",
                    "field": cmd.field,
                    "scope": "asset_source_publications",
                }
            ),
            actor,
        ),
    ).fetchone()


def create_schema(c, cmd, actor):
    asset = c.execute(
        "SELECT data_asset_id FROM smartlib.data_asset WHERE data_asset_id=%s FOR UPDATE",
        (cmd.data_asset_id,),
    ).fetchone()
    if not asset:
        raise LookupError("资源不存在或无权访问")
    version = c.execute(
        "SELECT COALESCE(max(version_number),0) version FROM smartlib.data_asset_version WHERE data_asset_id=%s",
        (cmd.data_asset_id,),
    ).fetchone()["version"]
    if version != cmd.base_version:
        raise ConflictError("元数据已有新版本，请刷新后重新提交")
    row = c.execute(
        """INSERT INTO smartlib.data_asset_version(data_asset_id,version_number,schema_version,metadata,created_by)
      VALUES (%s,%s,%s,%s,%s) RETURNING data_asset_version_id id""",
        (cmd.data_asset_id, version + 1, cmd.schema_version, Jsonb({"reason": cmd.reason}), actor),
    ).fetchone()
    for field in cmd.fields:
        c.execute(
            """INSERT INTO smartlib.data_schema_field(data_asset_version_id,field_path,data_type,nullable,
          classification,description,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"],
                field.field_path,
                field.data_type,
                field.nullable,
                field.classification,
                field.description,
                actor,
            ),
        )
    return row


def create_library(c, cmd, actor):
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("library_metric:" + cmd.metric_code,))
    existing = c.execute(
        "SELECT metric_name,unit FROM smartlib.library_metric_record WHERE metric_code=%s LIMIT 1",
        (cmd.metric_code,),
    ).fetchone()
    if existing and (existing["unit"] != cmd.unit or existing["metric_name"] != cmd.metric_name):
        raise ValueError("同一指标代码必须使用相同名称及单位；口径不同请使用新代码")
    return c.execute(
        """INSERT INTO smartlib.library_metric_record(metric_code,metric_name,period,organization,
      value,unit,source_reference,note,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING record_id id""",
        (
            cmd.metric_code,
            cmd.metric_name,
            cmd.period,
            cmd.organization,
            cmd.value,
            cmd.unit,
            cmd.source_reference,
            cmd.note,
            actor,
        ),
    ).fetchone()


def parse_library_csv(raw):
    if len(raw) > 2_000_000:
        raise ValueError("CSV 文件上限 2 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("请使用 UTF-8 编码的 CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    required = {"metric_code", "metric_name", "period", "organization", "value", "unit", "source_reference"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("CSV 缺少必填列，请下载模板")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("CSV 列名不可重复")
    if set(reader.fieldnames) - required - {"note"}:
        raise ValueError("CSV 包含未支持的列，请使用模板，避免误丢数据")
    rows = []
    keys = set()
    definitions = {}
    for index, row in enumerate(reader, start=2):
        if index > 1001:
            raise ValueError("每批最多 1000 条记录")
        if None in row:
            raise ValueError(f"第 {index} 行列数超出表头")
        try:
            command = LibraryCommand(
                **{k: v for k, v in row.items() if k in required | {"note"}}, reason="馆务月度汇总 CSV 导入"
            )
        except ValueError as exc:
            raise ValueError(f"第 {index} 行字段不合要求") from exc
        key = (command.metric_code, command.period, command.organization)
        if key in keys:
            raise ValueError(f"第 {index} 行与本批其他记录重复")
        definition = (command.metric_name, command.unit)
        if command.metric_code in definitions and definitions[command.metric_code] != definition:
            raise ValueError(f"第 {index} 行指标名称或单位不一致")
        definitions[command.metric_code] = definition
        keys.add(key)
        rows.append(command)
    if not rows:
        raise ValueError("CSV 中没有数据记录")
    return rows


def create_application(c, cmd, actor):
    if cmd.code == "scholargraph":
        raise ValueError("学者星图为系统内置应用，不重复登记")
    return c.execute(
        """INSERT INTO smartlib.hub_application(code,name,description,entry_path,owner_department,created_by)
      VALUES (%s,%s,%s,%s,%s,%s) RETURNING application_id id""",
        (cmd.code, cmd.name, cmd.description, cmd.entry_path, cmd.owner_department, actor),
    ).fetchone()


def save_setting(c, cmd, actor):
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("hub_setting:" + cmd.code,))
    row = c.execute(
        "SELECT setting_id id,version FROM smartlib.hub_setting WHERE code=%s FOR UPDATE", (cmd.code,)
    ).fetchone()
    if (row["version"] if row else 0) != cmd.base_version:
        raise ConflictError("配置已更新，请刷新后重试")
    return c.execute(
        """INSERT INTO smartlib.hub_setting(code,value,created_by) VALUES (%s,%s,%s)
      ON CONFLICT(code) DO UPDATE SET value=excluded.value,version=hub_setting.version+1
      RETURNING setting_id id""",
        (cmd.code, cmd.value, actor),
    ).fetchone()


STATES = {
    "resources": ("data_asset", "data_asset_id", "lifecycle_state", {"draft", "active", "paused", "retired"}),
    "applications": (
        "hub_application",
        "application_id",
        "lifecycle_state",
        {"draft", "active", "paused", "retired"},
    ),
    "governance": (
        "quality_issue",
        "quality_issue_id",
        "issue_state",
        {"acknowledged", "resolved", "wont_fix"},
    ),
    "rules": ("quality_rule", "quality_rule_id", "enabled", {"active", "paused"}),
}


def change_state(c, section, record_id, cmd, actor):
    if section not in STATES:
        raise ValueError("此台账不支持直接修改状态")
    table, key, field, allowed = STATES[section]
    if cmd.state not in allowed:
        raise ValueError("状态不适用于当前台账")
    extra = (
        sql.SQL(",resolution=%s,resolved_at=CASE WHEN %s='resolved' THEN clock_timestamp() ELSE NULL END")
        if section == "governance"
        else sql.SQL("")
    )
    if section == "applications":
        extra += sql.SQL(",version=version+1")
    values = [cmd.state == "active" if section == "rules" else cmd.state]
    if section == "governance":
        values += [cmd.reason, cmd.state]
    values += [record_id, cmd.base_updated_at]
    result = c.execute(
        sql.SQL("UPDATE smartlib.{} SET {}=%s").format(sql.Identifier(table), sql.Identifier(field))
        + extra
        + sql.SQL(" WHERE {}=%s AND updated_at=%s::timestamptz RETURNING {} id").format(
            sql.Identifier(key), sql.Identifier(key)
        ),
        values,
    ).fetchone()
    if not result:
        raise ConflictError("记录已被修改或当前身份无写入权限，请刷新检查")
    return result


def run_rule(c, rule_id, actor):
    rule = c.execute(
        """SELECT r.*,a.source_system_id FROM smartlib.quality_rule r
      JOIN smartlib.data_asset a USING(data_asset_id) WHERE quality_rule_id=%s FOR UPDATE OF r""",
        (rule_id,),
    ).fetchone()
    if not rule:
        raise LookupError("规则不存在或无权访问")
    definition = rule["rule_definition"]
    field = definition.get("field")
    if not rule["enabled"]:
        raise ValueError("规则已暂停")
    if definition.get("engine") != "publication_completeness_v1" or field not in {
        "title",
        "abstract",
        "journal_name",
        "publication_year",
        "issn",
        "eissn",
    }:
        raise ValueError("此规则没有可用的检查执行器；不能将规则登记视为已执行")
    rows = c.execute(
        sql.SQL("""SELECT m.publication_id,m.title,m.{} AS value FROM smartlib.publication_metadata m
      JOIN smartlib.knowledge_object o ON o.object_id=m.publication_id
      WHERE o.system_to='infinity' AND o.review_state NOT IN ('rejected','superseded')
      AND (EXISTS (SELECT 1 FROM smartlib.publication_intake_record i
        JOIN smartlib.ingestion_record r USING(record_id)
        JOIN smartlib.ingestion_batch b USING(batch_id)
        WHERE i.matched_publication_id=m.publication_id AND b.source_system_id=%s)
        OR EXISTS (SELECT 1 FROM smartlib.source_reference sr
          WHERE sr.object_id=m.publication_id AND sr.source_system_id=%s))
      ORDER BY m.publication_id""").format(sql.Identifier(field)),
        (rule["source_system_id"], rule["source_system_id"]),
    ).fetchall()
    missing = [
        {"publication_id": str(r["publication_id"]), "title": r["title"]}
        for r in rows
        if r["value"] is None or not str(r["value"]).strip()
    ]
    state = "error" if not rows else "failed" if missing else "passed"
    details = {
        "scope": "当前身份可见、属于该资产来源的去重论文",
        "field": field,
        "total": len(rows),
        "missing": len(missing),
        "examples": missing[:100],
        "examples_truncated": len(missing) > 100,
        "note": "没有可检查论文，不能认定规则通过"
        if not rows
        else "检查不修改规范事实；缺失记录可进入人工变更流程",
    }
    run = c.execute(
        """INSERT INTO smartlib.quality_run(quality_rule_id,run_state,observed_value,expected_value,
      finished_at,details,created_by) VALUES (%s,%s,%s,0,clock_timestamp(),%s,%s) RETURNING quality_run_id id""",
        (rule_id, state, len(missing), Jsonb(details), actor),
    ).fetchone()
    if missing:
        c.execute(
            """INSERT INTO smartlib.quality_issue(data_asset_id,quality_run_id,title,description,severity,
          requires_human_confirmation,created_by) VALUES (%s,%s,%s,%s,%s,true,%s)""",
            (
                rule["data_asset_id"],
                run["id"],
                rule["name"],
                f"本次检查 {len(rows)} 篇论文，{len(missing)} 篇缺少 {field}。",
                rule["severity"],
                actor,
            ),
        )
    return {"id": run["id"], "state": state, **details}


def revise_library(c, record_id, cmd, actor):
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("library_metric:" + cmd.metric_code,))
    row = c.execute(
        "SELECT * FROM smartlib.library_metric_record WHERE record_id=%s FOR UPDATE", (record_id,)
    ).fetchone()
    if not row:
        raise LookupError("记录不存在或不可见")
    if row["version"] != cmd.base_version:
        raise ConflictError("记录已有新版本，请刷新后重新修订")
    # A revision corrects the value and provenance; it cannot silently redefine the series.
    for key in ["metric_code", "metric_name", "period", "organization", "unit"]:
        if row[key] != getattr(cmd, key):
            raise ValueError("修订只允许修改数值、来源及说明；指标口径和时间机构不得改变")
    result = c.execute(
        """UPDATE smartlib.library_metric_record SET value=%s,source_reference=%s,note=%s,
      version=version+1 WHERE record_id=%s RETURNING record_id id""",
        (cmd.value, cmd.source_reference, cmd.note, record_id),
    ).fetchone()
    c.execute(
        """INSERT INTO smartlib.governance_change(resource_type,resource_id,change_type,
      before_state,after_state,reason,created_by) VALUES ('library_metric_record',%s,'corrected',%s,%s,%s,%s)""",
        (
            record_id,
            Jsonb(
                {
                    "value": str(row["value"]),
                    "source_reference": row["source_reference"],
                    "note": row["note"],
                    "version": row["version"],
                }
            ),
            Jsonb(
                {
                    "value": cmd.value,
                    "source_reference": cmd.source_reference,
                    "note": cmd.note,
                    "version": row["version"] + 1,
                }
            ),
            cmd.reason,
            actor,
        ),
    )
    return result
