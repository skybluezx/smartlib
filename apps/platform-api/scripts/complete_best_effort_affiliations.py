"""Complete unresolved paper affiliations using transparent best-effort inference.

The conservative v3 plan intentionally left papers empty when no author-level
publisher metadata was safe.  This pass mines the full-text front matter,
prefers author-marker matches, and falls back to a clearly labelled
publication-scope inference so the demo can expose a substantially complete
institution network without pretending every assignment was verified.
"""

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

from smartlib_platform.fulltext.affiliations import (
    NOISY_LEAD,
    ROOT_TERM,
    TRUNCATED_END,
    UNIT_START,
    ParsedAffiliation,
    identity_key,
    parse_affiliation,
)

PLAN_VERSION = "fulltext-affiliation-rebuild-plan-v4-best-effort"
ORG_LINE = re.compile(
    r"\b(?:university|hospital|institute|academy|college|school|faculty|department|"
    r"division|clinic|laborator(?:y|ies)|centre|center)\b|"
    r"(?:大学|医院|学院|研究所|科学院|实验室|中心|附属|护理部|科室|学部|系)",
    re.I,
)
ADDRESS_SIGNAL = re.compile(
    r"\b(?:China|USA|United States|United Kingdom|Singapore|Japan|Korea|"
    r"Germany|France|Italy|Australia|Canada)\b|(?:中国|省|市|区|路|号)|\b\d{5,6}\b",
    re.I,
)
BAD_CONTEXT = re.compile(
    r"\b(?:references?|acknowledgements?|introduction|methods?|results?|discussion|"
    r"ethics|copyright|published by|downloaded from|clinical trial|committee|"
    r"supplementary|publisher's note|edited by|reviewed by|these authors|contributed equally|"
    r"patients?|mice|cells?|expression|significant|incubated|assay|software|"
    r"received|accepted|published|such as|in the control group|online database|"
    r"mitochondrial|tumorigenesis|cardiovascular diseases|enzymatic activity|"
    r"oxidative phosphorylation|intervention group|first authorship)\b|"
    r"(?:参考文献|伦理委员会|研究对象|纳入标准)",
    re.I,
)
MARKER_PREFIX = re.compile(
    r"^\s*([0-9*†‡#+,;\s]{1,18})\s*[.)]?\s*(?=[A-Za-z\u3400-\u9fff])"
)
SUPERSCRIPT_TRANSLATION = str.maketrans("¹²³⁴⁵⁶⁷⁸⁹⁰", "1234567890")


def compact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def marker_tokens(value: object) -> set[str]:
    text = str(value or "").translate(SUPERSCRIPT_TRANSLATION)
    return {
        token.casefold()
        for token in re.findall(r"\d+|[a-z]|[*†‡#+]", text, re.I)
        if token
    }


def author_markers(name: str, header: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9\u3400-\u9fff]+", compact(name))
    if not words:
        return set()
    pattern = re.compile(r"(?<!\w)" + r"[\s.\-]*".join(map(re.escape, words)) + r"(?!\w)", re.I)
    result: set[str] = set()
    for match in pattern.finditer(header):
        tail = header[match.end() : match.end() + 28]
        marker_region = re.split(r"[,;\n&]", tail, maxsplit=1)[0]
        if len(marker_region) <= 18:
            result.update(marker_tokens(marker_region))
    return result


def candidate_chunks(text: str) -> list[str]:
    """Return likely front-matter affiliation rows, joining short PDF wraps."""
    # Restrict this inference to the first rendered page. Searching later pages
    # confuses study sites, suppliers and institutions cited in references with
    # author affiliations.
    first_page = text.split("\f", 1)[0][:18000]
    lines: list[str] = []
    for raw_line in first_page.splitlines()[:160]:
        segments = [compact(value) for value in re.split(r"\s{3,}", raw_line) if compact(value)]
        index = 0
        while index < len(segments):
            segment = segments[index]
            if (
                re.fullmatch(r"[0-9*†‡#+,;]+", segment)
                and index + 1 < len(segments)
                and ORG_LINE.search(segments[index + 1])
            ):
                lines.append(f"{segment} {segments[index + 1]}")
                index += 2
            else:
                lines.append(segment)
                index += 1
    output: list[str] = []
    for line in lines:
        if not line or len(line) > 750 or not ORG_LINE.search(line):
            continue
        prefix = MARKER_PREFIX.match(line)
        looks_like_signature = bool(
            prefix
            or UNIT_START.search(re.sub(r"^\s*(?:\d+|[*†‡#+])+\s*[.)]?\s*", "", line))
            or ADDRESS_SIGNAL.search(line)
            or re.search(r"(?:作者单位|通信作者|affiliation|address for correspondence)", line, re.I)
            or (
                len(line) <= 180
                and re.fullmatch(
                    r"(?:The\s+)?[A-Z][^.!?]{2,150}(?:University|Hospital|Institute|Academy)",
                    line,
                )
            )
        )
        if not looks_like_signature or BAD_CONTEXT.search(line):
            continue
        chunk = line.replace("Affliated", "Affiliated")
        if chunk not in output:
            output.append(chunk)
    return output


def acceptable_best_effort(item: ParsedAffiliation) -> bool:
    if not (5 <= len(item.canonical_name) <= 220):
        return False
    if not ROOT_TERM.search(item.canonical_name):
        return False
    if NOISY_LEAD.search(item.canonical_name) or TRUNCATED_END.search(item.canonical_name):
        return False
    return not {
        "context_contamination",
        "truncated_institution",
        "generic_or_contextual_root",
        "address_tail_not_resolved",
    }.intersection(item.issues)


def repair_or_reject(
    affiliation: ParsedAffiliation,
    raw: str,
    root_hints: list[str],
) -> ParsedAffiliation | None:
    suspicious = bool(
        BAD_CONTEXT.search(affiliation.canonical_name)
        or re.search(r"\[\d+(?:\s*[-,]\s*\d+)*\]", affiliation.canonical_name)
        or re.search(r"^(?:and|of|b|c)\s+", affiliation.canonical_name, re.I)
        or re.search(r"\b(?:Liu|Wang|Zhang|Li)\s+[A-Z]\b", affiliation.canonical_name)
        or re.search(
            r"^(?:China\s+\d|Beijing,|College,|Education\)|public teaching|Chuhuai\s+Wang)|"
            r"\b(?:CYP|dasatinib)\b|\buniversity,\s+dalian\s+medical\s+university$|"
            r"^(?:medical university\)|national university|the institute of heart|"
            r"the people(?:'|\u2019)s hospital|liver diseases academy|"
            r"institute of liver diseases)$",
            affiliation.canonical_name,
            re.I,
        )
    )
    if not suspicious:
        return affiliation
    normalized = identity_key(affiliation.canonical_name)
    matches = [
        hint
        for hint in root_hints
        if len(identity_key(hint)) >= 12 and identity_key(hint) in normalized
    ]
    if not matches:
        return None
    root = max(matches, key=lambda value: len(identity_key(value)))
    return ParsedAffiliation(
        raw=raw,
        canonical_name=root,
        hierarchy=(root,),
        address=affiliation.address,
        confidence=min(affiliation.confidence, 0.46),
        issues=tuple(sorted(set(affiliation.issues) | {"contaminated_branch_reduced_to_known_root"})),
    )


def parsed_candidates(text: str, root_hints: list[str]) -> list[tuple[ParsedAffiliation, str, set[str]]]:
    candidates: dict[str, tuple[ParsedAffiliation, str, set[str]]] = {}
    for raw in candidate_chunks(text):
        for affiliation in parse_affiliation(raw, root_hints=root_hints, source_confidence=0.72):
            prefix = MARKER_PREFIX.match(affiliation.raw)
            markers = marker_tokens(prefix.group(1)) if prefix else set()
            affiliation = repair_or_reject(affiliation, raw, root_hints)
            if affiliation and acceptable_best_effort(affiliation):
                candidates.setdefault(identity_key(affiliation.canonical_name), (affiliation, raw, markers))
    values = list(candidates.values())
    # If a full branch is present, do not also treat its root-only echo as an
    # independent paper affiliation. The hierarchy will still preserve it.
    root_keys = {
        identity_key(value[0].root_name)
        for value in values
        if identity_key(value[0].canonical_name) != identity_key(value[0].root_name)
    }
    values = [
        value
        for value in values
        if not (
            identity_key(value[0].canonical_name) == identity_key(value[0].root_name)
            and identity_key(value[0].canonical_name) in root_keys
        )
    ]
    return values[:10]


def prior_author_candidates(
    author: dict[str, Any], root_hints: list[str]
) -> list[tuple[ParsedAffiliation, str, set[str]]]:
    output: dict[str, tuple[ParsedAffiliation, str, set[str]]] = {}
    evidence = author.get("affiliation_evidence") or {}
    for item in evidence.get("assignments") or []:
        raw = compact(item.get("raw"))
        if not raw:
            continue
        for affiliation in parse_affiliation(raw, root_hints=root_hints, source_confidence=0.68):
            affiliation = repair_or_reject(affiliation, raw, root_hints)
            if affiliation and acceptable_best_effort(affiliation):
                output.setdefault(identity_key(affiliation.canonical_name), (affiliation, raw, set()))
    return list(output.values())[:6]


def organization_record(affiliation: ParsedAffiliation, raw: str) -> list[dict[str, Any]]:
    # IDs are already deterministic in the base plan; importing here avoids
    # duplicating the namespace contract.
    from plan_fulltext_affiliation_rebuild import organization_id

    ids = [organization_id(name) for name in affiliation.hierarchy]
    return [
        {
            "object_id": object_id,
            "canonical_name": name,
            "identity_key": identity_key(name),
            "level": "root" if index == 0 else "branch",
            "parent_id": ids[index - 1] if index else None,
            "source_raw_examples": [raw],
            "provisional_best_effort": True,
            "needs_confirmation": True,
        }
        for index, (name, object_id) in enumerate(zip(affiliation.hierarchy, ids, strict=True))
    ]


def assignment_value(
    affiliation: ParsedAffiliation,
    raw: str,
    *,
    method: str,
    confidence: float,
) -> dict[str, Any]:
    from plan_fulltext_affiliation_rebuild import organization_id

    ids = [organization_id(name) for name in affiliation.hierarchy]
    return {
        "canonical_name": affiliation.canonical_name,
        "organization_id": ids[-1],
        "root_name": affiliation.root_name,
        "root_organization_id": ids[0],
        "hierarchy": list(affiliation.hierarchy),
        "hierarchy_ids": ids,
        "address": affiliation.address,
        "raw": raw,
        "source_kind": method,
        "confidence": confidence,
        "issues": sorted(set(affiliation.issues) | {"best_effort_inference"}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-plan", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--assignments-csv", type=Path, required=True)
    args = parser.parse_args()

    plan = json.loads(args.base_plan.read_text(encoding="utf-8"))
    with gzip.open(args.corpus, "rt", encoding="utf-8") as source:
        corpus = {str(item["publication_id"]): item for line in source if (item := json.loads(line))}

    organizations = {item["object_id"]: item for item in plan["organizations"]}
    assignments_by_publication: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for assignment in plan["assignments"]:
        assignments_by_publication[assignment["publication_id"]].append(assignment)

    unresolved_publications = {
        item["publication_id"] for item in plan["publications"] if item["organization_assignments"] == 0
    }
    # v3 materialized roots have already passed the strict quality gate; use
    # only those as repair anchors rather than every exploratory hint.
    root_hints = [
        item["canonical_name"] for item in plan["organizations"] if item["level"] == "root"
    ]
    counters: Counter[str] = Counter()
    fallback_records: list[dict[str, Any]] = []

    for publication_id in sorted(unresolved_publications):
        publication = corpus[publication_id]
        candidates = parsed_candidates(publication["text"], root_hints)
        if not candidates:
            # Last text-based fallback: match already-normalized institutional
            # names in the early full text. This is safer than extracting a new
            # organization from a prose sentence.
            early_text_key = identity_key(publication["text"][:50000])
            matched_existing: list[tuple[ParsedAffiliation, str, set[str]]] = []
            for organization in sorted(
                organizations.values(), key=lambda value: len(value["identity_key"]), reverse=True
            ):
                key = organization["identity_key"]
                if len(key) < 12 or key not in early_text_key:
                    continue
                parsed = parse_affiliation(
                    organization["canonical_name"], root_hints=root_hints, source_confidence=0.46
                )
                if parsed and acceptable_best_effort(parsed[0]):
                    matched_existing.append((parsed[0], organization["canonical_name"], set()))
                if len(matched_existing) >= 4:
                    break
            candidates = matched_existing
        if not candidates:
            # The corpus is a Dalian Medical University representative-work
            # collection. Retain that dataset-level institutional anchor only as
            # the lowest-confidence provisional result, never as a verified fact.
            anchor = parse_affiliation(
                "Dalian Medical University", root_hints=root_hints, source_confidence=0.35
            )[0]
            candidates = [(anchor, "dataset scope: Dalian Medical University", set())]
        paper_assignments = assignments_by_publication[publication_id]
        corpus_authors = {
            str(author["publication_authorship_id"]): author for author in publication["authors"]
        }
        header = publication["text"][:14000]
        marker_map = {
            assignment["publication_authorship_id"]: author_markers(assignment["author_name"], header)
            for assignment in paper_assignments
        }
        used_methods: Counter[str] = Counter()
        for assignment in paper_assignments:
            markers = marker_map[assignment["publication_authorship_id"]]
            prior = prior_author_candidates(
                corpus_authors.get(assignment["publication_authorship_id"], {}), root_hints
            )
            matched = [value for value in candidates if value[2] and markers & value[2]]
            if prior:
                selected = prior
                method = "best_effort_prior_author_mapping"
                confidence = 0.68
            elif matched:
                selected = matched
                method = "best_effort_author_marker"
                confidence = 0.72
            elif len(candidates) == 1:
                selected = candidates
                method = "best_effort_single_paper_affiliation"
                confidence = 0.64
            else:
                selected = candidates
                method = "best_effort_publication_scope"
                confidence = 0.52
            values: dict[str, dict[str, Any]] = {}
            for affiliation, raw, _ in selected:
                value = assignment_value(
                    affiliation,
                    raw,
                    method=method,
                    confidence=min(confidence, affiliation.confidence),
                )
                values.setdefault(identity_key(affiliation.canonical_name), value)
                for record in organization_record(affiliation, raw):
                    existing = organizations.setdefault(record["object_id"], record)
                    for example in record["source_raw_examples"]:
                        if (
                            example not in existing["source_raw_examples"]
                            and len(existing["source_raw_examples"]) < 5
                        ):
                            existing["source_raw_examples"].append(example)
            assignment["organizations"] = list(values.values())
            assignment["best_effort"] = True
            assignment["best_effort_method"] = method
            used_methods[method] += bool(values)
            counters["authorships_completed"] += bool(values)
            counters["author_organization_assignments_added"] += len(values)
        publication_record = next(
            item for item in plan["publications"] if item["publication_id"] == publication_id
        )
        publication_record["organization_assignments"] = sum(
            len(item["organizations"]) for item in paper_assignments
        )
        publication_record["best_effort"] = True
        publication_record["best_effort_candidate_organizations"] = len(candidates)
        if publication_record["organization_assignments"]:
            counters["publications_completed"] += 1
        else:
            counters["publications_still_unresolved"] += 1
        fallback_records.append(
            {
                "publication_id": publication_id,
                "title": publication["publication_title"],
                "candidate_organizations": [value[0].canonical_name for value in candidates],
                "candidate_raw": [value[1] for value in candidates],
                "methods": dict(used_methods),
            }
        )

    all_assignments = plan["assignments"]
    counters["authors_reviewed"] = len(all_assignments)
    counters["authors_with_affiliations"] = sum(bool(item["organizations"]) for item in all_assignments)
    counters["authors_without_affiliations"] = sum(not item["organizations"] for item in all_assignments)
    counters["publications_reviewed"] = len(plan["publications"])
    counters["publications_with_affiliations"] = sum(
        item["organization_assignments"] > 0 for item in plan["publications"]
    )
    counters["publications_without_affiliations"] = sum(
        item["organization_assignments"] == 0 for item in plan["publications"]
    )
    counters["organizations_total"] = len(organizations)
    counters["root_organizations"] = sum(item["level"] == "root" for item in organizations.values())
    counters["branch_organizations"] = sum(item["level"] == "branch" for item in organizations.values())
    counters["hierarchy_relations"] = sum(item["parent_id"] is not None for item in organizations.values())

    plan["schema_version"] = PLAN_VERSION
    plan["generated_at"] = datetime.now(UTC).isoformat()
    plan["base_schema_version"] = "fulltext-affiliation-rebuild-plan-v3"
    plan["policy"] = {
        "mode": "best_effort_demo_completion",
        "scope": "99 publications left empty by conservative v3",
        "marker_match_confidence": 0.72,
        "single_affiliation_confidence": 0.64,
        "publication_scope_confidence": 0.52,
        "review_required": True,
    }
    plan["counts"] = dict(counters)
    plan["organizations"] = sorted(
        organizations.values(), key=lambda value: (value["level"], value["canonical_name"])
    )
    plan["best_effort_records"] = fallback_records
    args.report.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    with args.assignments_csv.open("w", encoding="utf-8", newline="") as output:
        fields = [
            "publication_id", "publication_title", "author_order", "author_name",
            "canonical_name", "root_name", "address", "source_kind", "confidence", "issues", "raw",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for assignment in all_assignments:
            for organization in assignment["organizations"]:
                writer.writerow(
                    {
                        **{field: assignment.get(field) for field in fields},
                        **{field: organization.get(field) for field in fields},
                        "issues": ";".join(organization["issues"]),
                    }
                )
    print(json.dumps(plan["counts"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
