from datetime import date
from uuid import UUID

from smartlib_platform.graph_analytics.service import (
    _build_incites_analysis,
    _discipline_analysis,
    _funding_candidate_shares,
    _institution_group,
    _journal_analyses,
    _people_network,
    _quartile_distribution,
    _scoped_publication_ids,
)


class _Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class _ScopeConnection:
    def __init__(self, publication_id: UUID) -> None:
        self.publication_id = publication_id
        self.sql = ""
        self.params: tuple[object, ...] = ()

    def execute(self, sql: str, params: tuple[object, ...]) -> _Rows:
        self.sql = sql
        self.params = params
        return _Rows([{"object_id": self.publication_id}])


def test_scope_combines_dimensions_and_expands_organization_descendants() -> None:
    publication_id = UUID(int=1)
    organization_id = UUID(int=2)
    project_kind_id = UUID(int=3)
    scholar_id = UUID(int=4)
    connection = _ScopeConnection(publication_id)

    result = _scoped_publication_ids(
        connection,  # type: ignore[arg-type]
        start_year=2023,
        end_year=2025,
        project_kind_ids=[project_kind_id],
        organization_ids=[organization_id],
        scholar_ids=[scholar_id],
    )

    assert result == [publication_id]
    assert "WITH RECURSIVE organization_scope" in connection.sql
    assert "organization.has_department" in connection.sql
    assert connection.params[0] == [organization_id]
    assert connection.params[1:3] == (2023, 2025)
    assert connection.params[-1] == [scholar_id]


def test_quartile_share_clamps_floating_point_roundoff() -> None:
    publication_ids = {f"paper-{index}" for index in range(10)}
    metrics = {
        publication_id: {
            "jcr": [{"quartile": "Q1"}, {"quartile": "Q1"}, {"quartile": "Q1"}]
        }
        for publication_id in publication_ids
    }

    result = _quartile_distribution(publication_ids, metrics, "jcr")

    assert result[0].share == 1.0


def test_funding_candidates_include_pending_distribution_and_other_bucket() -> None:
    rows = [
        {
            "object_id": f"candidate-{index}",
            "canonical_name": f"候选基金{index}",
            "relation_count": count,
            "linked_item_count": count,
            "average_confidence": confidence,
        }
        for index, (count, confidence) in enumerate([(8, 0.8), (4, 0.5), (2, 0.2)])
    ]

    result = _funding_candidate_shares(rows, display_limit=2)

    assert [item.name for item in result] == ["候选基金0", "候选基金1", "其他项目种类"]
    assert sum(item.share for item in result) == 1
    assert result[-1].relation_count == 2
    assert result[-1].review_state == "pending"


def test_funding_candidates_return_every_kind_by_default() -> None:
    rows = [
        {"object_id": f"kind-{index}", "canonical_name": f"Kind {index}",
         "relation_count": index + 1, "linked_item_count": index + 1,
         "average_confidence": 0.8}
        for index in range(25)
    ]
    result = _funding_candidate_shares(rows)
    assert len(result) == 25
    assert {item.object_id for item in result} == {row["object_id"] for row in rows}
    assert [item.linked_item_count for item in result] == list(range(25, 0, -1))


def test_people_network_counts_shared_publications_and_keeps_evidence() -> None:
    rows = [
        {
            "person_id": UUID(int=person),
            "person_name": name,
            "publication_id": UUID(int=publication),
            "publication_title": title,
        }
        for person, name, publication, title in [
            (1, "甲", 10, "论文一"),
            (2, "乙", 10, "论文一"),
            (1, "甲", 11, "论文二"),
            (2, "乙", 11, "论文二"),
            (3, "丙", 11, "论文二"),
        ]
    ]

    result = _people_network(rows, minimum=2, limit=20)

    assert result.total_edge_count == 1
    assert result.edges[0].publication_count == 2
    assert [item.title for item in result.edges[0].evidence_publications] == ["论文一", "论文二"]
    assert {item.name for item in result.nodes} == {"甲", "乙"}


def test_dalian_affiliations_are_grouped_for_focus_collaboration() -> None:
    first = _institution_group(
        "org-1",
        "The First Affiliated Hospital",
        "The First Affiliated Hospital of Dalian Medical University",
    )
    campus = _institution_group(
        "org-2",
        "College of Pharmacy",
        "College of Pharmacy, Dalian Medical University",
    )
    institute = _institution_group(
        "org-3",
        "Dalian Institute of Chemical Physics",
        "Chinese Academy of Sciences",
    )

    assert first == ("focus:dmu-first", "大连医科大学附属第一医院")
    assert campus == ("focus:dmu-campus", "大连医科大学校本部")
    assert institute == ("focus:dicp", "中国科学院大连化学物理研究所")


def test_external_institution_is_not_swallowed_by_combined_raw_affiliation() -> None:
    result = _institution_group(
        "org-maritime",
        "Dalian Maritime University",
        "First Affiliated Hospital of Dalian Medical University; Dalian Maritime University",
    )

    assert result == ("organization:org-maritime", "Dalian Maritime University")


def test_discipline_distribution_uses_primary_relations_for_share() -> None:
    rows = [
        {
            "object_id": UUID(int=1),
            "canonical_name": "基础医学",
            "publication_id": UUID(int=10),
            "review_state": "pending",
            "scheme": "MOE_GRADUATE_DISCIPLINE_2022",
            "classification_role": "primary",
            "discipline_code": "1001",
            "discipline_level": 2,
        },
        {
            "object_id": UUID(int=2),
            "canonical_name": "临床医学",
            "publication_id": UUID(int=11),
            "review_state": "pending",
            "scheme": "MOE_GRADUATE_DISCIPLINE_2022",
            "classification_role": "primary",
            "discipline_code": "1002",
            "discipline_level": 2,
        },
        {
            "object_id": UUID(int=1),
            "canonical_name": "基础医学",
            "publication_id": UUID(int=11),
            "review_state": "pending",
            "scheme": "MOE_GRADUATE_DISCIPLINE_2022",
            "classification_role": "secondary",
            "discipline_code": "1001",
            "discipline_level": 2,
        },
    ]

    result = _discipline_analysis(rows)

    assert result.classified_publications == 2
    assert result.broad_disciplines[0].share == 0.5
    assert result.broad_disciplines[0].secondary_publications == 1
    assert result.review_state == "pending"


def test_journal_project_analysis_uses_exact_year_metrics_and_fractional_quartiles() -> None:
    publication_id = UUID(int=10)
    project_id = UUID(int=20)
    journal_id = UUID(int=30)
    journal, projects = _journal_analyses(
        [{"object_id": journal_id, "canonical_name": "Journal A", "publication_count": 1}],
        [
            {
                "publication_id": publication_id,
                "metric_system": "jcr",
                "metric_year": 2024,
                "impact_factor": 8.2,
                "quartile": "Q1",
                "record_id": UUID(int=40),
            },
            {
                "publication_id": publication_id,
                "metric_system": "jcr",
                "metric_year": 2024,
                "impact_factor": 8.2,
                "quartile": "Q2",
                "record_id": UUID(int=41),
            },
            {
                "publication_id": publication_id,
                "metric_system": "cas_partition",
                "metric_year": 2024,
                "impact_factor": None,
                "quartile": "Q1",
                "record_id": UUID(int=42),
            },
        ],
        [
            {
                "project_id": project_id,
                "project_name": "项目一",
                "funding_year": 2026,
                "publication_id": publication_id,
                "publication_title": "论文一",
                "publication_year": 2024,
                "journal_id": journal_id,
                "journal_name": "Journal A",
            }
        ],
    )

    assert journal.impact_factor.median == 8.2
    assert journal.jcr_quartiles[0].paper_equivalents == 0.5
    assert journal.jcr_quartiles[1].paper_equivalents == 0.5
    assert projects.projects[0].publication_count == 1
    assert projects.annual_portfolios[0].funding_year == 2026
    assert projects.annual_portfolios[0].project_count == 1
    assert projects.annual_portfolios[0].unique_publications == 1
    assert projects.annual_portfolios[0].project_publication_links == 1
    assert projects.annual_portfolios[0].jcr_project_coverage.full == 1
    assert projects.projects[0].publications[0].jcr_quartiles == ["Q1", "Q2"]
    assert projects.projects[0].publications[0].cas_partitions == ["Q1"]


def test_incites_journal_analysis_preserves_scope_missingness_and_references() -> None:
    release = {
        "release_id": UUID(int=70),
        "exported_on": date(2026, 9, 9),
        "indexed_through": date(2026, 7, 31),
        "dataset_updated_on": date(2026, 9, 2),
    }
    base = {
        "publication_id": UUID(int=10),
        "publication_title": "论文一",
        "publication_year": 2024,
        "journal_name": "Journal A",
        "source_document_type": "Article",
        "source_research_areas": "Oncology",
        "source_collaboration_type": "International",
        "semantic_level": "publication",
        "unit": "ratio",
        "aggregation_rule": "mean",
        "value_status": "present",
    }
    rows = [
        {
            **base,
            "metric_code": "incites.cnci",
            "label": "学科规范化的引文影响力",
            "definition": "论文集合先去重后统计。",
            "numeric_value": 1.5,
        },
        {
            **base,
            "metric_code": "incites.times_cited",
            "label": "被引频次",
            "definition": "截至索引日期的累计被引。",
            "unit": "count",
            "aggregation_rule": "sum_and_mean",
            "numeric_value": 12,
        },
    ]

    result = _build_incites_analysis(
        release,
        rows,
        scoped_publication_ids={str(UUID(int=10)), str(UUID(int=11))},
    )

    assert result.snapshot_publications == 1
    cnci = next(metric for metric in result.metrics if metric.code == "incites.cnci")
    citations = next(metric for metric in result.metrics if metric.code == "incites.times_cited")
    assert cnci.covered_publications == 1
    assert cnci.missing_publications == 1
    assert cnci.reference == 1
    assert cnci.above_reference_count == 1
    assert citations.total == 12
    assert result.publications[0].metric_values["incites.cnci"] == 1.5


def test_current_versioned_nsfc_code_is_visible_in_legacy_analytics() -> None:
    result = _discipline_analysis([{
        'scheme': 'NSFC_APPLICATION_CODE', 'object_id': 'concept-1',
        'canonical_name': '中药学', 'publication_id': 'paper-1',
        'classification_role': 'primary', 'review_state': 'pending',
        'discipline_code': 'H32',
    }])
    assert result.classified_publications == 1
    assert result.nsfc_directions[0].code == 'H32'
    assert result.nsfc_directions[0].share == 1


def test_outcome_missing_values_are_not_zero_and_groups_are_exclusive() -> None:
    from smartlib_platform.graph_analytics.models import OutcomePaper
    from smartlib_platform.graph_analytics.outcomes import MODES, summarize_outcomes

    papers = [OutcomePaper(
        publication_id=UUID(int=i+1), title=str(i), mode=MODES[0], author_count=2,
        affiliation_author_count=2, institution_count=2, institution_names=['A', 'B'],
        cnci=value,
    ) for i, value in enumerate([0, 2, None])]
    groups = summarize_outcomes(papers)
    assert sum(g.publication_count for g in groups) == 3
    assert groups[0].cnci_covered == 2
    assert groups[0].cnci_median == 1
    assert groups[0].cnci_mean == 1
    assert groups[0].jif_median is None


def test_institution_hierarchy_deduplicates_parent_and_child_and_detects_cycles() -> None:
    from smartlib_platform.graph_analytics.outcomes import institution_roots

    parents = {'hospital': {'university'}, 'department': {'hospital'}}
    assert institution_roots(parents, 'department') == {'university'}
    assert institution_roots(parents, 'hospital') == {'university'}
    assert institution_roots({'a': {'b'}, 'b': {'a'}}, 'a') == set()
    assert institution_roots({'a': {'b', 'c'}}, 'a') == {'b', 'c'}


def test_mode_does_not_infer_cooperation_from_a_single_author_with_many_affiliations() -> None:
    from smartlib_platform.graph_analytics.outcomes import MODES, classify_mode

    assert classify_mode(1, 1, 1, 3, False) == MODES[2]
    assert classify_mode(3, 2, 2, 2, False) == MODES[3]
    assert classify_mode(3, 3, 3, 2, True) == MODES[3]
    assert classify_mode(3, 3, 3, 2, False) == MODES[0]
    assert classify_mode(3, 3, 3, 1, False) == MODES[1]


def test_application_register_rejects_temporal_leakage_and_missing_decision_dates():
    import pytest
    from pydantic import ValidationError

    from smartlib_platform.graph_analytics.planning import ApplicationRecord

    base = dict(reference='A', title='Application', applicant_id=UUID(int=1),
                project_kind_id=UUID(int=2), deadline='2024-03-01',
                submitted_on='2024-02-28', evidence='source page 1')
    assert ApplicationRecord(**base).decision == 'pending'
    with pytest.raises(ValidationError):
        ApplicationRecord(**{**base, 'submitted_on': '2024-03-02'})
    with pytest.raises(ValidationError):
        ApplicationRecord(**base, decision='awarded')
    with pytest.raises(ValidationError):
        ApplicationRecord(**base, decided_on='2023-01-01')
    with pytest.raises(ValidationError):
        ApplicationRecord(**base, project_id=UUID(int=3))


def test_support_action_requires_beneficiaries_and_nonretroactive_review():
    import pytest
    from pydantic import ValidationError

    from smartlib_platform.graph_analytics.planning import SupportAction

    base = dict(title='Support', rationale='source', support='meeting', expected_change='shared protocol',
                started_on='2024-01-01', review_on='2024-02-01', beneficiary_ids=[UUID(int=1)],
                decision_reason='reviewed', evidence='minutes')
    assert SupportAction(**base).decision == 'proposed'
    with pytest.raises(ValidationError):
        SupportAction(**{**base, 'review_on': '2023-01-01'})
    with pytest.raises(ValidationError):
        SupportAction(**{**base, 'beneficiary_ids': []})


def test_application_csv_intake_validates_entire_batch_before_writing():
    import pytest

    from smartlib_platform.graph_analytics.planning import parse_application_csv
    content = ('reference,title,applicant_id,project_kind_id,deadline,submitted_on,evidence\n'
               f'X,Title,{UUID(int=1)},{UUID(int=2)},2024-03-01,2024-02-01,file page 2\n')
    records = parse_application_csv(content.encode())
    assert len(records) == 1
    assert records[0].application.decision == 'pending'
    with pytest.raises(ValueError, match='第3行'):
        parse_application_csv((content + 'invalid,row,,,,,\n').encode())
    with pytest.raises(ValueError):
        parse_application_csv(b'reference,reference\nx,x\n')
    with pytest.raises(ValueError):
        parse_application_csv(b'\xff')


def test_journal_list_is_complete_and_uses_full_scope_denominator():
    from smartlib_platform.graph_analytics.service import _journal_analyses
    rows = [{"object_id": f"journal-{i}", "canonical_name": f"Journal {i}", "publication_count": 1} for i in range(20)]
    journals, _ = _journal_analyses(rows, [], [], scoped_publication_ids={str(i) for i in range(25)})
    assert len(journals.top_journals) == 20
    assert all(item.share == 1 / 25 for item in journals.top_journals)


def test_discipline_workspace_scopes_deduplicates_and_preserves_versions_and_sources() -> None:
    from smartlib_platform.graph_analytics.disciplines import discipline_workspace

    def row(pid, cid, role='primary', scheme='NSFC_APPLICATION_CODE', version='2026', state='pending'):
        return dict(publication_id=pid, object_id=cid, canonical_name=cid, scheme=scheme,
                    scheme_version=version, review_state=state, classification_role=role,
                    publication_title=f'Title {pid}', source_kind='algorithmic_inference')
    rows = [row('p1', 'a'), row('p1', 'a'), row('p1', 'b', 'secondary'), row('p2', 'b', None),
            row('outside', 'c'), row('p1', 'a-2025', version='2025'),
            row('p1', 'wos', 'secondary', scheme='INCITES_WOS', state='approved')]
    authors = [dict(publication_id='p1', person_id='s1', person_name='Scholar')]*2
    affiliations = [dict(publication_id='p1', organization_id='o1', organization_name='Organization')]*2
    result = discipline_workspace(rows, [dict(scheme='MOE_GRADUATE_DISCIPLINE',
                                             scheme_version='2022', concept_count=198)],
                                  ['p1', 'p2', 'missing'], authors, affiliations)
    current = next(s for s in result.schemes if s.key == 'NSFC_APPLICATION_CODE:2026')
    assert current.covered_publications == 2
    assert current.missing_publications == 1
    assert current.pending_publications == 2
    assert current.multiclass_publications == 1
    assert len(current.evidence) == 3
    assert current.intersections[0].publication_ids == ['p1']
    assert len(current.intersections) == 1
    b = next(d for d in current.directions if d.object_id == 'b')
    assert b.share == 2/3
    assert (b.primary_publications, b.secondary_publications, b.unspecified_publications) == (0, 1, 1)
    assert (b.scholar_count, b.organization_count) == (1, 1)
    assert len(result.papers[0].scholars) == 1
    assert all('outside' not in d.publication_ids for s in result.schemes for d in s.directions)
    empty = next(s for s in result.schemes if s.scheme == 'MOE_GRADUATE_DISCIPLINE')
    assert empty.dictionary_count == 198 and not empty.directions
    assert empty.missing_publications == 3
    wos = next(s for s in result.schemes if s.scheme == 'INCITES_WOS')
    assert wos.directions[0].primary_publications == 0
    assert wos.covered_publications == 1


def test_discipline_workspace_returns_all_directions_and_zero_scope_without_fake_coverage() -> None:
    from smartlib_platform.graph_analytics.disciplines import discipline_workspace
    rows = [dict(publication_id='p', object_id=str(i), canonical_name=str(i),
                 scheme='NSFC_APPLICATION_CODE', scheme_version='2026', review_state='pending')
            for i in range(35)]
    result = discipline_workspace(rows, [], ['p'], [], [])
    assert len(result.schemes[0].directions) == 35
    assert all(item.primary_publications == 0 for item in result.schemes[0].directions)
    empty = discipline_workspace(rows, [], [], [], [])
    assert empty.publication_count == 0 and not empty.papers
    assert all(s.covered_publications == 0 and not s.directions for s in empty.schemes)


def test_legacy_discipline_response_does_not_invent_primary_roles_or_truncate() -> None:
    rows = [dict(publication_id='p', object_id=str(i), canonical_name=str(i),
                 scheme='NSFC_APPLICATION_CODE', review_state='pending', classification_role=None)
            for i in range(35)]
    result = _discipline_analysis(rows)
    assert len(result.nsfc_directions) == 35
    assert result.primary_relation_count == 0
    assert all(item.primary_publications == 0 and item.publication_count == 1
               for item in result.nsfc_directions)


def test_people_directory_includes_isolates_and_focus_precedes_limit() -> None:
    rows = [
        {"publication_id": publication, "publication_title": publication,
         "person_id": person, "person_name": person}
        for publication, people in [("p1", ["a", "b"]), ("p2", ["a", "b"]),
                                    ("p3", ["c", "d"]), ("p4", ["solo"])]
        for person in people
    ]
    affiliations = [{
        "publication_id": "p3", "person_id": "c", "organization_id": "org", "organization_name": "机构"
    }]
    result = _people_network(rows, 1, 1, affiliations, focus_id="c")
    assert result.scope_node_count == 5
    assert result.total_node_count == 4
    assert result.matched_node_count == 2
    assert result.edges[0].source_id == "c"
    assert {node.object_id for node in result.directory} == {"a", "b", "c", "d", "solo"}
    assert not result.truncated
    assert _people_network(rows, 2, 1, affiliations, focus_id="c").matched_edge_count == 0
    assert _people_network(rows, 1, 1, affiliations, organization_id="org").edges == []
    institution = _people_network(rows, 1, 1, affiliations, organization_id="org", include_external=True)
    assert {node.object_id for node in institution.nodes} == {"c", "d"}
    assert _people_network(rows, 1, 1, affiliations, organization_id="missing").edges == []


def test_people_institution_default_keeps_both_endpoints_inside():
    rows = [{"publication_id": "p", "publication_title": "P", "person_id": p, "person_name": p}
            for p in ["a", "b", "external"]]
    affiliations = [{"publication_id": "p", "person_id": p, "organization_id": "org", "organization_name": "Org"}
                    for p in ["a", "b"]]
    internal = _people_network(rows, 1, 100, affiliations, organization_id="org")
    assert {node.object_id for node in internal.nodes} == {"a", "b"}
    assert len(internal.edges) == 1
    expanded = _people_network(rows, 1, 100, affiliations, organization_id="org", include_external=True)
    assert len(expanded.edges) == 3
    assert len(expanded.nodes) == 3


def test_cooperation_assessment_ignores_display_filters_and_deduplicates():
    rows = [
        {"publication_id": pid, "publication_title": pid, "person_id": person, "person_name": person}
        for pid, authors in {"p1": ["a", "b", "c"], "p2": ["a", "b"], "p3": ["d"]}.items()
        for person in authors
    ]
    full = _people_network(rows, 1, 100, scope_ids=["p1", "p2", "p3", "missing"])
    restricted = _people_network([*rows, rows[0]], 2, 1, focus_id="b",
                                 scope_ids=["missing", "p3", "p2", "p1"])
    assert full.assessment == restricted.assessment
    a = full.assessment
    assert a.node_count == 4 and a.edge_count == 3
    assert a.isolated_node_count == 1
    assert a.missing_author_publication_ids == ["missing"]
    assert sorted(n for c in a.communities for n in c.member_ids) == ["a", "b", "c", "d"]
    assert len(a.sensitivity) == 7
    assert _people_network(list(reversed(rows)), 1, 2,
                           scope_ids=["p1", "p2", "p3", "missing"]).assessment == a
    assert all(n.community_id is not None for n in full.nodes)


def test_cooperation_assessment_empty_and_no_edge_inputs():
    empty = _people_network([], 1, 1, scope_ids=["missing"]).assessment
    assert empty.modularity is None and empty.communities == []
    rows = [{"publication_id": "p", "publication_title": "P", "person_id": "a", "person_name": "A"}]
    a = _people_network(rows, 1, 1).assessment
    assert a.isolated_node_count == 1
    assert a.communities[0].internal_weight_share is None
    assert a.communities[0].publication_ids == ["p"]


def test_cooperation_standard_partition_metrics_and_frozen_evidence():
    from smartlib_platform.graph_analytics.cooperation import _ari
    assert _ari([{"a", "b"}, {"c", "d"}], [{"a", "b"}, {"c", "d"}]) == 1
    assert abs(_ari([{"a", "b"}, {"c", "d"}], [{"a", "c"}, {"b", "d"}]) + 0.5) < 1e-12
    rows = [{"publication_id": "p", "publication_title": "P", "person_id": n, "person_name": n}
            for n in ("a", "b", "c")]
    a = _people_network(rows, 1, 1).assessment
    c = a.communities[0]
    assert c.density == 1 and c.internal_weight_share == 1
    assert c.internal_edge_count == 3 and c.external_edge_count == 0
    assert c.connected_components == 1 and c.seed_stability == 1
    # Copy-on-read protects cached evidence from accidental mutations.
    a.communities.clear()
    assert len(_people_network(rows, 1, 100).assessment.communities) == 1


def test_cooperation_edge_evidence_is_not_limited_to_three_papers():
    rows = [{"publication_id": str(i), "publication_title": str(i), "person_id": n, "person_name": n}
            for i in range(5) for n in ("a", "b")]
    network = _people_network(rows, 1, 1)
    assert len(network.edges[0].evidence_publications) == network.edges[0].publication_count == 5


def test_community_portfolio_dedup_missing_zero_conflict_and_fractional_quartiles():
    from smartlib_platform.graph_analytics.cooperation_metrics import enrich_assessment
    rows = [{'publication_id': p, 'publication_title': p, 'person_id': n, 'person_name': n}
            for p in ('p1', 'p2', 'p3') for n in ('a', 'b')]
    a = _people_network(rows, 1, 1).assessment
    inputs = [dict(source='incites', publication_id=p, metric_code='incites.cnci',
                   value_status='present', numeric_value=v)
              for p, v in [('p1', 0), ('p1', 0), ('p2', 2)]]
    inputs += [dict(source='journal', publication_id='p1', metric_system='jcr',
                    impact_factor=4, quartile=q, record_id=r)
               for q, r in [('Q1','r1'), ('Q1','r1'), ('Q2','r2')]]
    inputs += [dict(source='journal', publication_id='p2', metric_system='jcr',
                    impact_factor=v, quartile=None, record_id=str(v)) for v in (5, 6)]
    enrich_assessment(a, {}, inputs)
    c = a.communities[0]
    cnci = next(m for m in c.metrics if m.code == 'incites.cnci')
    assert cnci.count == 2 and cnci.mean == cnci.median == 1
    assert cnci.above_reference_count == 1 and cnci.missing_publication_ids == ['p3']
    jif = next(m for m in c.metrics if m.code == 'journal.jif')
    assert jif.count == 1 and jif.mean == 4 and jif.total is None
    assert c.quartiles['jcr'].shares['Q1'] == c.quartiles['jcr'].shares['Q2'] == .5
    absent = next(m for m in c.metrics if m.code == 'incites.times_cited')
    assert absent.mean is None and absent.total is None and absent.count == 0
    assert c.quartiles['cas_partition'].shares['Q1'] is None
    assert not _people_network(rows, 1, 100).assessment.communities[0].metrics
    original_hash = a.metric_input_hash
    enrich_assessment(a, {'release': 'new'}, inputs)
    assert a.metric_input_hash != original_hash


def test_centers_distinguish_star_multiple_bridges_and_symmetric_graph():
    import networkx as nx

    from smartlib_platform.graph_analytics.cooperation import community_centers
    star = nx.star_graph(5)
    nx.set_edge_attributes(star, 1, 'weight')
    assert [c.person_id for c in community_centers(nx.relabel_nodes(star, str))] == ['0']
    clique = nx.complete_graph(5)
    nx.set_edge_attributes(clique, 1, 'weight')
    assert community_centers(clique) == []
    bridge = nx.path_graph([str(i) for i in range(6)])
    nx.set_edge_attributes(bridge, 1, 'weight')
    centers = community_centers(bridge)
    assert {c.person_id for c in centers if '簇内桥梁' in c.roles} == {'2','3'}
    assert community_centers(nx.empty_graph(1)) == []


def test_institution_assessment_uses_real_ids_and_full_scope_before_display_filters():
    from smartlib_platform.graph_analytics.service import _institution_network
    rows = [{'publication_id': p, 'publication_title': p, 'organization_id': n,
             'organization_name': '大连医科大学' if n == 'a' else n}
            for p, ns in [('p1',['a','b','b']),('p2',['a','b']),('p3',['c'])] for n in ns]
    narrow = _institution_network(rows, 2, 1, scope_ids=['p1','p2','p3','missing'])
    wide = _institution_network(rows, 1, 100, scope_ids=['p1','p2','p3','missing'])
    assert narrow.assessment.entity_type == 'organization'
    for community in narrow.assessment.communities:
        assert community.centers_method == 'top-5pct-median-1.2-v2'
        assert {m.person_id for m in community.member_center_metrics} == set(community.member_ids)
    assert narrow.assessment.node_count == 3
    assert narrow.assessment.isolated_node_count == 1
    assert narrow.assessment.missing_author_publication_ids == ['missing']
    assert narrow.assessment.input_hash == wide.assessment.input_hash
    assert narrow.assessment.communities == wide.assessment.communities
    assert {n.object_id for n in narrow.directory} == {'a','b','c'}
    assert all(n.node_type == 'organization' for n in narrow.directory)
    assert narrow.exploration_edges[0].publication_count == 2
    assert any(c.member_ids == ['c'] and c.publication_ids == ['p3'] for c in narrow.assessment.communities)


def test_institution_granularity_collapses_hierarchy_and_rebuilds_network():
    import json

    from smartlib_platform.graph_analytics.institution_granularity import aggregate_institutions
    from smartlib_platform.graph_analytics.service import _institution_network
    ids = [f'00000000-0000-0000-0000-{i:012d}' for i in range(1, 7)]
    a, a1, a2, deep, b, b1 = ids
    objects = [{'object_id': i, 'canonical_name': i} for i in ids]
    hierarchy = (objects, [{'child_id':a1,'parent_id':a}, {'child_id':a2,'parent_id':a},
                           {'child_id':deep,'parent_id':a1}, {'child_id':b1,'parent_id':b}])
    rows = [{'publication_id':pid,'organization_id':i,'organization_name':i} for pid, members in
            [('p1',[a,a1,deep,a2,b,b1]),('p2',[a,a1,a2]),('p3',[a])] for i in members]
    mapped, _, context = aggregate_institutions(rows,hierarchy)
    net = _institution_network(mapped,1,100,scope_ids=['p1','p2','p3'],aggregation_context=context)
    assert net.assessment.node_count == 2
    assert len(net.exploration_edges) == 1
    assert net.exploration_edges[0].publication_count == 1
    assert max(n.publication_count for n in net.directory) == 3
    expanded, _, expanded_context = aggregate_institutions(rows,hierarchy,json.dumps({'mode':'expanded','root_ids':[a]}))
    ex = _institution_network(expanded,1,100,aggregation_context=expanded_context)
    assert {n.object_id for n in ex.directory} == {a1,a2,b,f"unassigned:{a}"}
    assert a not in {e.source_id for e in ex.exploration_edges}
    assert ex.assessment.input_hash != net.assessment.input_hash
    internal, _, ctx = aggregate_institutions(rows,hierarchy,json.dumps({'mode':'internal','root_ids':[a],
                                    'groups':[{'name':'组合一','member_ids':[a1,a2]}]}))
    inside = _institution_network(internal,1,100,aggregation_context=ctx)
    assert inside.assessment.node_count == 2
    assert inside.assessment.edge_count == 0
    assert next(n.publication_count for n in inside.directory if n.object_id.startswith("group:")) == 2
    assert next(n.publication_count for n in inside.directory if n.object_id.startswith("unassigned:")) == 1
    assert len(ctx['groups']) == 1
    assert 'p3' in ctx['root_only_publication_ids']


def test_institution_granularity_rejects_overlaps_and_excludes_ambiguous_paths():
    import json

    import pytest
    from fastapi import HTTPException

    from smartlib_platform.graph_analytics.institution_granularity import aggregate_institutions
    a,b,c = [f'00000000-0000-0000-0000-{i:012d}' for i in range(1,4)]
    objects = [{'object_id':i,'canonical_name':i} for i in [a,b,c]]
    hierarchy = (objects,[{'child_id':b,'parent_id':a}])
    with pytest.raises(HTTPException,match='同一机构'):
        aggregate_institutions([],hierarchy,json.dumps({'mode':'internal','root_ids':[a], 'groups':[
            {'name':'A','member_ids':[b]}, {'name':'B','member_ids':[b]}]}))
    with pytest.raises(HTTPException):
        aggregate_institutions([],hierarchy,json.dumps({'mode':'internal','root_ids':[b]}))
    rows=[{'publication_id':'p','organization_id':b,'organization_name':b}]
    ambiguous = (objects,[{'child_id':b,'parent_id':a},{'child_id':b,'parent_id':c}])
    mapped,_,context=aggregate_institutions(rows,ambiguous)
    assert mapped == [] and context['invalid_hierarchy_publication_ids']==['p']
    cyclic = (objects,[{'child_id':b,'parent_id':a},{'child_id':a,'parent_id':b}])
    assert aggregate_institutions(rows,cyclic)[0] == []


def test_root_and_expanded_institution_groups_use_post_aggregation_members():
    import json
    import pytest
    from fastapi import HTTPException
    from smartlib_platform.graph_analytics.institution_granularity import aggregate_institutions
    from smartlib_platform.graph_analytics.service import _institution_network
    a, a1, a2, b, b1, c = [f'00000000-0000-0000-0000-{i:012d}' for i in range(1,7)]
    hierarchy=([{'object_id':i,'canonical_name':i} for i in [a,a1,a2,b,b1,c]],
               [{'child_id':a1,'parent_id':a},{'child_id':a2,'parent_id':a},{'child_id':b1,'parent_id':b}])
    rows=[{'publication_id':pid,'organization_id':i,'organization_name':i} for pid, members in
          [('p1',[a,a1,a2,b,b1,c]),('p2',[a1,b1])] for i in members]
    for mode, roots, members, remaining in [('root',[],[a,b],{c}),('expanded',[a],[a1,b],{a2,c})]:
        settings={'mode':mode,'root_ids':roots,'groups':[{'name':'组合','member_ids':members}]}
        mapped,_,ctx=aggregate_institutions(rows,hierarchy,json.dumps(settings))
        group=next(iter(ctx['groups']))
        net=_institution_network(mapped,1,100,aggregation_context=ctx)
        assert {n.object_id for n in net.directory} == remaining | {group}
        assert all(e.source_id != e.target_id for e in net.exploration_edges)
        assert all(e.publication_count == 1 for e in net.exploration_edges)
        assert next(n.publication_count for n in net.directory if n.object_id==group)==2
    for mode, roots, member in [('root',[],a1),('expanded',[a],a),('expanded',[a],b1)]:
        with pytest.raises(HTTPException):
            aggregate_institutions(rows,hierarchy,json.dumps({'mode':mode,'root_ids':roots,
                'groups':[{'name':'错误成员','member_ids':[member]}]}))


def test_author_affiliations_preserve_second_expanded_root_without_duplicate_parent():
    import json
    from smartlib_platform.graph_analytics.institution_granularity import aggregate_institutions
    from smartlib_platform.graph_analytics.service import _institution_network
    a,a1,a2,b,b1,c = [f'00000000-0000-0000-0000-{i:012d}' for i in range(1,7)]
    hierarchy=([{'object_id':i,'canonical_name':i} for i in [a,a1,a2,b,b1,c]],
        [{'child_id':a1,'parent_id':a},{'child_id':a2,'parent_id':a},{'child_id':b1,'parent_id':b}])
    rows=[{'publication_id':'p1','organization_id':i,'organization_name':i} for i in [a,a1,a2,b]]
    direct=[{'publication_id':'p1','organization_id':b1,'organization_name':b1,'relation_id':'author-affiliation'}]
    rows += direct
    rows += [{'publication_id':'p2','organization_id':i,'organization_name':i} for i in [b,c]]
    cfg=json.dumps({'mode':'expanded','root_ids':[a,b],'groups':[
        {'name':'组合1','member_ids':[a1]},{'name':'组合2','member_ids':[a2]}]})
    mapped,_,context=aggregate_institutions(rows,hierarchy,cfg)
    net=_institution_network(mapped,1,100,aggregation_context=context)
    ids={n.object_id for n in net.directory}
    assert {b1,f'unassigned:{b}',c} <= ids
    assert a not in ids and b not in ids
    assert context['root_only_publication_ids']==['p2']
    fallback_edges=[e for e in net.exploration_edges if f'unassigned:{b}' in (e.source_id,e.target_id)]
    assert len(fallback_edges)==1 and fallback_edges[0].publication_count==1
    assert len([e for e in net.exploration_edges if b1 in (e.source_id,e.target_id)])==2


def test_saved_workbench_preferences_roundtrip_and_reject_invalid_values():
    import pytest
    from pydantic import ValidationError
    from smartlib_platform.graph_analytics.models import AnalysisDefinition

    prefs = {
        'discipline.scheme': 'NSFC:2026', 'discipline.mode': 'intersection',
        'direction.coverage': True,
        'direction.institution': {'id': str(UUID(int=5)), 'name': '学校', 'kind': 'organization'},
        'institution.view': {'edgeLimit': 1000, 'peopleFocusId': str(UUID(int=6))},
        'people.clusterMinimum': 4,
    }
    definition = AnalysisDefinition(workspace_settings=prefs, people_include_external=True, edge_limit=1000)
    restored = AnalysisDefinition.model_validate_json(definition.model_dump_json())
    assert restored.workspace_settings == prefs
    assert restored.people_include_external and restored.edge_limit == 1000
    for invalid in ({'direction.institution': {'id': 'bad', 'name': '学校', 'kind': 'organization'}},
                    {'direction.coverage': 'false'}, {'people.clusterMinimum': 0},
                    {'institution.view': {'edgeLimit': -1}}, {'unknown': True}):
        with pytest.raises(ValidationError):
            AnalysisDefinition(workspace_settings=invalid)
    with pytest.raises(ValidationError):
        AnalysisDefinition(start_year=2026, end_year=2020)


def test_community_research_keeps_link_basis_versions_and_paper_deduplication():
    from types import SimpleNamespace
    from smartlib_platform.graph_analytics.community_research import enrich_community_research
    communities = [SimpleNamespace(publication_ids=['p1','p2','p3','p1']), SimpleNamespace(publication_ids=['p1']), SimpleNamespace(publication_ids=[])]
    a = SimpleNamespace(communities=communities)
    def fund(pid, basis, target, kind='kind1'):
        return dict(publication_id=pid, basis=basis, target_id=target, target_name=target,
                    kind_id=kind, kind_name=kind, category_label='境内中央公共资助', relation_id=f'{pid}-{basis}-{target}')
    def direction(pid, version='2026', oid='d1', role='primary'):
        return dict(publication_id=pid, scheme='NSFC', scheme_version=version, object_id=oid,
                    canonical_name=oid, discipline_code='H01', classification_role=role, relation_id=f'{pid}-{version}-{oid}')
    funding = [fund('p1','funded','project1'),fund('p1','funded','project1'),fund('p1','funded','project2'),
               fund('p1','representative','project1'),fund('p2','representative','project2'),
               fund('outside','funded','project3')]
    directions = [direction('p1'),direction('p1'),direction('p2',oid='d2',role='secondary'),direction('p1','2025')]
    enrich_community_research(a, funding, directions)
    r = communities[0].research
    assert r.funded_publication_ids == ['p1']
    assert r.representative_publication_ids == ['p1','p2']
    assert r.unlinked_publication_ids == r.unclassified_publication_ids == ['p3']
    funded = next(f for f in r.funding if f.basis == 'funded')
    assert funded.category_label == '境内中央公共资助'
    assert funded.project_ids == ['project1','project2'] and funded.publication_ids == ['p1']
    assert len(r.directions) == 3
    assert all(x.publication_ids == ['p1'] for x in r.intersections if x.funding_key == funded.key)
    assert len([x for x in r.intersections if x.funding_key == funded.key]) == 2
    assert communities[1].research.funded_publication_ids == ['p1']  # A paper may support multiple communities.
    assert communities[2].research.intersections == []
    fingerprint=r.input_hash
    enrich_community_research(a, list(reversed(funding)), list(reversed(directions)))
    assert communities[0].research.input_hash == fingerprint


def test_community_research_retains_projects_without_kind_and_missing_classification():
    from types import SimpleNamespace
    from smartlib_platform.graph_analytics.community_research import enrich_community_research
    a=SimpleNamespace(communities=[SimpleNamespace(publication_ids=['p1'])])
    enrich_community_research(a, [dict(publication_id='p1',basis='funded',target_id='project1',target_name='项目一',
        kind_id=None,kind_name=None,relation_id='r1')], [])
    r=a.communities[0].research
    assert r.funding[0].name == '未登记项目种类'
    assert r.funding[0].project_ids == ['project1']
    assert r.unclassified_publication_ids == ['p1'] and not r.intersections


def test_center_prominence_rejects_nearly_equal_scores_and_preserves_all_members():
    import networkx as nx
    from smartlib_platform.graph_analytics.cooperation import community_center_metrics
    graph = nx.complete_graph(20)
    nx.set_edge_attributes(graph, 1, 'weight')
    graph[0][1]['weight'] = 1.01
    rows = community_center_metrics(graph)
    assert len(rows) == 20 and not any(r.roles for r in rows)
    star = nx.star_graph(99)
    nx.set_edge_attributes(star, 1, 'weight')
    rows = community_center_metrics(star)
    assert len(rows) == 100 and [r.person_id for r in rows if r.roles] == ['0']
