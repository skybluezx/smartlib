"""Versioned, scope-bound discipline coverage and traceable co-occurrence."""

from collections import defaultdict
from itertools import combinations
from typing import Any

from pydantic import BaseModel, Field


class DirectionEvidence(BaseModel):
    publication_id: str
    concept_id: str
    role: str
    review_state: str
    source_kind: str
    rationale: str
    excerpt: str


class DirectionEntity(BaseModel):
    object_id: str
    name: str


class DirectionPaper(BaseModel):
    object_id: str
    title: str
    year: int | None = None
    scholars: list[DirectionEntity] = Field(default_factory=list)
    organizations: list[DirectionEntity] = Field(default_factory=list)


class DirectionCoverage(BaseModel):
    object_id: str
    name: str
    code: str | None = None
    level: int | None = None
    publication_ids: list[str]
    primary_publications: int
    secondary_publications: int
    unspecified_publications: int
    pending_publications: int
    scholar_count: int
    organization_count: int
    share: float | None


class DirectionIntersection(BaseModel):
    left_id: str
    right_id: str
    publication_ids: list[str]


class DirectionScheme(BaseModel):
    key: str
    scheme: str
    name: str
    version: str
    dictionary_count: int
    covered_publications: int
    missing_publications: int
    multiclass_publications: int
    pending_publications: int
    directions: list[DirectionCoverage]
    intersections: list[DirectionIntersection]
    evidence: list[DirectionEvidence]


class DisciplineWorkspace(BaseModel):
    publication_count: int
    schemes: list[DirectionScheme]
    papers: list[DirectionPaper]


SCHEMES = {
    "NSFC_APPLICATION_CODE": "国自然申请代码",
    "INCITES_WOS": "InCites / WoS 研究方向",
    "MOE_GRADUATE_DISCIPLINE": "教育部学科目录",
    "GBT_13745": "GB/T 13745 学科分类",
}
LEGACY = {
    "NSFC_APPLICATION_CODE_2026": ("NSFC_APPLICATION_CODE", "2026"),
    "MOE_GRADUATE_DISCIPLINE_2022": ("MOE_GRADUATE_DISCIPLINE", "2022"),
    "GBT_13745_2009": ("GBT_13745", "2009"),
}


def scheme_identity(row: dict[str, Any]) -> tuple[str, str]:
    scheme = str(row.get("scheme") or "UNKNOWN")
    base, legacy_version = LEGACY.get(scheme, (scheme, "版本未记录"))
    return base, str(row.get("scheme_version") or legacy_version)


def discipline_workspace(
    rows: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    publication_ids: list[Any],
    authors: list[dict[str, Any]],
    affiliations: list[dict[str, Any]],
) -> DisciplineWorkspace:
    """Rows must come from analysis_relation under the existing authorization scope.

    Do not turn unknown roles into primary or treat accepted inference as human review.
    Every count is a distinct paper set; cross-system labels are never paired.
    """
    scope = {str(value) for value in publication_ids}
    paper_map: dict[str, DirectionPaper] = {}
    people: dict[str, dict[str, str]] = defaultdict(dict)
    organizations: dict[str, dict[str, str]] = defaultdict(dict)
    for row in authors:
        people[str(row["publication_id"])][str(row["person_id"])] = row["person_name"]
    for row in affiliations:
        organizations[str(row["publication_id"])][str(row["organization_id"])] = row["organization_name"]
    catalogs = {scheme_identity(row): int(row["concept_count"]) for row in catalog}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        pid = str(row["publication_id"])
        if pid not in scope:
            continue
        grouped[scheme_identity(row)].append(row)
        paper_map[pid] = DirectionPaper(
            object_id=pid,
            title=row.get("publication_title") or "论文题名未收录",
            year=row.get("publication_year"),
            scholars=[DirectionEntity(object_id=i, name=n) for i, n in sorted(people[pid].items())],
            organizations=[
                DirectionEntity(object_id=i, name=n) for i, n in sorted(organizations[pid].items())
            ],
        )
    # Preserve empty dictionaries; show explicitly when no usable dictionary exists.
    for scheme in SCHEMES:
        if not any(key[0] == scheme for key in catalogs.keys() | grouped.keys()):
            catalogs[(scheme, "未提供")] = 0
    result = []
    for scheme, version in sorted(
        catalogs.keys() | grouped.keys(),
        key=lambda k: (list(SCHEMES).index(k[0]) if k[0] in SCHEMES else 99, k),
    ):
        records = grouped[(scheme, version)]
        by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_paper: dict[str, set[str]] = defaultdict(set)
        pending: set[str] = set()
        evidence: dict[tuple[str, ...], DirectionEvidence] = {}
        for row in records:
            pid, cid = str(row["publication_id"]), str(row["object_id"])
            by_concept[cid].append(row)
            by_paper[pid].add(cid)
            role = str(row.get("classification_role") or "unspecified")
            state = str(row["review_state"])
            if state != "approved":
                pending.add(pid)
            item = DirectionEvidence(
                publication_id=pid,
                concept_id=cid,
                role=role,
                review_state=state,
                source_kind=row.get("source_kind") or "unspecified",
                rationale=str(row.get("rationale") or "")[:1200],
                excerpt=str(row.get("evidence_excerpt") or "")[:600],
            )
            evidence[(pid, cid, role, state, item.source_kind, item.rationale, item.excerpt)] = item
        directions = []
        for cid, entries in by_concept.items():
            ids = {str(row["publication_id"]) for row in entries}

            def count_role(role: str, entries: list[dict[str, Any]] = entries) -> int:
                return len(
                    {
                        str(row["publication_id"])
                        for row in entries
                        if (row.get("classification_role") or "unspecified") == role
                    }
                )

            first = entries[0]
            directions.append(
                DirectionCoverage(
                    object_id=cid,
                    name=first["canonical_name"],
                    code=first.get("discipline_code"),
                    level=first.get("discipline_level"),
                    publication_ids=sorted(ids),
                    primary_publications=count_role("primary"),
                    secondary_publications=count_role("secondary"),
                    unspecified_publications=len(
                        {
                            str(row["publication_id"])
                            for row in entries
                            if row.get("classification_role") not in ("primary", "secondary")
                        }
                    ),
                    pending_publications=len(
                        {str(row["publication_id"]) for row in entries if row["review_state"] != "approved"}
                    ),
                    scholar_count=len({person for pid in ids for person in people[pid]}),
                    organization_count=len({org for pid in ids for org in organizations[pid]}),
                    share=len(ids) / len(scope) if scope else None,
                )
            )
        directions.sort(key=lambda item: (-len(item.publication_ids), item.name, item.object_id))
        pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
        for pid, concepts in by_paper.items():
            for pair in combinations(sorted(concepts), 2):
                pairs[pair].add(pid)
        result.append(
            DirectionScheme(
                key=f"{scheme}:{version}",
                scheme=scheme,
                name=SCHEMES.get(scheme, scheme),
                version=version,
                dictionary_count=catalogs.get((scheme, version), 0),
                covered_publications=len(by_paper),
                missing_publications=len(scope - by_paper.keys()),
                multiclass_publications=sum(len(ids) > 1 for ids in by_paper.values()),
                pending_publications=len(pending),
                directions=directions,
                intersections=[
                    DirectionIntersection(left_id=a, right_id=b, publication_ids=sorted(ids))
                    for (a, b), ids in sorted(pairs.items(), key=lambda item: (-len(item[1]), item[0]))
                ],
                evidence=sorted(
                    evidence.values(), key=lambda item: (item.publication_id, item.concept_id, item.role)
                ),
            )
        )
    return DisciplineWorkspace(
        publication_count=len(scope),
        schemes=result,
        papers=sorted(paper_map.values(), key=lambda item: item.object_id),
    )
