from datetime import UTC, datetime
from uuid import UUID

from smartlib_platform.scholars.service import (
    _affiliations,
    get_scholar_evidence,
    get_scholar_profile,
    list_scholars,
    resolve_scholar_object_id,
)

SCHOLAR_ID = UUID("81000000-0000-4000-8000-000000000001")
PUBLICATION_ID = UUID("85000000-0000-4000-8000-000000000001")
RELATION_ID = UUID("88000000-0000-4000-8000-000000000025")
EVIDENCE_ID = UUID("8c000000-0000-4000-8000-000000000020")
SOURCE_REFERENCE_ID = UUID("8b000000-0000-4000-8000-000000000020")
NOW = datetime(2026, 8, 26, tzinfo=UTC)


class Cursor:
    def __init__(
        self, *, rows: list[dict[str, object]] | None = None, row: dict[str, object] | None = None
    ) -> None:
        self.rows = rows or []
        self.row = row

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows

    def fetchone(self) -> dict[str, object] | None:
        return self.row


class QueueConnection:
    def __init__(self, cursors: list[Cursor]) -> None:
        self.cursors = cursors
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> Cursor:
        self.calls.append((query, params))
        return self.cursors.pop(0)


def summary_row() -> dict[str, object]:
    return {
        "object_id": SCHOLAR_ID,
        "scholar_id": "SL-DEMO-0001",
        "canonical_name": "林知远",
        "initials": "林",
        "title": "教授 / 博士生导师",
        "department": "基础医学院",
        "discipline": "基础医学",
        "primary_direction": "肠道微生态与代谢性肝病",
        "publications": 2,
        "projects": 2,
        "collaborators": 2,
        "synthetic": True,
        "dataset_version": "scholargraph-demo-v1",
        "object_version": 1,
        "updated_at": NOW,
    }


def related_row(*, object_type: str = "publication") -> dict[str, object]:
    return {
        "object_id": PUBLICATION_ID,
        "object_type": object_type,
        "canonical_name": "微生态代谢轴与肝病分层研究",
        "description": "synthetic 代表成果。",
        "relation_id": RELATION_ID,
        "predicate": "person.authored",
        "fact_class": "literature_fact",
        "confidence": 1.0,
        "review_state": "approved",
        "evidence_count": 1,
        "object_version": 1,
        "year": 2026,
        "item_type": "论文",
    }


def test_list_scholars_returns_computed_metrics_and_synthetic_boundary() -> None:
    connection = QueueConnection([Cursor(rows=[summary_row()])])

    result = list_scholars(connection, query="微生态", department="基础医学院", limit=10)

    assert result[0].scholar_id == "SL-DEMO-0001"
    assert result[0].metrics.publications == 2
    assert result[0].metrics.collaborators == 2
    assert result[0].synthetic is True
    assert result[0].dataset_version == "scholargraph-demo-v1"
    assert connection.calls[0][1][-1] == 10
    assert "person.authoritatively_affiliated_with" in connection.calls[0][0]
    assert "relation.valid_from <= now()" in connection.calls[0][0]


def test_affiliation_snapshots_are_not_collapsed_or_promoted() -> None:
    base = dict(
        relation_id=RELATION_ID,
        organization_id=SCHOLAR_ID,
        organization_name="机构 A",
        is_current=True,
        evidence=[],
    )
    connection = QueueConnection(
        [
            Cursor(
                rows=[
                    dict(base, category="authoritative"),
                    dict(base, category="output", context_object_id=PUBLICATION_ID),
                    dict(base, category="output", context_object_id=SCHOLAR_ID),
                ]
            )
        ]
    )
    result = _affiliations(connection, SCHOLAR_ID)
    assert len(result) == 3
    assert [item.category for item in result] == ["authoritative", "output", "output"]
    assert result[1].context_object_id != result[2].context_object_id
    assert "r.review_state='approved'" in connection.calls[0][0]


def test_public_scholar_id_resolves_to_visible_canonical_object() -> None:
    connection = QueueConnection([Cursor(row={"object_id": SCHOLAR_ID})])

    result = resolve_scholar_object_id(connection, "SL-DEMO-0001")

    assert result == SCHOLAR_ID
    assert connection.calls[0][1] == ("SL-DEMO-0001", "SL-DEMO-0001")


def test_profile_keeps_fact_and_analysis_relations_distinct() -> None:
    direction = {
        "object_id": UUID("84000000-0000-4000-8000-000000000001"),
        "canonical_name": "肠道微生态与代谢性肝病",
        "relation_id": UUID("88000000-0000-4000-8000-000000000013"),
        "fact_class": "human_confirmed",
        "confidence": 0.98,
        "review_state": "approved",
        "evidence_count": 1,
    }
    connection = QueueConnection(
        [
            Cursor(rows=[summary_row()]),
            Cursor(row={"description": "synthetic 学者。"}),
            Cursor(rows=[{"canonical_name": "基础医学"}]),
            Cursor(rows=[direction]),
            Cursor(row={"publication": 1, "project": 0, "person": 0, "concept": 0}),
            Cursor(rows=[]),
            Cursor(rows=[related_row()]),
            Cursor(rows=[]),
            Cursor(rows=[]),
            Cursor(rows=[]),
        ]
    )

    result = get_scholar_profile(connection, SCHOLAR_ID)

    assert result is not None
    assert result.profile_kind == "fact_profile"
    assert result.affiliations == []
    assert result.metric_scope == "current_visible_analysis_eligible_relations"
    assert result.research_directions[0].fact_class == "human_confirmed"
    assert result.representative_publications[0].evidence_count == 1
    assert connection.calls[7][1] is not None
    assert connection.calls[7][1][1] == ["person.leads_project", "person.participates_in"]


def test_evidence_preserves_relation_source_and_dataset_context() -> None:
    evidence_row = {
        "evidence_id": EVIDENCE_ID,
        "object_id": PUBLICATION_ID,
        "evidence_type": "publication",
        "citation": "scholargraph-demo-v1 / 微生态代谢轴与肝病分层研究",
        "excerpt": "synthetic 证据。",
        "source_reference_id": SOURCE_REFERENCE_ID,
        "source_name": "机构知识库",
        "source_version": "scholargraph-demo-v1",
        "observed_at": NOW,
        "dataset_version": "scholargraph-demo-v1",
        "synthetic": True,
        "relation_id": RELATION_ID,
        "predicate": "person.authored",
        "fact_class": "literature_fact",
        "confidence": 1.0,
        "review_state": "approved",
    }
    connection = QueueConnection(
        [
            Cursor(row={"object_id": SCHOLAR_ID, "scholar_id": "SL-DEMO-0001", "version": 1}),
            Cursor(rows=[evidence_row]),
        ]
    )

    result = get_scholar_evidence(connection, SCHOLAR_ID)

    assert result is not None
    assert result.scholar_id == "SL-DEMO-0001"
    assert result.items[0].relation_id == RELATION_ID
    assert result.items[0].source_name == "机构知识库"
    assert result.items[0].synthetic is True
    assert result.items[0].dataset_version == "scholargraph-demo-v1"
