from datetime import UTC, datetime
from uuid import UUID

from smartlib_platform.knowledge.service import (
    get_institution_associations,
    get_object_detail,
    get_organization_hierarchy_options,
    get_project_kind_options,
    get_publication_resource_reference,
    list_object_catalog,
)


class Cursor:
    def __init__(self, *, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, cursors):
        self.cursors = cursors
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        return self.cursors.pop(0)


def test_catalog_filters_counts_and_pages_real_objects() -> None:
    now = datetime(2026, 9, 3, tzinfo=UTC)
    row = {
        "object_id": UUID("85000000-0000-4000-8000-000000000001"),
        "object_type": "publication",
        "canonical_name": "A verified publication",
        "description": "Crossref verified metadata.",
        "visibility": "campus",
        "quality_state": "validated",
        "review_state": "approved",
        "version": 1,
        "attributes": {"doi": "10.1000/example", "year": 2025},
        "created_by": UUID("71000000-0000-4000-8000-000000000001"),
        "created_at": now,
        "updated_at": now,
    }
    connection = Connection([Cursor(row={"total": 155}), Cursor(rows=[row])])

    result = list_object_catalog(
        connection,
        object_types=["publication"],
        query="verified",
        page=2,
        page_size=20,
        sort="year",
    )

    assert result.total == 155
    assert result.items[0].attributes["doi"] == "10.1000/example"
    assert "object_type = ANY(%s)" in connection.calls[0][0]
    assert connection.calls[1][1][-2:] == (20, 20)


def test_catalog_linked_only_excludes_taxonomy_only_metadata() -> None:
    connection = Connection([Cursor(row={"total": 0}), Cursor(rows=[])])

    list_object_catalog(
        connection,
        object_types=["organization", "department", "discipline"],
        linked_only=True,
        sort="name",
    )

    count_query = connection.calls[0][0]
    assert "relation.predicate NOT LIKE 'taxonomy.%%'" in count_query
    assert "relation_assertion" in count_query
    assert "affiliation_organization_ids" not in count_query
    assert "review_state NOT IN ('rejected','superseded')" in count_query
    assert "relation.review_state NOT IN ('rejected','superseded')" in count_query
    assert "endpoint.object_id=relation.subject_id" in count_query
    assert "endpoint.object_id=relation.object_id" in count_query


def test_catalog_returns_real_organization_hierarchy() -> None:
    now = datetime(2026, 9, 8, tzinfo=UTC)
    child_id = UUID("85000000-0000-4000-8000-000000000010")
    parent_id = UUID("85000000-0000-4000-8000-000000000011")
    row = {
        "object_id": child_id,
        "object_type": "organization",
        "canonical_name": "基础医学院",
        "description": None,
        "visibility": "campus",
        "quality_state": "validated",
        "review_state": "approved",
        "version": 1,
        "attributes": {"organization_level": "2"},
        "created_by": UUID("71000000-0000-4000-8000-000000000001"),
        "created_at": now,
        "updated_at": now,
    }
    connection = Connection([
        Cursor(row={"total": 1}),
        Cursor(rows=[row]),
        Cursor(rows=[{
            "origin_id": child_id,
            "node_id": parent_id,
            "object_type": "organization",
            "canonical_name": "大连医科大学",
            "depth": 1,
        }]),
    ])

    result = list_object_catalog(
        connection,
        object_types=["organization"],
        linked_only=True,
        sort="name",
    )

    assert [node.canonical_name for node in result.items[0].hierarchy_path] == ["大连医科大学"]
    assert "WITH RECURSIVE parent_edges" in connection.calls[2][0]
    assert "parent.review_state NOT IN ('rejected','superseded')" in connection.calls[2][0]


def test_catalog_filters_by_organization_scope_and_level() -> None:
    root_id = UUID("85000000-0000-4000-8000-000000000011")
    connection = Connection([Cursor(row={"total": 0}), Cursor(rows=[])])

    list_object_catalog(
        connection,
        object_types=["organization", "department"],
        linked_only=True,
        hierarchy_root_id=root_id,
        organization_level=2,
        sort="name",
    )

    count_query, params = connection.calls[0]
    assert "WITH RECURSIVE root(root_id)" in count_query
    assert "object_type IN ('organization','department')" in count_query
    assert "(attributes->>'organization_level')::int = %s" in count_query
    assert params[-2:] == (root_id, 2)


def test_catalog_filters_projects_by_project_kind() -> None:
    project_kind_id = UUID("85000000-0000-4000-8000-000000000099")
    connection = Connection([Cursor(row={"total": 0}), Cursor(rows=[])])

    list_object_catalog(
        connection,
        object_types=["project"],
        project_kind_id=project_kind_id,
        sort="year",
    )

    count_query, params = connection.calls[0]
    assert "object_type = 'project'" in count_query
    assert "attributes->>'funding_program_id' = %s" in count_query
    assert "relation.predicate='project.under_program'" in count_query
    assert params[-2:] == (str(project_kind_id), project_kind_id)


def test_organization_hierarchy_options_return_roots_and_levels() -> None:
    root_id = UUID("85000000-0000-4000-8000-000000000011")
    connection = Connection([
        Cursor(rows=[{
            "object_id": root_id,
            "canonical_name": "大连医科大学",
            "descendant_count": 48,
        }]),
        Cursor(rows=[{"organization_level": 1}, {"organization_level": 2}]),
    ])

    result = get_organization_hierarchy_options(connection)

    assert result.scopes[0].canonical_name == "大连医科大学"
    assert result.scopes[0].descendant_count == 48
    assert result.levels == [1, 2]
    assert "HAVING COUNT(DISTINCT descendants.object_id)" in connection.calls[0][0]
    assert "root.review_state NOT IN ('rejected','superseded')" in connection.calls[0][0]
    assert "review_state NOT IN ('rejected','superseded')" in connection.calls[1][0]


def test_project_kind_options_return_only_kinds_linked_to_projects() -> None:
    project_kind_id = UUID("85000000-0000-4000-8000-000000000099")
    connection = Connection([Cursor(rows=[{
        "object_id": project_kind_id,
        "canonical_name": "国家自然科学基金面上项目",
        "category_label": "境内中央公共资助",
        "project_count": 36,
    }])])

    result = get_project_kind_options(connection)

    assert result.items[0].canonical_name == "国家自然科学基金面上项目"
    assert result.items[0].category_label == "境内中央公共资助"
    assert result.items[0].project_count == 36
    query = connection.calls[0][0]
    assert "record_kind'='funding_category'" in query
    assert "relation.predicate='project.under_program'" in query


def test_institution_associations_follow_scholars_to_distinct_outputs() -> None:
    organization_id = UUID("85000000-0000-4000-8000-000000000011")
    scholar_id = UUID("85000000-0000-4000-8000-000000000012")
    publication_id = UUID("85000000-0000-4000-8000-000000000013")
    connection = Connection([
        Cursor(row={"scholar_count": 3, "output_count": 12}),
        Cursor(rows=[{
            "object_id": scholar_id,
            "canonical_name": "测试学者",
            "output_count": 4,
        }]),
        Cursor(rows=[{
            "object_id": publication_id,
            "object_type": "publication",
            "canonical_name": "测试论文",
            "year": 2025,
            "scholar_count": 2,
        }]),
    ])

    result = get_institution_associations(connection, organization_id, limit=1)

    assert result.scholar_count == 3
    assert result.output_count == 12
    assert result.scholars[0].output_count == 4
    assert result.outputs[0].scholar_count == 2
    assert result.truncated is True
    assert all("institution_scope" in query for query, _ in connection.calls)
    assert "person.authoritatively_affiliated_with" in connection.calls[0][0]
    assert "person.authored" in connection.calls[0][0]
    assert "person.object_type='person'" in connection.calls[0][0]
    assert connection.calls[1][1] == (organization_id, 1)
    assert connection.calls[2][1] == (organization_id, 1)


def test_publication_detail_assembles_metadata_authors_identifiers_and_fulltext() -> None:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    publication_id = UUID("85000000-0000-4000-8000-000000000001")
    object_row = {
        "object_id": publication_id,
        "object_type": "publication",
        "canonical_name": "A verified publication",
        "description": "Verified abstract.",
        "visibility": "campus",
        "quality_state": "validated",
        "review_state": "approved",
        "version": 2,
        "attributes": {"doi": "10.1000/example", "year": 2025},
        "created_by": UUID("71000000-0000-4000-8000-000000000001"),
        "created_at": now,
        "updated_at": now,
    }
    metadata = {
        "title": "A verified publication",
        "subtitle": None,
        "abstract": "Verified abstract.",
        "journal_name": "Journal of Tests",
        "journal_abbreviation": "J Test",
        "issn": None,
        "eissn": None,
        "publication_year": 2025,
        "published_online_at": None,
        "published_print_at": None,
        "volume": "12",
        "issue": "3",
        "pages": "1-9",
        "article_number": None,
        "publication_type": "journal-article",
        "language_code": "en",
        "publication_status": "published",
        "metadata_version": 2,
        "identity_state": "verified",
        "enrichment_state": "complete",
        "fulltext_state": "extracted",
        "last_enriched_at": now,
    }
    connection = Connection(
        [
            Cursor(row=object_row),
            Cursor(row=metadata),
            Cursor(
                rows=[
                    {
                        "identifier_type": "doi",
                        "value": "10.1000/example",
                        "is_primary": True,
                        "verification_status": "matched",
                    }
                ]
            ),
            Cursor(
                rows=[
                    {
                        "author_order": 1,
                        "author_display_name": "Test Author",
                        "orcid": None,
                        "affiliation_raw": "Test University",
                        "is_first_author": True,
                        "is_co_first_author": False,
                        "is_corresponding_author": True,
                        "is_co_corresponding_author": False,
                        "role_source": "fulltext",
                        "role_evidence": {},
                        "affiliation_names": ["Test University"],
                        "person_object_id": None,
                        "verification_status": "matched",
                    }
                ]
            ),
            Cursor(
                rows=[
                    {
                        "fulltext_resource_id": UUID("86000000-0000-4000-8000-000000000001"),
                        "file_name": "paper.pdf",
                        "mime_type": "application/pdf",
                        "resource_role": "article",
                        "size_bytes": 1024,
                        "extraction_state": "extracted",
                        "license_tags": ["controlled-file"],
                    }
                ]
            ),
        ]
    )

    connection.cursors.append(Cursor(rows=[{
        "record_id": publication_id, "metric_system": "jcr", "metric_year": 2025,
        "release_id": publication_id, "release_label": "JCR 2025", "impact_factor": 8.2,
        "quartile": "Q1", "categories": ["Biology"], "source_row_number": 10,
    }]))
    result = get_object_detail(connection, publication_id)

    assert result is not None
    assert result.type_details["journal_name"] == "Journal of Tests"
    assert result.identifiers[0].value == "10.1000/example"
    assert result.contributors[0].roles == ["first_author", "corresponding_author"]
    assert result.resources[0].extraction_state == "extracted"
    assert result.resources[0].resource_role == "article"
    assert result.journal_metrics[0].impact_factor == 8.2
    assert result.journal_metrics[0].categories == ["Biology"]
    query, parameters = connection.calls[-1]
    assert "release.metric_year=metadata.publication_year" in query
    assert "journal_metric_analysis_eligible" in query
    assert parameters == ([publication_id],)


def test_project_detail_uses_extensible_attributes_without_publication_queries() -> None:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    project_id = UUID("85000000-0000-4000-8000-000000000058")
    connection = Connection(
        [
            Cursor(
                row={
                    "object_id": project_id,
                    "object_type": "project",
                    "canonical_name": "A funded project",
                    "description": "Project details pending.",
                    "visibility": "restricted",
                    "quality_state": "unverified",
                    "review_state": "pending",
                    "version": 1,
                    "attributes": {"year": 2026, "principal_investigator_name": "丁俊莹"},
                    "created_by": UUID("71000000-0000-4000-8000-000000000001"),
                    "created_at": now,
                    "updated_at": now,
                }
            )
        ]
    )

    result = get_object_detail(connection, project_id)

    assert result is not None
    assert result.type_details["principal_investigator_name"] == "丁俊莹"
    assert len(connection.calls) == 1


def test_publication_resource_reference_is_scoped_to_publication_and_resource() -> None:
    publication_id = UUID("85000000-0000-4000-8000-000000000001")
    resource_id = UUID("86000000-0000-4000-8000-000000000001")
    connection = Connection(
        [
            Cursor(
                row={
                    "file_name": "paper.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 2048,
                    "storage_uri": "s3://smartlib-publications/publications/example/paper.pdf",
                }
            )
        ]
    )

    result = get_publication_resource_reference(connection, publication_id, resource_id)

    assert result is not None
    assert result.file_name == "paper.pdf"
    assert connection.calls[0][1] == (publication_id, resource_id)
    assert "publication.object_type='publication'" in connection.calls[0][0]
