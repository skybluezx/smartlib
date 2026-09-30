"""Bounded, non-executing import of library ledgers; never reads the merge-report sheet."""

import csv
import hashlib
import io
import json
import posixpath
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

CATALOG = json.loads(Path(__file__).with_name("catalog.json").read_text())
BY_CODE = {item["code"]: item for item in CATALOG}
BY_NAME = {item["name"]: item for item in CATALOG}
MAX_UPLOAD = 20 * 1024 * 1024
MAX_EXPANDED = 80 * 1024 * 1024
MAX_ROWS = 10000
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def content_hash(category, fields):
    return hashlib.sha256(
        json.dumps([category, fields], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def normalize(category, fields, origin=None):
    if category not in BY_CODE:
        raise ValueError("未知工作表类型")
    spec = BY_CODE[category]
    if set(fields) - set(spec["fields"]):
        raise ValueError("存在不属于此工作表的字段")
    values = {key: str(fields.get(key, "")).strip() for key in spec["fields"]}
    if any(len(value) > 12000 for value in values.values()):
        raise ValueError("单元格文字超过 12000 字")
    title = values[spec["title_field"]]
    if not title:
        raise ValueError(f"缺少必填字段：{spec['title_field']}")
    warnings = []
    raw = values[spec["date_field"]]
    period = re.fullmatch(r"(\d{4}[./]\d{1,2}[./]\d{1,2})\s*[-—~至]\s*(?:\d{4}[./]\d{1,2}[./]\d{1,2})?", raw)
    if period:
        raw = period.group(1)
        warnings.append("区间时间按开始日期归年；原始区间完整保留")
    year = month = None
    precision = "unknown"
    match = re.fullmatch(r"(\d{4})(?:[-/.年](\d{1,2})(?:[-/.月](\d{1,2})日?)?月?)?年?", raw)
    if match:
        y, m, d = (int(v) if v else None for v in match.groups())
        try:
            date(y, m or 1, d or 1)
            if not 1900 <= y <= 2100:
                raise ValueError()
            year, month = y, m
            precision = "day" if d else "month" if m else "year"
        except ValueError:
            pass
    if precision == "unknown":
        warnings.append("时间未提供或无法确定；保留原值，不纳入按年统计")
    elif precision != "day":
        warnings.append("时间仅精确到" + ("年" if precision == "year" else "月"))
    audience = None
    if spec["audience_field"]:
        value = values[spec["audience_field"]]
        if re.fullmatch(r"\d+(?:\.0+)?", value) and float(value) <= 100000000:
            audience = int(float(value))
        else:
            warnings.append("参与人数未提供或不是明确的非负整数，不计入人次合计")
    return dict(
        category=category,
        title=title,
        fields=values,
        year=year,
        month=month,
        date_precision=precision,
        department=values.get(spec["department_field"], ""),
        audience=audience,
        warnings=warnings,
        origin=origin or {"file": "手工登记"},
        content_hash=content_hash(category, {k: v for k, v in values.items() if k != "序号"}),
    )


def safe_zip(data):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
        if len(entries) > 2500 or sum(v.file_size for v in entries) > MAX_EXPANDED:
            raise ValueError("压缩包展开体积或条目数超限")
        for entry in entries:
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or entry.flag_bits & 1:
                raise ValueError("不接受不安全路径或加密压缩文件")
        return archive
    except zipfile.BadZipFile as exc:
        raise ValueError("压缩文件损坏") from exc


def xml(data):
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("不接受带实体声明的工作簿")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("工作簿内容损坏") from exc


def xlsx_rows(data):
    with safe_zip(data) as archive:
        names = set(archive.namelist())
        book = xml(archive.read("xl/workbook.xml"))
        sheets = book.findall("s:sheets/s:sheet", NS)
        sheet = next((s for s in sheets if s.get("name") == "总表"), None)
        if sheet is None:
            if len(sheets) != 1 or sheets[0].get("name") == "报告":
                raise ValueError("多工作表文件必须提供“总表”，不会导入合并报告页")
            sheet = sheets[0]
        rel_id = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        relations = xml(archive.read("xl/_rels/workbook.xml.rels"))
        rel = next(
            (r for r in relations if r.get("Id") == rel_id and r.get("TargetMode") != "External"), None
        )
        if rel is None:
            raise ValueError("无法定位工作表")
        target = posixpath.normpath("xl/" + rel.get("Target", ""))
        if rel.get("Target", "").startswith("/"):
            target = rel.get("Target").lstrip("/")
        if not target.startswith("xl/") or target not in names:
            raise ValueError("工作表引用不合法")
        strings = []
        if "xl/sharedStrings.xml" in names:
            strings = ["".join(si.itertext()) for si in xml(archive.read("xl/sharedStrings.xml"))]
        date_styles = set()
        if "xl/styles.xml" in names:
            styles = xml(archive.read("xl/styles.xml"))
            custom = {
                int(n.get("numFmtId"))
                for n in styles.findall("s:numFmts/s:numFmt", NS)
                if re.search(r"[yd]", n.get("formatCode", ""), re.I)
            }
            date_styles = {
                i
                for i, xf in enumerate(styles.findall("s:cellXfs/s:xf", NS))
                if int(xf.get("numFmtId", 0))
                in set(range(14, 23))
                | set(range(27, 37))
                | {45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58}
                | custom
            }
        props = book.find("s:workbookPr", NS)
        base = (
            date(1904, 1, 1)
            if props is not None and props.get("date1904") in ("1", "true")
            else date(1899, 12, 30)
        )
        rows = []
        for row in xml(archive.read(target)).findall("s:sheetData/s:row", NS):
            cells = {}
            for cell in row.findall("s:c", NS):
                coordinate = re.match(r"([A-Z]+)", cell.get("r", "A1"))[1]
                index = 0
                for char in coordinate:
                    index = index * 26 + ord(char) - 64
                if index > 100:
                    raise ValueError("工作表列数超过 100")
                typ = cell.get("t")
                value = cell.findtext("s:v", "", NS)
                if typ == "s":
                    value = strings[int(value)] if value else ""
                elif typ == "inlineStr":
                    value = "".join(cell.find("s:is", NS).itertext())
                elif cell.get("s") and int(cell.get("s")) in date_styles and value:
                    try:
                        value = (base + timedelta(days=float(value))).isoformat()
                    except ValueError, OverflowError:
                        pass
                if cell.find("s:f", NS) is not None:
                    raise ValueError("存在公式单元格，请先另存为值后再导入（不使用缓存公式结果）")
                cells[index - 1] = value
            if cells:
                rows.append((int(row.get("r")), [cells.get(i, "") for i in range(max(cells) + 1)]))
            if len(rows) > MAX_ROWS + 100:
                raise ValueError("工作表行数超限")
        return sheet.get("name"), rows


def parse_upload(filename, data, category=""):
    if len(data) > MAX_UPLOAD or not data:
        raise ValueError("文件须非空且不超过 20 MB")
    if category and category not in BY_CODE:
        raise ValueError("未知工作表类型")
    files = []
    if filename.lower().endswith(".zip"):
        with safe_zip(data) as archive:
            for entry in archive.infolist():
                if entry.is_dir() or entry.filename.startswith("__MACOSX/"):
                    continue
                if not entry.filename.lower().endswith((".xlsx", ".csv")):
                    raise ValueError("ZIP 中只允许 XLSX 或 CSV 工作表")
                files.append((PurePosixPath(entry.filename).name, archive.read(entry)))
        if len(files) > 50:
            raise ValueError("一次最多 50 个工作表")
    else:
        files.append((PurePosixPath(filename).name, data))
    records, errors, skipped = [], [], 0
    seen = set()
    expanded = 0
    for name, content in files:
        try:
            if name.lower().endswith(".xlsx"):
                with safe_zip(content) as archive:
                    expanded += sum(e.file_size for e in archive.infolist())
                if expanded > MAX_EXPANDED:
                    raise ValueError("工作簿累计展开体积超限")
                sheet, rows = xlsx_rows(content)
            elif name.lower().endswith(".csv"):
                text = content.decode("utf-8-sig")
                sheet = "CSV"
                rows = list(enumerate(csv.reader(io.StringIO(text)), 1))
                if len(rows) > MAX_ROWS + 100:
                    raise ValueError("CSV 行数超限")
            else:
                raise ValueError("只接受 CSV、XLSX 或 ZIP 文件")
            spec = BY_CODE.get(category) or BY_NAME.get(Path(name).stem)
            if not spec:
                raise ValueError("无法识别业务类型，请选择类型或按工作表名称命名文件")
            header = None
            for row_num, row in rows:
                row = [str(v).strip() for v in row]
                if not any(row):
                    skipped += 1
                    continue
                if spec["title_field"] in row and spec["date_field"] in row:
                    if header:
                        skipped += 1
                    else:
                        nonempty = [v for v in row if v]
                        if len(nonempty) != len(set(nonempty)) or set(nonempty) - set(spec["fields"]):
                            raise ValueError("表头重复或含未定义字段，请按字段目录调整")
                        header = row
                    continue
                if header is None:
                    skipped += 1
                    continue
                # Repeated block titles from merged source files, not business entries.
                if sum(bool(v) for v in row) == 1 and row[0] in (spec["name"], spec["name"] + "表"):
                    skipped += 1
                    continue
                if any(row[len(header) :]) or any(
                    i < len(row) and row[i] for i, key in enumerate(header) if not key
                ):
                    errors.append({"file": name, "row": row_num, "message": "表头以外存在数据，请补全表头"})
                    continue
                fields = {key: row[i] if i < len(row) else "" for i, key in enumerate(header) if key}
                try:
                    record = normalize(spec["code"], fields, {"file": name, "sheet": sheet, "row": row_num})
                    # Serial number is source provenance, not business identity.
                    fingerprint = content_hash(
                        spec["code"], {k: v for k, v in record["fields"].items() if k != "序号"}
                    )
                    if fingerprint in seen:
                        raise ValueError("本批次存在完全重复事项（不含序号），请核实后再导入")
                    seen.add(fingerprint)
                    records.append(record)
                except ValueError as exc:
                    errors.append({"file": name, "row": row_num, "message": str(exc)})
                if len(records) + len(errors) > MAX_ROWS:
                    raise ValueError("一次最多导入 10000 条事项")
            if header is None:
                raise ValueError("未找到有效表头，至少需要标题与时间字段")
        except (ValueError, KeyError, IndexError, UnicodeError, csv.Error, zipfile.BadZipFile) as exc:
            errors.append({"file": name, "row": None, "message": str(exc) or "文件格式不完整"})
    if not records and not errors:
        errors.append({"file": filename, "row": None, "message": "未找到业务记录"})
    return {
        "records": records,
        "errors": errors,
        "skipped_rows": skipped,
        "warning_count": sum(bool(r["warnings"]) for r in records),
        "categories": {
            c["name"]: sum(r["category"] == c["code"] for r in records)
            for c in CATALOG
            if any(r["category"] == c["code"] for r in records)
        },
    }
