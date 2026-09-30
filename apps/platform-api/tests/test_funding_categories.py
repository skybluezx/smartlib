from smartlib_platform.graph_analytics.service import _funding_category_shares


def test_category_coverage_unions_papers_across_kinds():
    rows = [
        {"object_id": "a", "category_label": "中央", "publication_ids": ["p1", "p2"]},
        {"object_id": "b", "category_label": "中央", "publication_ids": ["p2", "p3"]},
        {"object_id": "c", "category_label": "地方", "publication_ids": ["p1"]},
    ]
    result = _funding_category_shares(rows, 4)
    assert result[0].linked_project_count == 3
    assert result[0].share == .75
    assert result[0].funding_agency == "2 个项目种类 · 类内论文去重"
    assert result[1].linked_project_count == 1


def test_empty_and_unknown_category():
    assert _funding_category_shares([], 0) == []
    result = _funding_category_shares([{"object_id": "a", "publication_ids": ["p1"]}], 1)
    assert result[0].name == "来源待确认"
    assert result[0].share == 1


def test_projects_deduplicated_within_category():
    project = {"object_id": "p", "name": "项目", "kind_name": "基金", "grant_number": "123"}
    rows = [{"object_id": "k", "publication_ids": ["a"], "projects": [project, project]}]
    result = _funding_category_shares(rows, 1)
    assert len(result[0].projects) == 1
    assert result[0].projects[0].grant_number == "123"
