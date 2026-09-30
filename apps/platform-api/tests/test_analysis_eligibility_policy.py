from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = REPOSITORY_ROOT / "database/migrations/V56__unify_analysis_and_graph_eligibility.sql"
ANALYTICS_SERVICE = (
    REPOSITORY_ROOT
    / "apps/platform-api/src/smartlib_platform/graph_analytics/service.py"
)
POSTGRES_GRAPH = (
    REPOSITORY_ROOT / "apps/platform-api/src/smartlib_platform/graph/postgres.py"
)


def test_shared_policy_includes_pending_and_approved_and_drives_projection() -> None:
    sql = MIGRATION.read_text()

    assert "analysis_state_eligible" in sql
    assert "p_review_state IN ('pending', 'approved')" in sql
    assert "analysis_state_eligible(subject.review_state)" in sql
    assert "analysis_state_eligible(target.review_state)" in sql
    assert "analysis-eligibility-v1:object:" in sql
    assert "analysis-eligibility-v1:relation:" in sql


def test_postgres_analytics_and_graph_baseline_use_shared_policy() -> None:
    analytics = ANALYTICS_SERVICE.read_text()
    graph = POSTGRES_GRAPH.read_text()

    assert analytics.count("smartlib.analysis_state_eligible") >= 35
    forbidden_filters = (
        "relation.predicate = 'person.authored'\n                     AND relation.review_state",
        "relation.predicate='publication.published_in'\n                     AND relation.review_state",
        "relation.predicate='project.has_representative_publication'\n"
        "                    AND relation.review_state",
    )
    assert not any(value in analytics for value in forbidden_filters)
    assert "smartlib.analysis_state_eligible(relation.review_state)" in graph
    assert "smartlib.analysis_state_eligible(subject.review_state)" in graph
    assert "smartlib.analysis_state_eligible(object.review_state)" in graph


def test_project_kind_distribution_retains_mixed_review_state() -> None:
    from smartlib_platform.graph_analytics.service import _funding_candidate_shares

    result = _funding_candidate_shares(
        [
            {
                "object_id": "kind-1",
                "canonical_name": "国家自然科学基金项目",
                "relation_count": 3,
                "linked_item_count": 2,
                "pending_relation_count": 2,
                "approved_relation_count": 1,
                "average_confidence": 0.8,
            }
        ]
    )

    assert result[0].review_state == "mixed"
