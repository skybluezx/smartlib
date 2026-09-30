import hashlib
from datetime import UTC, datetime
from uuid import UUID

from psycopg.types.json import Jsonb

from smartlib_platform.knowledge_hub.service import ConflictError

from .parser import BY_CODE, normalize, parse_upload


def preview(c, actor, filename, data, mode, category=""):
    result = parse_upload(filename, data, category)
    if mode == "real" and any(r["title"].startswith("【模拟】") for r in result["records"]):
        raise ValueError("文件包含明确标注的模拟事项，请选择模拟数据用途")
    # Interpretation is part of import identity: same bytes with a different selected schema are distinct.
    digest = hashlib.sha256(data + b"\0" + category.encode()).hexdigest()
    batch = c.execute(
        """INSERT INTO smartlib.library_work_batch
        (created_by,filename,file_hash,mode,preview) VALUES(%s,%s,%s,%s,%s) RETURNING batch_id id""",
        (actor, filename, digest, mode, Jsonb(result)),
    ).fetchone()
    return batch_detail(c, batch["id"])


def batch_detail(c, identifier):
    row = c.execute(
        "SELECT *,batch_id id FROM smartlib.library_work_batch WHERE batch_id=%s", (identifier,)
    ).fetchone()
    if not row:
        raise LookupError("导入批次不存在或无权访问")
    payload = row.pop("preview")
    row.update(
        count=len(payload["records"]),
        errors=payload["errors"],
        skipped_rows=payload["skipped_rows"],
        warning_count=payload["warning_count"],
        categories=payload["categories"],
        examples=payload["records"][:30],
        examples_truncated=len(payload["records"]) > 30,
    )
    existing = c.execute(
        """SELECT batch_id FROM smartlib.library_work_batch
        WHERE file_hash=%s AND mode=%s AND state='imported' """,
        (row["file_hash"], row["mode"]),
    ).fetchone()
    row["already_imported"] = bool(existing)
    return row


def insert(c, actor, record, mode, reason, batch_id=None):
    if mode == "real" and record["title"].startswith("【模拟】"):
        raise ValueError("模拟事项不能写入正式台账")
    row = c.execute(
        """INSERT INTO smartlib.library_work_record
        (created_by,batch_id,category,title,mode,year,month,date_precision,department,audience,fields,warnings,origin,content_hash)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *,record_id id""",
        (
            actor,
            batch_id,
            record["category"],
            record["title"],
            mode,
            record["year"],
            record["month"],
            record["date_precision"],
            record["department"],
            record["audience"],
            Jsonb(record["fields"]),
            Jsonb(record["warnings"]),
            Jsonb(record["origin"]),
            record["content_hash"],
        ),
    ).fetchone()
    history(c, row, reason)
    return row


def history(c, row, reason):
    snapshot = {
        key: (str(value) if isinstance(value, (datetime, UUID)) else value) for key, value in row.items()
    }
    c.execute(
        """INSERT INTO smartlib.library_work_revision (record_id,created_by,version,reason,snapshot)
        VALUES(%s,%s,%s,%s,%s)""",
        (row["id"], row["created_by"], row["version"], reason, Jsonb(snapshot)),
    )


def commit(c, actor, identifier, command):
    if not command.confirm:
        raise ValueError("请确认预检结果及数据用途")
    batch = c.execute(
        "SELECT * FROM smartlib.library_work_batch WHERE batch_id=%s FOR UPDATE", (identifier,)
    ).fetchone()
    if not batch:
        raise LookupError("导入批次不存在或无权访问")
    c.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (str(actor) + batch["mode"],),
    )
    existing = c.execute(
        """SELECT batch_id id,jsonb_array_length(preview->'records') count
        FROM smartlib.library_work_batch WHERE file_hash=%s AND mode=%s AND state='imported' """,
        (batch["file_hash"], batch["mode"]),
    ).fetchone()
    if existing:
        return {**existing, "reused": True}
    if batch["expires_at"] < datetime.now(UTC):
        raise ConflictError("预检结果已超过 24 小时，请重新上传")
    payload = batch["preview"]
    if payload["errors"] or not payload["records"]:
        raise ValueError("预检存在错误或没有可导入事项，请修正文件后重新上传")
    for record in payload["records"]:
        duplicate = c.execute(
            """SELECT 1 FROM smartlib.library_work_record
            WHERE mode=%s AND category=%s AND content_hash=%s AND state='active' LIMIT 1""",
            (batch["mode"], record["category"], record["content_hash"]),
        ).fetchone()
        if duplicate:
            raise ConflictError("与已有台账存在完全重复事项；整批未写入，请先核查已有记录")
        insert(c, actor, record, batch["mode"], command.reason, identifier)
    c.execute(
        "UPDATE smartlib.library_work_batch SET state='imported',committed_at=clock_timestamp() "
        "WHERE batch_id=%s",
        (identifier,),
    )
    return {"id": identifier, "count": len(payload["records"]), "reused": False}


def create(c, actor, command):
    return insert(c, actor, normalize(command.category, command.fields), command.mode, command.reason)


def detail(c, identifier):
    row = c.execute(
        "SELECT *,record_id id FROM smartlib.library_work_record WHERE record_id=%s", (identifier,)
    ).fetchone()
    if not row:
        raise LookupError("记录不存在或无权访问")
    row["history"] = c.execute(
        """SELECT version,reason,created_at,snapshot FROM smartlib.library_work_revision
        WHERE record_id=%s ORDER BY version DESC""",
        (identifier,),
    ).fetchall()
    return row


def revise(c, actor, identifier, command):
    old = c.execute(
        "SELECT * FROM smartlib.library_work_record WHERE record_id=%s FOR UPDATE", (identifier,)
    ).fetchone()
    if not old:
        raise LookupError("记录不存在或无权访问")
    if old["version"] != command.base_version:
        raise ConflictError("记录已被修改，请刷新后再编辑")
    if command.mode != old["mode"] or command.category != old["category"]:
        raise ValueError("不能更改记录的数据用途与业务类型")
    record = normalize(command.category, command.fields, old["origin"])
    row = c.execute(
        """UPDATE smartlib.library_work_record SET title=%s,year=%s,month=%s,date_precision=%s,
        department=%s,audience=%s,fields=%s,warnings=%s,content_hash=%s,state=%s,version=version+1,
        updated_at=clock_timestamp() WHERE record_id=%s RETURNING *,record_id id""",
        (
            record["title"],
            record["year"],
            record["month"],
            record["date_precision"],
            record["department"],
            record["audience"],
            Jsonb(record["fields"]),
            Jsonb(record["warnings"]),
            record["content_hash"],
            command.state,
            identifier,
        ),
    ).fetchone()
    history(c, row, command.reason)
    return row


def where(mode, category="", year=None, department="", q="", state="active"):
    if category and category not in BY_CODE:
        raise ValueError("未知业务类型")
    return (
        """mode=%s AND (%s='' OR category=%s) AND (%s::integer IS NULL OR year=%s)
        AND (%s='' OR department=%s) AND (%s='' OR strpos(lower(title||fields::text),lower(%s))>0)
        AND (%s='all' OR state=%s)""",
        (mode, category, category, year, year, department, department, q, q, state, state),
    )


def listing(c, mode="real", category="", year=None, department="", q="", state="active", page=1):
    clause, args = where(mode, category, year, department, q, state)
    total = c.execute("SELECT count(*) n FROM smartlib.library_work_record WHERE " + clause, args).fetchone()[
        "n"
    ]
    rows = c.execute(
        "SELECT *,record_id id FROM smartlib.library_work_record WHERE "
        + clause
        + " ORDER BY year DESC NULLS LAST,month DESC NULLS LAST,created_at DESC,record_id LIMIT 25 OFFSET %s",
        (*args, (page - 1) * 25),
    ).fetchall()
    return {"items": rows, "total": total, "page": page, "page_size": 25}


def overview(c, mode="real", category="", year=None, department="", q="", state="active"):
    clause, args = where(mode, category, year, department, q, state)
    source = " FROM smartlib.library_work_record WHERE " + clause
    summary = c.execute(
        """SELECT count(*) records,count(DISTINCT category) categories,
        count(*) FILTER(WHERE year IS NULL) unknown_dates,
        count(*) FILTER(WHERE warnings<>'[]'::jsonb) needs_attention"""
        + source,
        args,
    ).fetchone()
    categories = c.execute(
        """SELECT category,count(*) records,count(audience) audience_covered,
        sum(audience) audience_total"""
        + source
        + " GROUP BY category ORDER BY records DESC,category",
        args,
    ).fetchall()
    for item in categories:
        spec = BY_CODE[item["category"]]
        item.update(name=spec["name"], group=spec["group"], audience_field=spec["audience_field"])
    years = c.execute(
        "SELECT year,count(*) records" + source + " GROUP BY year ORDER BY year NULLS LAST", args
    ).fetchall()
    options = c.execute(
        """SELECT array_agg(DISTINCT year ORDER BY year) FILTER(WHERE year IS NOT NULL) years,
        array_agg(DISTINCT department ORDER BY department) FILTER(WHERE department<>'') departments
        FROM smartlib.library_work_record WHERE mode=%s""",
        (mode,),
    ).fetchone()
    return {
        "summary": summary,
        "categories": categories,
        "years": years,
        "options": options,
        "mode": mode,
        "scope_note": "仅统计本人可见记录；模拟与正式数据分开。事项数不等于工作质量或绩效。",
    }


def batches(c, mode):
    return c.execute(
        """SELECT batch_id id,filename,mode,state,created_at,committed_at,
        jsonb_array_length(preview->'records') count,jsonb_array_length(preview->'errors') errors,
        (preview->>'warning_count')::integer warning_count FROM smartlib.library_work_batch
        WHERE mode=%s ORDER BY created_at DESC LIMIT 100""",
        (mode,),
    ).fetchall()
