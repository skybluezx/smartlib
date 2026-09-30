"""Research classification policy, shared by ingestion and profile aggregation.

Classification is an evidenced assertion, never a person identity or employment fact.
"""
from collections import defaultdict

POLICY_VERSION = "research-classification-2026-09-v1"
SCHEME_ROLES = {
    "NSFC_APPLICATION_CODE": "research_direction",
    "MESH": "biomedical_topic",
    "WOS_CATEGORY": "evaluation_comparison",
    "INCITES_WOS": "evaluation_comparison",
    "INCITES_CITATION_TOPIC": "evaluation_comparison",
    "MOE_GRADUATE_DISCIPLINE": "education_management",
}


def validate_assignment(assignment: dict) -> None:
    """Validate a proposed assignment before entering the governed relation workflow."""
    required = ("publication_id", "scheme", "scheme_version", "code", "source_kind",
                "source_reference", "evidence_id", "method_version", "review_state")
    if missing := [key for key in required if not assignment.get(key)]:
        raise ValueError(f"Missing classification provenance: {missing}")
    if assignment["scheme"] not in SCHEME_ROLES:
        raise ValueError("Unregistered classification scheme")
    if assignment["source_kind"] not in {"external_indexing", "human_classification", "algorithmic_inference"}:
        raise ValueError("Unknown assignment source kind")
    if assignment["review_state"] not in {"pending", "approved", "rejected"}:
        raise ValueError("Unknown classification review state")
    if assignment["review_state"] == "approved" and not (
        assignment.get("reviewed_by") and assignment.get("reviewed_at")
    ):
        raise ValueError("Approval needs an identified reviewer and timestamp")
    if assignment.get("classification_role", "primary") not in {"primary", "secondary", "topic"}:
        raise ValueError("Unknown classification role")


def aggregate_profile(
    assignments: list[dict],
    memberships: list[dict],
    publication_years: dict[str, int | None],
    *,
    scheme: str,
    scheme_version: str,
    start_year: int,
    end_year: int,
) -> dict:
    """Count distinct publications, not authors, edges or parent/child duplicates.

    Membership input comes from authorship for scholars, and paper-context affiliation
    evidence for organizations. An organization membership without a paper snapshot is
    ineligible. No person.member_of_discipline or employment assertions are produced.
    """
    if scheme not in SCHEME_ROLES or start_year > end_year:
        raise ValueError("Invalid profile scope")
    eligible = {pid for pid, year in publication_years.items()
                if year is not None and start_year <= year <= end_year}
    by_paper = defaultdict(set)
    for item in assignments:
        if (item.get("review_state") != "approved"
                or item.get("scheme") != scheme or item.get("scheme_version") != scheme_version
                or item.get("publication_id") not in eligible):
            continue
        validate_assignment(item)
        by_paper[item["publication_id"]].add(item["code"])
    entity_papers = defaultdict(set)
    groups = defaultdict(set)
    for item in memberships:
        if item.get("review_state") != "approved" or item.get("publication_id") not in eligible:
            continue
        kind = item.get("entity_type")
        if kind not in {"person", "organization"}:
            raise ValueError("Only scholars and organizations have this derived profile")
        if kind == "organization" and (
            item.get("membership_kind") != "publication_snapshot" or not item.get("evidence_id")
        ):
            continue
        if kind == "person" and item.get("membership_kind") != "authorship":
            continue
        key = (kind, item["entity_id"])
        pid = item["publication_id"]
        entity_papers[key].add(pid)
        for code in by_paper[pid]:
            groups[(*key, code)].add(pid)
    return {
        "policy_version": POLICY_VERSION, "scheme": scheme, "scheme_version": scheme_version,
        "start_year": start_year, "end_year": end_year, "counting_unit": "distinct_publication",
        "multi_label_non_additive": True,
        "rows": [{"entity_type": kind, "entity_id": entity_id, "code": code,
                  "paper_count": len(papers), "publication_ids": sorted(papers)}
                 for (kind, entity_id, code), papers in sorted(groups.items())],
        "coverage": [{"entity_type": kind, "entity_id": entity_id,
                      "eligible_papers": len(papers),
                      "classified_papers": sum(bool(by_paper[p]) for p in papers)}
                     for (kind, entity_id), papers in sorted(entity_papers.items())],
    }
