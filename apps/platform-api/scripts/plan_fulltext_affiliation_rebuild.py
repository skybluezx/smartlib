"""Build a reviewable affiliation and organization hierarchy rebuild plan."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from smartlib_platform.fulltext.affiliations import (
    NOISY_LEAD,
    ROOT_TERM,
    TRUNCATED_END,
    UNIT_START,
    ParsedAffiliation,
    discover_root_hints,
    identity_key,
    parse_affiliation,
)

PLAN_VERSION = "fulltext-affiliation-rebuild-plan-v3"
ORGANIZATION_NAMESPACE = UUID("ae53fe31-4873-4bf3-a6e6-e21aa7141dcf")


def organization_id(name: str) -> str:
    return str(uuid5(ORGANIZATION_NAMESPACE, f"organization:{identity_key(name)}"))


def load_jsonl_gzip(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def verified_records(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["record_id"]): item for item in payload["records"]}


def publication_imports(path: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            result[str(row["publication_id"])].append(str(row["record_id"]))
    return result


def existing_organization_names(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as source:
        return sorted({str(row["organization_name"]) for row in csv.DictReader(source)})


def authoritative_authors(record: dict[str, Any]) -> list[dict[str, Any]]:
    return list((record.get("enriched_metadata") or {}).get("authors") or [])


def choose_verification_record(
    import_ids: list[str],
    records: dict[str, dict[str, Any]],
    expected_author_count: int,
) -> dict[str, Any] | None:
    candidates = [records[value] for value in import_ids if value in records]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            len(authoritative_authors(item)) == expected_author_count,
            sum(bool(author.get("affiliations")) for author in authoritative_authors(item)),
        ),
    )


def prior_sources(author: dict[str, Any]) -> list[dict[str, Any]]:
    metadata_sources: list[dict[str, Any]] = []
    marker_sources: list[dict[str, Any]] = []
    evidence = author.get("affiliation_evidence") or {}
    for item in evidence.get("assignments") or []:
        method = str(item.get("method") or "")
        if method not in {"existing_author_affiliation", "fulltext_marker"}:
            continue
        target = metadata_sources if method == "existing_author_affiliation" else marker_sources
        target.append(
            {
                "kind": method,
                "raw": str(item.get("raw") or ""),
                "confidence": 0.96 if method == "existing_author_affiliation" else 0.90,
            }
        )
    # Per-author metadata is safer than reusing a full-text marker assignment.
    # Old marker extraction can collide when several superscript numbers are
    # adjacent in the PDF text layer, so retain it only when it yields a small,
    # credible set rather than assigning an entire paper's affiliation block.
    if metadata_sources:
        return metadata_sources
    distinct_marker_sources = {
        identity_key(item["raw"]): item for item in marker_sources if identity_key(item["raw"])
    }
    return list(distinct_marker_sources.values()) if len(distinct_marker_sources) <= 3 else []


def source_values(
    author: dict[str, Any],
    verified_author: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    verified = [
        {"kind": "verified_publisher_metadata", "raw": str(raw), "confidence": 0.98}
        for raw in ((verified_author or {}).get("affiliations") or [])
        if str(raw).strip()
    ]
    candidates = verified or prior_sources(author)
    unique: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = identity_key(item["raw"])
        if key:
            unique.setdefault(key, item)
    return list(unique.values())


def acceptable(item: ParsedAffiliation) -> bool:
    if len(item.canonical_name) > 190:
        return False
    if not ROOT_TERM.search(item.canonical_name):
        return False
    if NOISY_LEAD.search(item.canonical_name) or TRUNCATED_END.search(item.canonical_name):
        return False
    return not {
        "possible_address_contamination",
        "parent_not_resolved",
        "context_contamination",
        "truncated_institution",
        "generic_or_contextual_root",
        "address_tail_not_resolved",
    }.intersection(item.issues)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--existing-affiliations", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--assignments-csv", type=Path, required=True)
    args = parser.parse_args()

    corpus = load_jsonl_gzip(args.corpus)
    records = verified_records(args.verification)
    imports = publication_imports(args.mapping)
    existing_names = existing_organization_names(args.existing_affiliations)

    work: list[dict[str, Any]] = []
    raw_values: list[str] = []
    for publication in corpus:
        verification = choose_verification_record(
            imports.get(str(publication["publication_id"]), []),
            records,
            len(publication["authors"]),
        )
        verified_authors = authoritative_authors(verification or {})
        aligned = len(verified_authors) == len(publication["authors"])
        authors: list[dict[str, Any]] = []
        for index, author in enumerate(publication["authors"]):
            sources = source_values(author, verified_authors[index] if aligned else None)
            raw_values.extend(item["raw"] for item in sources)
            authors.append({"record": author, "sources": sources})
        work.append(
            {
                "publication": publication,
                "verification_record_id": (
                    str(verification["record_id"]) if verification else None
                ),
                "verified_author_alignment": aligned,
                "authors": authors,
            }
        )

    clean_existing_roots = [
        name
        for name in existing_names
        if ROOT_TERM.search(name)
        and not UNIT_START.search(name)
        and len(name) <= 140
        and not re.search(r"\b\d{5,6}\b", name)
    ]
    root_hints = discover_root_hints([*raw_values, *clean_existing_roots])

    counters: Counter[str] = Counter()
    organizations: dict[str, dict[str, Any]] = {}
    assignments: list[dict[str, Any]] = []
    publication_records: list[dict[str, Any]] = []
    for item in work:
        publication = item["publication"]
        publication_assignment_count = 0
        publication_author_count = len(item["authors"])
        for author_item in item["authors"]:
            author = author_item["record"]
            parsed: dict[str, tuple[ParsedAffiliation, dict[str, Any]]] = {}
            rejected: list[dict[str, Any]] = []
            for source in author_item["sources"]:
                for affiliation in parse_affiliation(
                    source["raw"],
                    root_hints=root_hints,
                    source_confidence=float(source["confidence"]),
                ):
                    if acceptable(affiliation):
                        parsed.setdefault(identity_key(affiliation.canonical_name), (affiliation, source))
                    else:
                        rejected.append(
                            {
                                "raw": affiliation.raw,
                                "canonical_name": affiliation.canonical_name,
                                "issues": list(affiliation.issues),
                            }
                        )
            if parsed and {value[1]["kind"] for value in parsed.values()} == {"fulltext_marker"}:
                if len(parsed) > 3:
                    rejected.extend(
                        {
                            "raw": value[0].raw,
                            "canonical_name": value[0].canonical_name,
                            "issues": ["excessive_marker_scope"],
                        }
                        for value in parsed.values()
                    )
                    parsed = {}
            organization_ids: list[str] = []
            parsed_values: list[dict[str, Any]] = []
            for affiliation, source in parsed.values():
                hierarchy_ids = [organization_id(name) for name in affiliation.hierarchy]
                organization_ids.append(hierarchy_ids[-1])
                for level, (name, object_id) in enumerate(
                    zip(affiliation.hierarchy, hierarchy_ids, strict=True)
                ):
                    organization = organizations.setdefault(
                        object_id,
                        {
                            "object_id": object_id,
                            "canonical_name": name,
                            "identity_key": identity_key(name),
                            "level": "root" if level == 0 else "branch",
                            "parent_id": hierarchy_ids[level - 1] if level else None,
                            "source_raw_examples": [],
                        },
                    )
                    if level == 0:
                        organization["level"] = "root"
                        organization["parent_id"] = None
                    examples = organization["source_raw_examples"]
                    if affiliation.raw not in examples and len(examples) < 5:
                        examples.append(affiliation.raw)
                parsed_values.append(
                    {
                        "canonical_name": affiliation.canonical_name,
                        "organization_id": hierarchy_ids[-1],
                        "root_name": affiliation.root_name,
                        "root_organization_id": hierarchy_ids[0],
                        "hierarchy": list(affiliation.hierarchy),
                        "hierarchy_ids": hierarchy_ids,
                        "address": affiliation.address,
                        "raw": affiliation.raw,
                        "source_kind": source["kind"],
                        "confidence": affiliation.confidence,
                        "issues": list(affiliation.issues),
                    }
                )
            organization_ids = sorted(set(organization_ids))
            if organization_ids:
                counters["authors_with_affiliations"] += 1
                counters["author_organization_assignments"] += len(organization_ids)
                publication_assignment_count += len(organization_ids)
            else:
                counters["authors_without_affiliations"] += 1
            counters["rejected_candidates"] += len(rejected)
            assignments.append(
                {
                    "publication_id": str(publication["publication_id"]),
                    "publication_title": publication["publication_title"],
                    "publication_authorship_id": str(author["publication_authorship_id"]),
                    "author_order": int(author["author_order"]),
                    "author_name": author["author_name_raw"],
                    "person_object_id": author.get("person_object_id"),
                    "organizations": parsed_values,
                    "rejected_candidates": rejected,
                    "source_count": len(author_item["sources"]),
                }
            )
        counters["publications_reviewed"] += 1
        counters["publications_with_affiliations"] += publication_assignment_count > 0
        counters["publications_without_affiliations"] += publication_assignment_count == 0
        counters["authors_reviewed"] += publication_author_count
        counters["fulltext_characters_reviewed"] += len(publication["text"])
        publication_records.append(
            {
                "publication_id": str(publication["publication_id"]),
                "title": publication["publication_title"],
                "content_checksum": publication["content_checksum"],
                "text_length": len(publication["text"]),
                "authors": publication_author_count,
                "organization_assignments": publication_assignment_count,
                "verification_record_id": item["verification_record_id"],
                "verified_author_alignment": item["verified_author_alignment"],
            }
        )

    counters["organizations_total"] = len(organizations)
    counters["root_organizations"] = sum(
        value["level"] == "root" for value in organizations.values()
    )
    counters["branch_organizations"] = sum(
        value["level"] == "branch" for value in organizations.values()
    )
    counters["hierarchy_relations"] = sum(
        value["parent_id"] is not None for value in organizations.values()
    )
    report = {
        "schema_version": PLAN_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "counts": dict(counters),
        "root_hints": list(root_hints),
        "organizations": sorted(
            organizations.values(), key=lambda value: (value["level"], value["canonical_name"])
        ),
        "assignments": assignments,
        "publications": publication_records,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with args.assignments_csv.open("w", encoding="utf-8", newline="") as output:
        fields = [
            "publication_id",
            "publication_title",
            "author_order",
            "author_name",
            "canonical_name",
            "root_name",
            "address",
            "source_kind",
            "confidence",
            "issues",
            "raw",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for assignment in assignments:
            for organization in assignment["organizations"]:
                writer.writerow(
                    {
                        **{field: assignment.get(field) for field in fields},
                        **{field: organization.get(field) for field in fields},
                        "issues": ";".join(organization["issues"]),
                    }
                )
    print(json.dumps(report["counts"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
