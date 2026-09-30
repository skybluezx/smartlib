#!/usr/bin/env python3
# ruff: noqa: RUF001
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

NAMESPACE = UUID("af4bd264-8687-4d16-bd72-8db42d2723c5")
DATASET_ID = "authoritative-discipline-taxonomies"
DATASET_VERSION = "2026-09-04-v1"


def stable_id(kind: str, key: str) -> str:
    return str(uuid5(NAMESPACE, f"{DATASET_ID}:{DATASET_VERSION}:{kind}:{key}"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def checksum(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_package(source_root: Path) -> dict[str, object]:
    preview = source_root / "preview"
    source_manifest = json.loads((source_root / "source_manifest.json").read_text(encoding="utf-8"))
    source_records = {item["path"]: item for item in source_manifest["records"]}

    systems = [
        {
            "source_system_id": stable_id("source-system", "moe"),
            "code": "moe_discipline_catalog",
            "name": "国务院学位委员会、教育部学科专业目录",
            "owner_department": "国务院学位委员会、教育部",
            "source_type": "repository",
            "authorization_state": "approved",
        },
        {
            "source_system_id": stable_id("source-system", "nsfc"),
            "code": "nsfc_application_codes",
            "name": "国家自然科学基金申请代码",
            "owner_department": "国家自然科学基金委员会",
            "source_type": "repository",
            "authorization_state": "approved",
        },
        {
            "source_system_id": stable_id("source-system", "samr"),
            "code": "samr_gbt_13745",
            "name": "GB/T 13745-2009 学科分类与代码",
            "owner_department": "国家市场监督管理总局、国家标准化管理委员会",
            "source_type": "repository",
            "authorization_state": "approved",
        },
    ]
    system_by_scheme = {
        "MOE_GRADUATE_DISCIPLINE_2022": systems[0],
        "MOE_PREVIOUS_DISCIPLINE": systems[0],
        "NSFC_APPLICATION_CODE_2026": systems[1],
        "GBT_13745_2009": systems[2],
    }
    schemes = [
        {
            "scheme": "MOE_GRADUATE_DISCIPLINE_2022",
            "name": "研究生教育学科专业目录（2022年）",
            "version": "2022（2023年起实施，含2025调整对应关系）",
            "source_path": "sources/moe/研究生教育学科专业目录_2022.pdf",
            "quality_state": "validated",
            "description": "高校学科归属主干，含学科门类、一级学科和专业学位类别。",
        },
        {
            "scheme": "MOE_PREVIOUS_DISCIPLINE",
            "name": "教育部原学科专业目录对应项",
            "version": "2025调整对应关系中的原目录口径",
            "source_path": "sources/moe/2025学科专业调整对应关系表.html",
            "quality_state": "validated",
            "description": "仅用于保留原目录名称、代码及其与2022目录的对应关系。",
        },
        {
            "scheme": "NSFC_APPLICATION_CODE_2026",
            "name": "国家自然科学基金申请代码（2026年）",
            "version": "2026",
            "source_path": "sources/nsfc/99885.html",
            "quality_state": "warning",
            "description": "科研项目和学者研究方向的细粒度分类；官方图片经OCR结构化，逐条保留识别质量标记。",
        },
        {
            "scheme": "GBT_13745_2009",
            "name": "GB/T 13745-2009 学科分类与代码",
            "version": "2009",
            "source_path": "sources/samr/科技统计工作文件_2024版_含GBT13745摘选.pdf",
            "quality_state": "warning",
            "description": "本次仅纳入带正式编码的一、二级记录；三级解析词项因数量口径差异继续隔离。",
        },
    ]

    objects: list[dict[str, object]] = []
    object_by_key: dict[tuple[str, str], str] = {}

    def add_object(
        scheme: str,
        code: str,
        name: str,
        level: int | str,
        node_type: str,
        parent_code: str,
        source_path: str,
        quality_state: str,
        attributes: dict[str, object] | None = None,
    ) -> str:
        key = (scheme, code)
        if key in object_by_key:
            existing = next(item for item in objects if item["object_id"] == object_by_key[key])
            if existing["canonical_name"] != name:
                raise ValueError(f"同一体系代码对应多个名称: {scheme} {code}")
            return object_by_key[key]
        object_id = stable_id("discipline", f"{scheme}:{code}")
        item = {
            "object_id": object_id,
            "object_type": "discipline",
            "canonical_name": name.strip(),
            "description": f"{node_type}；代码 {code}",
            "quality_state": quality_state,
            "review_state": "approved",
            "scheme": scheme,
            "code": code,
            "level": int(level),
            "node_type": node_type,
            "parent_code": parent_code,
            "source_path": source_path,
            "attributes": attributes or {},
        }
        objects.append(item)
        object_by_key[key] = object_id
        return object_id

    for scheme in schemes:
        scheme_id = stable_id("scheme", scheme["scheme"])
        scheme["object_id"] = scheme_id
        scheme["source_system_id"] = system_by_scheme[scheme["scheme"]]["source_system_id"]
        objects.append(
            {
                "object_id": scheme_id,
                "object_type": "concept",
                "canonical_name": scheme["name"],
                "description": scheme["description"],
                "quality_state": scheme["quality_state"],
                "review_state": "approved",
                "scheme": scheme["scheme"],
                "code": scheme["scheme"],
                "level": 0,
                "node_type": "分类体系",
                "parent_code": "",
                "source_path": scheme["source_path"],
                "attributes": {"scheme_version": scheme["version"], "kind": "vocabulary_scheme"},
            }
        )

    moe_source = "sources/moe/研究生教育学科专业目录_2022.pdf"
    for row in read_csv(preview / "教育部研究生教育学科专业目录_2022_预览.csv"):
        add_object(
            row["scheme"],
            row["code"],
            row["name"],
            row["level"],
            row["node_type"],
            row["parent_code"],
            moe_source,
            "validated",
            {"degree_level": row["degree_level"], "extraction_status": row["review_status"]},
        )

    mapping_source = "sources/moe/2025学科专业调整对应关系表.html"
    field_rows = read_csv(preview / "教育部8类专业学位领域对应关系_2025_预览.csv")
    for row in field_rows:
        add_object(
            "MOE_GRADUATE_DISCIPLINE_2022",
            row["current_field_code"],
            row["current_field_name"],
            3,
            "专业学位领域",
            row["current_field_code"][:4],
            mapping_source,
            "validated",
            {"effective_mapping_notice": "2025"},
        )

    correspondence = read_csv(preview / "教育部学科专业调整对应关系_2025_预览.csv")
    legacy_entries: dict[str, str] = {}
    for row in correspondence:
        legacy_entries[row["previous_code"]] = row["previous_name"]
    for row in field_rows:
        legacy_entries[row["previous_field_code"]] = row["previous_field_name"]
    for code, name in sorted(legacy_entries.items()):
        add_object(
            "MOE_PREVIOUS_DISCIPLINE",
            code,
            name,
            2 if len(code) <= 4 else 3,
            "原目录对应项",
            "",
            mapping_source,
            "validated",
            {"historical": True},
        )

    for row in read_csv(preview / "国自然申请代码_2026_OCR预览.csv"):
        flags = [flag for flag in row["ocr_flags"].split(";") if flag]
        add_object(
            row["scheme"],
            row["code"],
            row["name"],
            row["level"],
            "申请代码",
            row["parent_code"],
            f"sources/nsfc/images/{row['source_image']}",
            "warning" if flags else "validated",
            {
                "department_code": row["department_code"],
                "department_name": row["department_name"],
                "source_column": int(row["source_column"]),
                "ocr_flags": flags,
                "extraction_status": row["review_status"],
            },
        )

    for row in read_csv(preview / "GBT13745_2009_一二级编码预览.csv"):
        add_object(
            row["scheme"],
            row["code"],
            row["name"],
            row["level"],
            f"{row['level']}级学科",
            row["parent_code"],
            "sources/samr/科技统计工作文件_2024版_含GBT13745摘选.pdf",
            "warning",
            {
                "source_form": row["source_form"],
                "scope_note": "仅正式编码记录；三级词项未导入",
                "description_from_source": row["description"],
            },
        )

    relations: list[dict[str, object]] = []

    def add_relation(subject_id: str, predicate: str, object_id: str, scheme: str, attributes=None):
        key = f"{subject_id}:{predicate}:{object_id}"
        relations.append(
            {
                "relation_id": stable_id("relation", key),
                "subject_id": subject_id,
                "predicate": predicate,
                "object_id": object_id,
                "scheme": scheme,
                "attributes": attributes or {},
            }
        )

    scheme_ids = {item["scheme"]: item["object_id"] for item in schemes}
    for item in objects:
        if item["object_type"] != "discipline":
            continue
        add_relation(scheme_ids[item["scheme"]], "taxonomy.contains", item["object_id"], item["scheme"])
        if item["parent_code"]:
            parent = object_by_key.get((item["scheme"], str(item["parent_code"])))
            if parent is None:
                raise ValueError(f"缺少父级: {item['scheme']} {item['code']} -> {item['parent_code']}")
            add_relation(item["object_id"], "taxonomy.broader", parent, item["scheme"])

    for row in correspondence:
        current = object_by_key[("MOE_GRADUATE_DISCIPLINE_2022", row["current_code"])]
        previous = object_by_key[("MOE_PREVIOUS_DISCIPLINE", row["previous_code"])]
        add_relation(
            current,
            "taxonomy.replaces",
            previous,
            "MOE_GRADUATE_DISCIPLINE_2022",
            {"notice": "2025"},
        )
    for row in field_rows:
        current = object_by_key[("MOE_GRADUATE_DISCIPLINE_2022", row["current_field_code"])]
        previous = object_by_key[("MOE_PREVIOUS_DISCIPLINE", row["previous_field_code"])]
        add_relation(
            current,
            "taxonomy.replaces",
            previous,
            "MOE_GRADUATE_DISCIPLINE_2022",
            {"notice": "2025"},
        )

    for item in objects:
        system = system_by_scheme[item["scheme"]]
        item["source_system_id"] = system["source_system_id"]
        item["source_reference_id"] = stable_id("source-reference", item["object_id"])
        item["outbox_event_id"] = stable_id("object-outbox", item["object_id"])
        checksum_fields = ("scheme", "code", "canonical_name", "attributes")
        item["content_checksum"] = checksum({key: item[key] for key in checksum_fields})
    for relation in relations:
        relation["evidence_id"] = stable_id("scheme-evidence", relation["scheme"])
        relation["outbox_event_id"] = stable_id("relation-outbox", relation["relation_id"])

    object_counts = Counter(str(item["object_type"]) for item in objects)
    discipline_counts = Counter(
        str(item["scheme"]) for item in objects if item["object_type"] == "discipline"
    )
    relation_counts = Counter(str(item["predicate"]) for item in relations)
    return {
        "manifest": {
            "dataset_id": DATASET_ID,
            "dataset_version": DATASET_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "synthetic": False,
            "visibility": "public",
            "review_state": "approved",
            "object_counts": dict(object_counts),
            "discipline_counts": dict(discipline_counts),
            "relation_counts": dict(relation_counts),
            "source_file_count": len(source_manifest["records"]),
            "excluded": {
                "scheme": "GBT_13745_2009",
                "level": 3,
                "records": 2306,
                "reason": "解析数量与来源声明口径存在差异，继续隔离待核清",
            },
        },
        "source_systems": systems,
        "schemes": schemes,
        "source_files": list(source_records.values()),
        "objects": objects,
        "relations": relations,
    }


def validate_package(package: dict[str, object]) -> None:
    manifest = package["manifest"]
    objects = package["objects"]
    relations = package["relations"]
    if manifest["synthetic"] is not False:
        raise ValueError("学科分类受控导入包不得标记为虚拟数据")
    if manifest["object_counts"] != dict(Counter(item["object_type"] for item in objects)):
        raise ValueError("对象计数不一致")
    if manifest["relation_counts"] != dict(Counter(item["predicate"] for item in relations)):
        raise ValueError("关系计数不一致")
    object_ids = {UUID(item["object_id"]) for item in objects}
    if len(object_ids) != len(objects):
        raise ValueError("对象稳定标识重复")
    relation_ids = {UUID(item["relation_id"]) for item in relations}
    if len(relation_ids) != len(relations):
        raise ValueError("关系稳定标识重复")
    if any(item["scheme"] == "GBT_13745_2009" and int(item["level"]) == 3 for item in objects):
        raise ValueError("GB/T三级解析词项不得进入正式导入包")
    for relation in relations:
        if UUID(relation["subject_id"]) not in object_ids or UUID(relation["object_id"]) not in object_ids:
            raise ValueError(f"关系端点不存在: {relation['relation_id']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成权威学科分类受控导入包")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = build_package(args.source_root)
    validate_package(package)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "prepared", **package["manifest"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
