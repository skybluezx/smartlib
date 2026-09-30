from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from smartlib_platform.leadership.http import authorization
from smartlib_platform.leadership.models import MatterCommand, Scope
from smartlib_platform.leadership.service import aggregate


def test_scope_validates_year_order_and_does_not_accept_arbitrary_queries():
    with pytest.raises(ValidationError):
        Scope(start_year=2026, end_year=2020)
    with pytest.raises(ValidationError):
        Scope(graph_query="MATCH (n) DETACH DELETE n")
    assert Scope(start_year=2020, end_year=2020).end_year == 2020


def test_school_leader_permissions_are_not_a_frontend_role_switch():
    assert authorization(["leadership.read"], "production") is True
    assert authorization(["knowledge_hub.manage"], "development") is False
    for permissions, environment, write in [
        ([], "development", False),
        (["knowledge_hub.manage"], "production", False),
        (["leadership.read"], "production", True),
    ]:
        with pytest.raises(HTTPException) as exc:
            authorization(permissions, environment, write)
        assert exc.value.status_code == 403


def test_deduplicates_papers_authors_and_only_uses_authored_affiliation_context():
    p, other, a, b, org = [str(uuid4()) for _ in range(5)]
    papers = [{"object_id": p, "year": None}]
    authors = [{"object_id": a, "name": "学者甲", "publication_id": p}] * 2
    authors += [{"object_id": b, "name": "范围外学者", "publication_id": other}]
    affiliations = [{"object_id": org, "name": "署名机构", "person_id": a, "publication_id": p}] * 2
    affiliations += [{"object_id": org, "name": "机构", "person_id": b, "publication_id": p}]
    result = aggregate(papers, authors, affiliations)
    assert result["coverage"] == {
        "publications": 1,
        "scholars": 1,
        "organizations": 1,
        "with_authors": 1,
        "with_affiliations": 1,
        "missing_year": 1,
    }
    assert result["scholars"][0]["papers"] == [p]
    assert result["organizations"][0]["scholar_count"] == 1
    assert result["years"][0]["year"] is None


def test_empty_scope_is_not_fabricated_missing_metrics():
    result = aggregate([], [], [])
    assert result["coverage"]["publications"] == 0
    assert result["scholars"] == []
    assert result["years"] == []


def test_matters_require_real_evidence_and_do_not_accept_hiring_decisions():
    data = {
        "category": "recruitment",
        "title": "人才方向议题",
        "question": "核实该方向的合作基础",
        "evidence": "会议纪要及相关论文",
        "responsible_unit": "学院",
        "next_step": "请专家核实材料",
        "review_on": "2026-12-01",
    }
    assert MatterCommand(**data).status == "proposed"
    with pytest.raises(ValidationError):
        MatterCommand(**{**data, "evidence": ""})
    with pytest.raises(ValidationError):
        MatterCommand(**{**data, "status": "hired"})
