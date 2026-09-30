# ruff: noqa: RUF001
import argparse
import hashlib
import json
import re
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid5
from xml.etree import ElementTree

SHEET_NAME = "全部论著（283篇）"
EXPECTED_HEADERS = [
    "总序号",
    "获批人",
    "代表作序号",
    "作者（原文）",
    "题名",
    "期刊/会议",
    "年份",
    "卷（期）",
    "页码/文章号",
    "原始文献类型",
    "原始著录",
    "SCI表行号",
    "SCI序号",
    "SCI发表年份",
    "SCI论文名称",
    "SCI期刊名称",
    "SCI影响因子",
    "SCI通讯作者",
    "通讯作者单位",
    "SCI第一作者",
    "第一作者单位",
    "SCI文献类型",
    "UT号",
    "来源库",
    "DOI",
    "PMID",
    "PMCID",
    "全文入口URL",
    "出版社最终URL",
    "直接PDF URL",
    "其他候选URL",
    "PDF页数",
    "PDF SHA256",
]
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def normalize_doi(value: object) -> str:
    text = normalize_text(value).lower()
    return re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text).strip()


def normalize_pmid(value: object) -> str:
    return re.sub(r"^pmid:\s*", "", normalize_text(value), flags=re.IGNORECASE)


def normalize_pmcid(value: object) -> str:
    text = normalize_text(value).upper()
    if text and not text.startswith("PMC"):
        text = f"PMC{text}"
    return text


def _column_index(cell_reference: str) -> int:
    letters = re.match(r"[A-Z]+", cell_reference)
    if letters is None:
        raise ValueError(f"invalid cell reference: {cell_reference}")
    result = 0
    for character in letters.group(0):
        result = result * 26 + ord(character) - 64
    return result - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t")) for item in root]


def _sheet_path(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationship_id = None
    for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
        if sheet.attrib.get("name") == sheet_name:
            relationship_id = sheet.attrib[f"{{{REL_NS}}}id"]
            break
    if relationship_id is None:
        raise ValueError(f"missing worksheet: {sheet_name}")
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for relationship in relationships.findall(f"{{{PKG_REL_NS}}}Relationship"):
        if relationship.attrib.get("Id") == relationship_id:
            target = relationship.attrib["Target"].lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"
    raise ValueError(f"missing worksheet relationship: {sheet_name}")


def read_xlsx_rows(path: Path, sheet_name: str = SHEET_NAME) -> list[list[object]]:
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        root = ElementTree.fromstring(archive.read(_sheet_path(archive, sheet_name)))
    rows: list[list[object]] = []
    for row_node in root.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
        values: list[object] = [""] * len(EXPECTED_HEADERS)
        for cell in row_node.findall(f"{{{MAIN_NS}}}c"):
            index = _column_index(cell.attrib["r"])
            if index >= len(EXPECTED_HEADERS):
                continue
            cell_type = cell.attrib.get("t")
            value_node = cell.find(f"{{{MAIN_NS}}}v")
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t"))
            elif value_node is None:
                value = ""
            elif cell_type == "s":
                value = shared[int(value_node.text or "0")]
            elif cell_type in {"str", "e"}:
                value = value_node.text or ""
            else:
                numeric = value_node.text or ""
                try:
                    number = float(numeric)
                    value = int(number) if number.is_integer() else number
                except ValueError:
                    value = numeric
            values[index] = value
        rows.append(values)
    return rows


def build_package(workbook_path: Path, scholar_package_path: Path) -> dict[str, object]:
    workbook_bytes = workbook_path.read_bytes()
    workbook_sha256 = hashlib.sha256(workbook_bytes).hexdigest()
    rows = read_xlsx_rows(workbook_path)
    if not rows or rows[0] != EXPECTED_HEADERS:
        raise ValueError("publication worksheet headers do not match the controlled contract")
    data_rows = rows[1:]
    if len(data_rows) != 283:
        raise ValueError(f"expected 283 publication rows, got {len(data_rows)}")

    scholar_package = json.loads(scholar_package_path.read_text(encoding="utf-8"))
    scholar_manifest = scholar_package["manifest"]
    if scholar_manifest["source_file_sha256"] != workbook_sha256:
        raise ValueError("workbook checksum differs from the controlled scholar source")
    scholar_ids = {item["canonical_name"]: item["object_id"] for item in scholar_package["scholars"]}
    namespace = UUID(scholar_manifest["uuid_namespace"])
    dataset_version = "2026-nsf-representative-publications-publication-intake-v1"

    serials = [int(row[0]) for row in data_rows]
    if serials != list(range(1, 284)):
        raise ValueError("publication serial numbers must be exactly 1 through 283")
    required_field_errors = []
    for excel_row, row in enumerate(data_rows, start=2):
        for column_index, field_name in ((1, "获批人"), (2, "代表作序号"), (4, "题名")):
            if normalize_text(row[column_index]) == "":
                required_field_errors.append(f"row {excel_row}: {field_name}")
        if normalize_text(row[6]):
            year = int(row[6])
            if not 1500 <= year <= 2200:
                required_field_errors.append(f"row {excel_row}: 年份范围")
    if required_field_errors:
        raise ValueError(
            "missing or invalid required publication fields: " + "; ".join(required_field_errors)
        )
    missing_awardees = sorted({normalize_text(row[1]) for row in data_rows} - set(scholar_ids))
    if missing_awardees:
        raise ValueError(
            "publication awardees are not in the controlled scholar set: " + ", ".join(missing_awardees)
        )

    dois = [normalize_doi(row[24]) for row in data_rows]
    title_year_keys = [(normalize_text(row[4]).casefold(), str(row[6])) for row in data_rows]
    doi_counts = Counter(value for value in dois if value)
    title_year_counts = Counter(value for value in title_year_keys if value[0])
    items = []
    for excel_row, values in enumerate(data_rows, start=2):
        raw_payload = dict(zip(EXPECTED_HEADERS, values, strict=True))
        serial = int(values[0])
        awardee = normalize_text(values[1])
        doi = normalize_doi(values[24])
        title_year_key = (normalize_text(values[4]).casefold(), str(values[6]))
        quality_issues = []
        if not normalize_text(values[6]):
            quality_issues.append("missing_publication_year")
        normalized_payload = {
            "source_serial": serial,
            "representative_work_order": int(values[2]),
            "awardee_name": awardee,
            "awardee_person_id": scholar_ids[awardee],
            "authors_raw_list": [
                normalize_text(value) for value in str(values[3]).split(";") if normalize_text(value)
            ],
            "title": normalize_text(values[4]),
            "journal_or_conference": normalize_text(values[5]),
            "publication_year": int(values[6]) if str(values[6]).strip() else None,
            "volume_issue": normalize_text(values[7]),
            "pages_or_article_number": normalize_text(values[8]),
            "source_publication_type": normalize_text(values[9]),
            "doi": doi or None,
            "pmid": normalize_pmid(values[25]) or None,
            "pmcid": normalize_pmcid(values[26]) or None,
            "wos_ut": normalize_text(values[22]) or None,
            "duplicate_candidate_by_doi": bool(doi and doi_counts[doi] > 1),
            "duplicate_candidate_by_title_year": title_year_counts[title_year_key] > 1,
            "quality_issues": quality_issues,
            "requires_manual_review": bool(quality_issues),
        }
        canonical = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        items.append(
            {
                "record_id": str(uuid5(namespace, f"{dataset_version}:item:{serial}")),
                "external_id": f"NSF-PUB-{serial:04d}",
                "source_excel_row": excel_row,
                "source_serial": serial,
                "awardee_name_raw": str(values[1]),
                "awardee_person_id": scholar_ids[awardee],
                "raw_payload": raw_payload,
                "normalized_payload": normalized_payload,
                "row_checksum": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            }
        )

    stat = workbook_path.stat()
    return {
        "manifest": {
            "dataset_id": scholar_manifest["dataset_id"],
            "dataset_version": dataset_version,
            "synthetic": False,
            "purpose": "将283条代表性论著原始行登记为待核验记录，不直接生成已确认论文",
            "source_system_id": scholar_manifest["source_system_id"],
            "source_file": scholar_manifest["source_file"],
            "source_file_sha256": workbook_sha256,
            "source_file_size": stat.st_size,
            "source_file_modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            "sheet": SHEET_NAME,
            "used_range": "A1:AG284",
            "expected_item_count": 283,
            "unique_awardees": len({normalize_text(row[1]) for row in data_rows}),
            "rows_with_doi": sum(bool(value) for value in dois),
            "rows_missing_publication_year": sum(not normalize_text(row[6]) for row in data_rows),
            "duplicate_doi_groups": sum(count > 1 for count in doi_counts.values()),
            "duplicate_title_year_groups": sum(count > 1 for count in title_year_counts.values()),
            "initial_verification_state": "normalized",
            "batch_state": "verifying",
            "uuid_namespace": str(namespace),
        },
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare controlled publication intake package")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--scholars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = build_package(args.workbook, args.scholars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(package["manifest"], ensure_ascii=False))


if __name__ == "__main__":
    main()
