# ruff: noqa: RUF001

import csv
import io
import json
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from smartlib_platform.foundation.database import DbConnection
from smartlib_platform.publications.models import (
    PublicationImportItemResult,
    PublicationImportRecordInput,
    PublicationImportResult,
)

IMPORT_RULE_VERSION = "publication-intake-v1"
MAX_BATCH_ROWS = 5000

FIELD_ALIASES = {
    "title": ("title", "题名", "论文题名", "论文名称"),
    "journal_name": ("journal_name", "journal", "期刊", "期刊名称", "刊物名称"),
    "publication_year": ("publication_year", "year", "发表年份", "出版年份", "年份"),
    "doi": ("doi", "DOI"),
    "pmid": ("pmid", "PMID"),
    "pmcid": ("pmcid", "PMCID"),
    "authors": ("authors", "author_list", "作者", "作者列表"),
    "awardee_name": ("awardee_name", "获批人", "学者姓名", "成果归属人"),
    "representative_work_number": (
        "representative_work_number", "代表性论著序号", "代表性论著编号", "论著编号"
    ),
}


def _clean(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _normalize_doi(value: object) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", cleaned, flags=re.I).strip().lower()


def _split_authors(value: object) -> list[str]:
    cleaned = _clean(value)
    if not cleaned:
        return []
    return [item.strip() for item in re.split(r"[;；|\n]+", cleaned) if item.strip()]


def automatic_eligibility(record: PublicationImportRecordInput) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not record.doi:
        reasons.append("缺少 DOI，不能进行 DOI 精确核验")
    if record.publication_year is None:
        reasons.append("缺少发表年份，不能完成年份一致性核验")
    if record.awardee_name and not record.authors:
        reasons.append("声明了成果归属人，但没有作者列表，不能自动确认作者归属")
    return not reasons, reasons


def records_from_csv(content: bytes) -> list[PublicationImportRecordInput]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV 必须使用 UTF-8 编码") from exc
    return records_from_rows(list(csv.DictReader(io.StringIO(text))))


def records_from_xlsx(path: Path) -> list[PublicationImportRecordInput]:
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    try:
        with zipfile.ZipFile(path) as archive:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = ["".join(node.itertext()) for node in root.findall(f"{{{main_ns}}}si")]
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            sheet = workbook.find(f".//{{{main_ns}}}sheet")
            if sheet is None:
                raise ValueError("XLSX 中没有工作表")
            relation_id = sheet.get(f"{{{rel_ns}}}id")
            relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            target = next(
                (
                    relation.get("Target")
                    for relation in relationships.findall(f"{{{package_rel_ns}}}Relationship")
                    if relation.get("Id") == relation_id
                ),
                None,
            )
            if not target:
                raise ValueError("无法定位 XLSX 的首个工作表")
            sheet_path = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(posixpath.join("xl", target))
            )
            root = ET.fromstring(archive.read(sheet_path))
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ValueError("文件不是有效的 XLSX 工作簿") from exc

    matrix: list[list[object]] = []
    for row in root.findall(f".//{{{main_ns}}}row"):
        values: dict[int, object] = {}
        for cell in row.findall(f"{{{main_ns}}}c"):
            reference = cell.get("r", "A1")
            letters = re.match(r"[A-Z]+", reference)
            if not letters:
                continue
            index = 0
            for letter in letters.group():
                index = index * 26 + ord(letter) - 64
            cell_type = cell.get("t")
            if cell_type == "inlineStr":
                value: object = "".join(cell.itertext())
            else:
                value_node = cell.find(f"{{{main_ns}}}v")
                raw = value_node.text if value_node is not None else ""
                if cell_type == "s" and raw:
                    value = shared[int(raw)]
                elif cell_type in {"str", "b"}:
                    value = raw
                else:
                    try:
                        number = float(raw)
                        value = int(number) if number.is_integer() else number
                    except ValueError:
                        value = raw
            values[index - 1] = value
        if values:
            matrix.append([values.get(index) for index in range(max(values) + 1)])
    if not matrix:
        raise ValueError("XLSX 首个工作表中没有数据")
    headers = [_clean(value) or "" for value in matrix[0]]
    return records_from_rows([dict(zip(headers, row, strict=False)) for row in matrix[1:]])


def records_from_rows(rows: list[dict[str, object]]) -> list[PublicationImportRecordInput]:
    if len(rows) > MAX_BATCH_ROWS:
        raise ValueError(f"单次最多导入 {MAX_BATCH_ROWS} 条论文")
    alias_lookup = {
        alias.strip().casefold(): field for field, aliases in FIELD_ALIASES.items() for alias in aliases
    }
    parsed: list[PublicationImportRecordInput] = []
    errors: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        values: dict[str, object] = {}
        extras: dict[str, object] = {}
        for header, value in row.items():
            field = alias_lookup.get(str(header or "").strip().casefold())
            if field:
                values[field] = value
            elif _clean(value):
                extras[str(header)] = value
        title = _clean(values.get("title"))
        if not title and not any(_clean(value) for value in row.values()):
            continue
        if not title:
            errors.append(f"第 {row_number} 行缺少论文题名")
            continue
        year_value = _clean(values.get("publication_year"))
        try:
            year = int(float(year_value)) if year_value else None
        except ValueError:
            errors.append(f"第 {row_number} 行发表年份不是有效数字")
            continue
        try:
            parsed.append(PublicationImportRecordInput(
                title=title,
                journal_name=_clean(values.get("journal_name")),
                publication_year=year,
                doi=_normalize_doi(values.get("doi")),
                pmid=_clean(values.get("pmid")),
                pmcid=_clean(values.get("pmcid")),
                authors=_split_authors(values.get("authors")),
                awardee_name=_clean(values.get("awardee_name")),
                representative_work_number=_clean(values.get("representative_work_number")),
                metadata=extras,
            ))
        except ValueError as exc:
            errors.append(f"第 {row_number} 行格式错误：{exc}")
    if errors:
        preview = "；".join(errors[:10])
        suffix = f"；另有 {len(errors) - 10} 项" if len(errors) > 10 else ""
        raise ValueError(preview + suffix)
    if not parsed:
        raise ValueError("文件中没有可导入的论文记录")
    return parsed


def _json_checksum(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def import_publication_records(
    connection: DbConnection,
    *,
    records: list[PublicationImportRecordInput],
    source_label: str,
    source_uri: str,
    source_checksum: str,
    source_sheet: str,
    actor_id: UUID,
    trace_id: str,
) -> PublicationImportResult:
    source_system_id = uuid4()
    connection.execute(
        """INSERT INTO smartlib.source_system
                  (source_system_id,code,name,owner_department,source_type,authorization_state,metadata)
             VALUES (%s,'knowledge_hub_publication_intake','知识中台论文导入',
                     '图书馆','manual','approved',%s)
             ON CONFLICT (code) DO UPDATE SET name=excluded.name
             RETURNING source_system_id""",
        (source_system_id, Jsonb({"intake_rule_version": IMPORT_RULE_VERSION})),
    )
    source_row = connection.execute(
        "SELECT source_system_id FROM smartlib.source_system WHERE code='knowledge_hub_publication_intake'"
    ).fetchone()
    source_system_id = source_row["source_system_id"]
    batch_id = uuid4()
    generated_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    dataset_version = f"web-publication-import-{generated_at}-{str(batch_id)[:8]}"
    connection.execute(
        """INSERT INTO smartlib.ingestion_batch
                  (batch_id,source_system_id,dataset_version,source_uri,
                   source_checksum,source_locator,expected_item_count,batch_state,
                   processing_rule_version,metadata,created_by,pipeline_key,source_kind)
             VALUES (%s,%s,%s,%s,%s,%s,%s,'imported',%s,%s,%s,'publication',%s)""",
        (
            batch_id, source_system_id, dataset_version, source_uri, source_checksum,
            Jsonb({"sheet": source_sheet} if not source_uri.startswith("manual:") else {}),
            len(records), IMPORT_RULE_VERSION,
            Jsonb({"source_label": source_label, "submission_contract": IMPORT_RULE_VERSION}), actor_id,
            "manual" if source_uri.startswith("manual:") else "file",
        ),
    )
    results: list[PublicationImportItemResult] = []
    for position, record in enumerate(records, start=1):
        eligible, reasons = automatic_eligibility(record)
        item_id = uuid4()
        normalized = {
            "title": record.title.strip(),
            "journal_or_conference": _clean(record.journal_name),
            "publication_year": record.publication_year,
            "doi": _normalize_doi(record.doi),
            "pmid": _clean(record.pmid),
            "pmcid": _clean(record.pmcid),
            "authors_raw_list": record.authors,
            "awardee_name": _clean(record.awardee_name),
            "automatic_verification_eligible": eligible,
            "eligibility_reasons": reasons,
        }
        raw = {**record.model_dump(mode="json"), **record.metadata}
        state = "normalized" if eligible else "manual_review"
        awardee = None
        if record.awardee_name:
            matches = connection.execute(
                """SELECT object_id FROM smartlib.knowledge_object
                    WHERE object_type='person' AND system_to='infinity'::timestamptz
                      AND canonical_name=%s ORDER BY object_id LIMIT 2""",
                (record.awardee_name.strip(),),
            ).fetchall()
            if len(matches) == 1:
                awardee = matches[0]["object_id"]
        locator = {"position": position} if source_uri.startswith("manual:") else {
            "sheet": source_sheet, "row": position
        }
        connection.execute(
            """INSERT INTO smartlib.ingestion_record
               (record_id,batch_id,source_locator,source_record_key,record_kind,raw_payload,
                normalized_payload,payload_checksum,processing_state,created_by)
               VALUES (%s,%s,%s,%s,'publication',%s,%s,%s,'processed',%s)""",
            (item_id,batch_id,Jsonb(locator),str(position),Jsonb(raw),Jsonb(normalized),
             _json_checksum(raw),actor_id),
        )
        connection.execute(
            """INSERT INTO smartlib.publication_intake_record(record_id,verification_state)
               VALUES (%s,%s)""", (item_id,state),
        )
        if record.representative_work_number or record.awardee_name:
            connection.execute(
                """INSERT INTO smartlib.representative_work_submission
                   (record_id,representative_work_number,awardee_name_raw,awardee_person_id)
                   VALUES (%s,%s,%s,%s)""",
                (item_id,record.representative_work_number,record.awardee_name,awardee),
            )
        results.append(PublicationImportItemResult(
            record_id=item_id,
            source_row_number=position,
            title=record.title,
            verification_state=state,
            automatic_verification_eligible=eligible,
            eligibility_reasons=reasons,
        ))
    connection.execute(
        """INSERT INTO audit.audit_event
                  (actor_id,action,resource_type,resource_id,decision,trace_id,details)
             VALUES (%s,'publication.import.submitted','ingestion_batch',%s,
                     'recorded',%s,%s)""",
        (actor_id, str(batch_id), trace_id, Jsonb({"source_label": source_label, "count": len(records)})),
    )
    automatic_count = sum(item.automatic_verification_eligible for item in results)
    return PublicationImportResult(
        batch_id=batch_id,
        dataset_version=dataset_version,
        source_label=source_label,
        accepted_count=len(results),
        automatic_eligible_count=automatic_count,
        manual_review_count=len(results) - automatic_count,
        items=results,
    )
