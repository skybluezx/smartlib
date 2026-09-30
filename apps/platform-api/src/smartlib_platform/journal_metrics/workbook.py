import hashlib
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from uuid import UUID, uuid5
from xml.etree import ElementTree

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
PACKAGE_NAMESPACE = UUID("d3b59b35-3e13-4f4f-bd0f-e1c60453bc77")

PROFILES = {
    "jcr-2025": {
        "sheet": "2025JCR分区",
        "header_row": 1,
        "edition_year": 2025,
        "metric_year": 2024,
        "headers": [
            "期刊名",
            "ISSN",
            "eISSN",
            "Category",
            "Total citation",
            "2024JIF",
            "Quartile",
            "JIF rank",
            "2023分区",
        ],
    },
    "jcr-2026": {
        "sheet": "2026 JCR",
        "header_row": 2,
        "edition_year": 2026,
        "metric_year": 2025,
        "headers": [
            "期刊名",
            "ISSN号",
            "eISSN号",
            "Wos学科信息",
            "引用索引版本",
            "总引用",
            "2025影响因子",
            "分区",
        ],
    },
}


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def normalize_issn(value: object) -> str | None:
    text = normalize_text(value).upper().replace("\N{EN DASH}", "-")
    if text in {"", "N/A", "#N/A", "NONE"}:
        return None
    compact = re.sub(r"[^0-9X]", "", text)
    if len(compact) != 8 or not re.fullmatch(r"[0-9]{7}[0-9X]", compact):
        raise ValueError(f"invalid ISSN: {value}")
    return f"{compact[:4]}-{compact[4:]}"


def parse_quartile(value: object) -> str | None:
    text = normalize_text(value).upper()
    if text in {"", "N/A", "#N/A", "NONE"}:
        return None
    if text not in {"Q1", "Q2", "Q3", "Q4"}:
        raise ValueError(f"invalid quartile: {value}")
    return text


def parse_rank(value: object) -> tuple[int | None, int | None]:
    text = normalize_text(value)
    if text in {"", "N/A", "#N/A"}:
        return None, None
    match = re.fullmatch(r"(\d+)\s*/\s*(\d+)", text)
    if match is None:
        raise ValueError(f"invalid rank: {value}")
    position, total = (int(part) for part in match.groups())
    if position < 1 or total < 1 or position > total:
        raise ValueError(f"invalid rank bounds: {value}")
    return position, total


def parse_categories(category_value: object, index_value: object | None = None) -> list[dict[str, object]]:
    categories = []
    for order, raw_category in enumerate(normalize_text(category_value).split(";"), start=1):
        text = normalize_text(raw_category)
        if not text:
            continue
        embedded = re.fullmatch(r"(.+?)\s*\(([^()]*)\)", text)
        if embedded:
            name = normalize_text(embedded.group(1))
            indexes = [normalize_text(value).upper() for value in embedded.group(2).split(",")]
        else:
            name = text
            indexes = [normalize_text(value).upper() for value in str(index_value or "").split(",")]
        categories.append(
            {
                "category_order": order,
                "category_name": name,
                "citation_indexes": [value for value in indexes if value],
            }
        )
    if not categories:
        raise ValueError("journal metric record has no category")
    return categories


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


def read_xlsx_rows(path: Path, sheet_name: str, width: int) -> list[list[object]]:
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        root = ElementTree.fromstring(archive.read(_sheet_path(archive, sheet_name)))
    rows: list[list[object]] = []
    for row_node in root.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
        values: list[object] = [""] * width
        for cell in row_node.findall(f"{{{MAIN_NS}}}c"):
            index = _column_index(cell.attrib["r"])
            if index >= width:
                continue
            cell_type = cell.attrib.get("t")
            value_node = cell.find(f"{{{MAIN_NS}}}v")
            if cell_type == "inlineStr":
                value: object = "".join(
                    node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t")
                )
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


def _optional_number(value: object, number_type: type[int] | type[float]) -> int | float | None:
    text = normalize_text(value)
    if text in {"", "N/A", "#N/A"}:
        return None
    return number_type(float(text))


def _optional_metric_number(value: object) -> tuple[float | None, bool]:
    text = normalize_text(value)
    if text in {"", "N/A", "#N/A"}:
        return None, False
    is_upper_bound = text.startswith("<")
    number_text = text[1:].strip() if is_upper_bound else text
    return float(number_text), is_upper_bound


def build_package(workbook_path: Path, profile_name: str) -> dict[str, object]:
    if profile_name not in PROFILES:
        raise ValueError(f"unsupported JCR workbook profile: {profile_name}")
    profile = PROFILES[profile_name]
    headers = profile["headers"]
    rows = read_xlsx_rows(workbook_path, str(profile["sheet"]), len(headers))
    header_index = int(profile["header_row"]) - 1
    if len(rows) <= header_index or rows[header_index] != headers:
        raise ValueError("JCR worksheet headers do not match the controlled profile")

    workbook_checksum = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
    dataset_version = f"{profile_name}-{workbook_checksum[:12]}"
    records = []
    for source_row_number, values in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(normalize_text(value) for value in values):
            continue
        raw_payload = dict(zip(headers, values, strict=True))
        if profile_name == "jcr-2025":
            categories = parse_categories(values[3])
            total_citations = _optional_number(values[4], int)
            impact_factor, impact_factor_is_upper_bound = _optional_metric_number(values[5])
            quartile = parse_quartile(values[6])
            rank_position, rank_total = parse_rank(values[7])
            previous_quartile = parse_quartile(values[8])
        else:
            categories = parse_categories(values[3], values[4])
            total_citations = _optional_number(values[5], int)
            impact_factor, impact_factor_is_upper_bound = _optional_metric_number(values[6])
            quartile = parse_quartile(values[7])
            rank_position, rank_total = None, None
            previous_quartile = None
        title = normalize_text(values[0])
        if not title:
            raise ValueError(f"row {source_row_number}: journal title is required")
        issn = normalize_issn(values[1])
        eissn = normalize_issn(values[2])
        canonical = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        row_checksum = hashlib.sha256(canonical.encode()).hexdigest()
        records.append(
            {
                "record_id": str(uuid5(PACKAGE_NAMESPACE, f"{dataset_version}:row:{source_row_number}")),
                "source_row_number": source_row_number,
                "journal": {
                    "canonical_title": title,
                    "normalized_title": title.casefold(),
                    "issn": issn,
                    "eissn": eissn,
                },
                "record_granularity": (
                    "journal_category" if profile_name == "jcr-2026" or len(categories) == 1 else "journal"
                ),
                "total_citations": total_citations,
                "impact_factor": impact_factor,
                "impact_factor_is_upper_bound": impact_factor_is_upper_bound,
                "quartile": quartile,
                "previous_quartile": previous_quartile,
                "rank_position": rank_position,
                "rank_total": rank_total,
                "categories": categories,
                "raw_payload": raw_payload,
                "row_checksum": row_checksum,
            }
        )

    return {
        "manifest": {
            "dataset_version": dataset_version,
            "metric_system": "jcr",
            "edition_year": profile["edition_year"],
            "metric_year": profile["metric_year"],
            "release_label": f"JCR {profile['edition_year']} local workbook intake",
            "publisher_name": "Clarivate",
            "source_file": str(workbook_path),
            "source_file_sha256": workbook_checksum,
            "source_sheet": profile["sheet"],
            "expected_record_count": len(records),
            "source_authority_status": "unverified",
            "license_authorization_state": "pending",
            "release_state": "staged",
            "profile": profile_name,
        },
        "records": records,
    }
