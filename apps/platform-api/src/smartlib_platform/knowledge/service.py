from dataclasses import dataclass
from uuid import UUID

from psycopg.types.json import Jsonb

from smartlib_platform.foundation.database import DbConnection
from smartlib_platform.identities.service import IDENTITY_TYPES, get_identity
from smartlib_platform.publications.analysis_metrics import load_journal_metric_rows

from .models import (
    InstitutionAssociatedOutputView,
    InstitutionAssociatedScholarView,
    InstitutionAssociationSummary,
    KnowledgeObjectContributorView,
    KnowledgeObjectCreate,
    KnowledgeObjectDetailView,
    KnowledgeObjectHierarchyNode,
    KnowledgeObjectIdentifierView,
    KnowledgeObjectPage,
    KnowledgeObjectResourceView,
    KnowledgeObjectView,
    OrganizationHierarchyOptions,
    OrganizationHierarchyScope,
    ProjectKindOption,
    ProjectKindOptions,
    PublicationJournalMetricDetail,
)

_COLUMNS = """object_id, object_type, canonical_name, description, visibility, quality_state,
              review_state, version, attributes, created_by, created_at, updated_at"""


@dataclass(frozen=True)
class PublicationResourceReference:
    file_name: str
    mime_type: str
    size_bytes: int | None
    storage_uri: str


def list_objects(connection: DbConnection, limit: int = 50) -> list[KnowledgeObjectView]:
    rows = connection.execute(
        f"SELECT {_COLUMNS} FROM smartlib.knowledge_object "
        "WHERE system_to='infinity'::timestamptz "
        "AND review_state NOT IN ('rejected','superseded') "
        "ORDER BY updated_at DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return [KnowledgeObjectView.model_validate(row) for row in rows]


def list_object_catalog(
    connection: DbConnection,
    *,
    object_types: list[str] | None = None,
    linked_only: bool = False,
    query: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort: str = "updated",
    hierarchy_root_id: UUID | None = None,
    organization_level: int | None = None,
    project_kind_id: UUID | None = None,
) -> KnowledgeObjectPage:
    clauses: list[str] = ["system_to='infinity'::timestamptz",
                          "review_state NOT IN ('rejected','superseded')"]
    params: list[object] = []
    if object_types:
        clauses.append("object_type = ANY(%s)")
        params.append(object_types)
    if project_kind_id is not None:
        clauses.append("object_type = 'project'")
        clauses.append(
            """(
                attributes->>'funding_program_id' = %s
                OR EXISTS (
                    SELECT 1
                      FROM smartlib.relation_assertion relation
                     WHERE relation.subject_id=smartlib.knowledge_object.object_id
                       AND relation.object_id=%s
                       AND relation.predicate='project.under_program'
                       AND relation.review_state NOT IN ('rejected','superseded')
                       AND relation.system_to='infinity'::timestamptz
                       AND relation.valid_from <= clock_timestamp()
                       AND relation.valid_to > clock_timestamp()
                )
            )"""
        )
        params.extend([str(project_kind_id), project_kind_id])
    if hierarchy_root_id is not None or organization_level is not None:
        clauses.append("object_type IN ('organization','department')")
    if hierarchy_root_id is not None:
        clauses.append(
            """EXISTS (
                WITH RECURSIVE root(root_id) AS (VALUES (%s::uuid)),
                parent_edges AS (
                    SELECT relation.subject_id AS child_id,relation.object_id AS parent_id
                      FROM smartlib.relation_assertion relation
                     WHERE relation.predicate IN ('organization.part_of','department.part_of')
                       AND relation.review_state NOT IN ('rejected','superseded')
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.subject_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.object_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                       AND relation.system_to='infinity'::timestamptz
                       AND relation.valid_from <= clock_timestamp()
                       AND relation.valid_to > clock_timestamp()
                    UNION ALL
                    SELECT relation.object_id AS child_id,relation.subject_id AS parent_id
                      FROM smartlib.relation_assertion relation
                     WHERE relation.predicate='organization.has_department'
                       AND relation.review_state NOT IN ('rejected','superseded')
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.subject_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.object_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                       AND relation.system_to='infinity'::timestamptz
                       AND relation.valid_from <= clock_timestamp()
                       AND relation.valid_to > clock_timestamp()
                ), descendants(object_id,visited) AS (
                    SELECT root_id,ARRAY[root_id] FROM root
                    UNION ALL
                    SELECT edge.child_id,descendants.visited || edge.child_id
                      FROM descendants
                      JOIN parent_edges edge ON edge.parent_id=descendants.object_id
                     WHERE NOT edge.child_id=ANY(descendants.visited)
                )
                SELECT 1 FROM descendants
                 WHERE descendants.object_id=smartlib.knowledge_object.object_id
            )"""
        )
        params.append(hierarchy_root_id)
    if organization_level is not None:
        clauses.append(
            "attributes->>'organization_level' ~ '^[0-9]+$' "
            "AND (attributes->>'organization_level')::int = %s"
        )
        params.append(organization_level)
    if linked_only:
        clauses.append(
            """(
                EXISTS (
                    SELECT 1
                      FROM smartlib.relation_assertion relation
                     WHERE relation.object_id IS NOT NULL
                       AND relation.review_state NOT IN ('rejected','superseded')
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.subject_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.object_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                       AND relation.system_to = 'infinity'::timestamptz
                       AND relation.valid_from <= clock_timestamp()
                       AND relation.valid_to > clock_timestamp()
                       AND relation.predicate NOT LIKE 'taxonomy.%%'
                       AND (
                           relation.subject_id = smartlib.knowledge_object.object_id
                           OR relation.object_id = smartlib.knowledge_object.object_id
                       )
                )
            )"""
        )
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        clauses.append("""(canonical_name ILIKE %s OR description ILIKE %s OR attributes::text ILIKE %s
            OR EXISTS(SELECT 1 FROM unnest(smartlib.identity_search_aliases(object_id)) n WHERE n ILIKE %s)
            OR EXISTS(SELECT 1 FROM smartlib.person_identifier i
                      WHERE i.object_id=smartlib.knowledge_object.object_id
                      AND i.verification_status='matched' AND i.normalized_value ILIKE %s)
            OR EXISTS(SELECT 1 FROM smartlib.organization_identifier i
                      WHERE i.object_id=smartlib.knowledge_object.object_id
                      AND i.verification_status='matched' AND i.normalized_value ILIKE %s))""")
        params.extend([pattern] * 6)
    where = " AND ".join(clauses) if clauses else "TRUE"
    order_by = {
        "name": "canonical_name ASC, updated_at DESC",
        "year": (
            "(CASE WHEN object_type='publication' THEN (SELECT publication_year FROM smartlib.publication_metadata WHERE publication_id=smartlib.knowledge_object.object_id) WHEN attributes->>'year' ~ '^[0-9]{4}$' "
            "THEN (attributes->>'year')::int END) DESC NULLS LAST, canonical_name ASC"
        ),
        "updated": "updated_at DESC, canonical_name ASC",
    }[sort]
    total_row = connection.execute(
        f"SELECT COUNT(*) AS total FROM smartlib.knowledge_object WHERE {where}", tuple(params)
    ).fetchone()
    total = int(total_row["total"]) if total_row else 0
    offset = (page - 1) * page_size
    rows = connection.execute(
        f"SELECT {_COLUMNS}, (SELECT publication_year FROM smartlib.publication_metadata WHERE publication_id=smartlib.knowledge_object.object_id) AS publication_year FROM smartlib.knowledge_object WHERE {where} "
        f"ORDER BY {order_by} LIMIT %s OFFSET %s",
        (*params, page_size, offset),
    ).fetchall()
    hierarchy_by_object = _load_catalog_hierarchy(
        connection,
        [row["object_id"] for row in rows if row["object_type"] in {"organization", "department"}],
    )
    return KnowledgeObjectPage(
        items=[KnowledgeObjectView.model_validate({
            **row,
            "hierarchy_path": hierarchy_by_object.get(row["object_id"], []),
        }) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_organization_hierarchy_options(
    connection: DbConnection,
) -> OrganizationHierarchyOptions:
    scope_rows = connection.execute(
        """WITH RECURSIVE parent_edges AS (
                 SELECT relation.subject_id AS child_id,relation.object_id AS parent_id
                   FROM smartlib.relation_assertion relation
                  WHERE relation.predicate IN ('organization.part_of','department.part_of')
                    AND relation.review_state NOT IN ('rejected','superseded')
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.subject_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.object_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                    AND relation.system_to='infinity'::timestamptz
                    AND relation.valid_from <= clock_timestamp()
                    AND relation.valid_to > clock_timestamp()
                 UNION ALL
                 SELECT relation.object_id AS child_id,relation.subject_id AS parent_id
                   FROM smartlib.relation_assertion relation
                  WHERE relation.predicate='organization.has_department'
                    AND relation.review_state NOT IN ('rejected','superseded')
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.subject_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.object_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                    AND relation.system_to='infinity'::timestamptz
                    AND relation.valid_from <= clock_timestamp()
                    AND relation.valid_to > clock_timestamp()
             ), roots AS (
                 SELECT DISTINCT edge.parent_id AS root_id
                   FROM parent_edges edge
                  WHERE NOT EXISTS (
                      SELECT 1 FROM parent_edges upper_edge
                       WHERE upper_edge.child_id=edge.parent_id
                  )
             ), descendants(root_id,object_id,visited) AS (
                 SELECT root_id,root_id,ARRAY[root_id] FROM roots
                 UNION ALL
                 SELECT descendants.root_id,edge.child_id,descendants.visited || edge.child_id
                   FROM descendants
                   JOIN parent_edges edge ON edge.parent_id=descendants.object_id
                  WHERE NOT edge.child_id=ANY(descendants.visited)
             )
             SELECT root.object_id,root.canonical_name,
                    COUNT(DISTINCT descendants.object_id) FILTER (
                        WHERE descendants.object_id <> root.object_id
                    ) AS descendant_count
               FROM roots
               JOIN smartlib.knowledge_object root ON root.object_id=roots.root_id
               JOIN descendants ON descendants.root_id=roots.root_id
              WHERE root.system_to='infinity'::timestamptz
                AND root.review_state NOT IN ('rejected','superseded')
                AND root.object_type IN ('organization','department')
              GROUP BY root.object_id,root.canonical_name
             HAVING COUNT(DISTINCT descendants.object_id) FILTER (
                        WHERE descendants.object_id <> root.object_id
                    ) > 0
              ORDER BY root.canonical_name"""
    ).fetchall()
    level_rows = connection.execute(
        """SELECT DISTINCT (attributes->>'organization_level')::int AS organization_level
             FROM smartlib.knowledge_object
            WHERE system_to='infinity'::timestamptz
              AND review_state NOT IN ('rejected','superseded')
              AND object_type IN ('organization','department')
              AND attributes->>'organization_level' ~ '^[0-9]+$'
            ORDER BY organization_level"""
    ).fetchall()
    return OrganizationHierarchyOptions(
        scopes=[OrganizationHierarchyScope.model_validate(row) for row in scope_rows],
        levels=[int(row["organization_level"]) for row in level_rows],
    )


def get_project_kind_options(connection: DbConnection) -> ProjectKindOptions:
    rows = connection.execute(
        """SELECT kind.object_id,
                  kind.canonical_name,
                  NULLIF(kind.attributes->>'funding_source_category_label','') AS category_label,
                  COUNT(DISTINCT project.object_id) AS project_count
             FROM smartlib.knowledge_object kind
             JOIN smartlib.knowledge_object project
               ON project.object_type='project'
              AND project.system_to='infinity'::timestamptz
              AND project.review_state NOT IN ('rejected','superseded')
              AND (
                  project.attributes->>'funding_program_id'=kind.object_id::text
                  OR EXISTS (
                      SELECT 1
                        FROM smartlib.relation_assertion relation
                       WHERE relation.subject_id=project.object_id
                         AND relation.object_id=kind.object_id
                         AND relation.predicate='project.under_program'
                         AND relation.review_state NOT IN ('rejected','superseded')
                         AND relation.system_to='infinity'::timestamptz
                         AND relation.valid_from <= clock_timestamp()
                         AND relation.valid_to > clock_timestamp()
                  )
              )
            WHERE kind.object_type='funding_program'
              AND kind.system_to='infinity'::timestamptz
              AND kind.review_state NOT IN ('rejected','superseded')
              AND kind.attributes->>'record_kind'='funding_category'
            GROUP BY kind.object_id,kind.canonical_name,
                     kind.attributes->>'funding_source_category_label'
            ORDER BY category_label NULLS LAST,kind.canonical_name"""
    ).fetchall()
    return ProjectKindOptions(items=[ProjectKindOption.model_validate(row) for row in rows])


def _load_catalog_hierarchy(
    connection: DbConnection,
    object_ids: list[UUID],
) -> dict[UUID, list[KnowledgeObjectHierarchyNode]]:
    if not object_ids:
        return {}
    rows = connection.execute(
        """WITH RECURSIVE parent_edges AS (
                 SELECT relation.subject_id AS child_id,relation.object_id AS parent_id
                   FROM smartlib.relation_assertion relation
                  WHERE relation.predicate IN ('organization.part_of','department.part_of')
                    AND relation.review_state NOT IN ('rejected','superseded')
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.subject_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.object_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                    AND relation.system_to='infinity'::timestamptz
                    AND relation.valid_from <= clock_timestamp()
                    AND relation.valid_to > clock_timestamp()
                 UNION ALL
                 SELECT relation.object_id AS child_id,relation.subject_id AS parent_id
                   FROM smartlib.relation_assertion relation
                  WHERE relation.predicate='organization.has_department'
                    AND relation.review_state NOT IN ('rejected','superseded')
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.subject_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                       AND EXISTS (SELECT 1 FROM smartlib.knowledge_object endpoint
                            WHERE endpoint.object_id=relation.object_id
                              AND endpoint.system_to='infinity'::timestamptz
                              AND endpoint.review_state NOT IN ('rejected','superseded'))
                    AND relation.system_to='infinity'::timestamptz
                    AND relation.valid_from <= clock_timestamp()
                    AND relation.valid_to > clock_timestamp()
             ), ancestry AS (
                 SELECT edge.child_id AS origin_id,parent.object_id AS node_id,
                        parent.object_type,parent.canonical_name,1 AS depth,
                        ARRAY[edge.child_id,parent.object_id] AS visited
                   FROM parent_edges edge
                   JOIN smartlib.knowledge_object parent ON parent.object_id=edge.parent_id
                  WHERE edge.child_id=ANY(%s)
                    AND parent.system_to='infinity'::timestamptz
                    AND parent.review_state NOT IN ('rejected','superseded')
                 UNION ALL
                 SELECT ancestry.origin_id,parent.object_id,parent.object_type,
                        parent.canonical_name,ancestry.depth+1,
                        ancestry.visited || parent.object_id
                   FROM ancestry
                   JOIN parent_edges edge ON edge.child_id=ancestry.node_id
                   JOIN smartlib.knowledge_object parent ON parent.object_id=edge.parent_id
                  WHERE ancestry.depth < 8
                    AND parent.system_to='infinity'::timestamptz
                    AND parent.review_state NOT IN ('rejected','superseded')
                    AND NOT parent.object_id=ANY(ancestry.visited)
             ), deduplicated AS (
                 SELECT DISTINCT ON (origin_id,node_id)
                        origin_id,node_id,object_type,canonical_name,depth
                   FROM ancestry
                  ORDER BY origin_id,node_id,depth
             )
             SELECT origin_id,node_id,object_type,canonical_name,depth
               FROM deduplicated
              ORDER BY origin_id,depth DESC,canonical_name""",
        (object_ids,),
    ).fetchall()
    result: dict[UUID, list[KnowledgeObjectHierarchyNode]] = {}
    for row in rows:
        result.setdefault(row["origin_id"], []).append(KnowledgeObjectHierarchyNode(
            object_id=row["node_id"],
            object_type=row["object_type"],
            canonical_name=row["canonical_name"],
        ))
    return result


def get_object(connection: DbConnection, object_id: UUID) -> KnowledgeObjectView | None:
    row = connection.execute(
        f"SELECT {_COLUMNS} FROM smartlib.knowledge_object "
        "WHERE object_id=(SELECT COALESCE((attributes->>'merged_into_publication_id')::uuid,object_id) "
        "FROM smartlib.knowledge_object WHERE object_id=%s) "
        "AND system_to='infinity'::timestamptz", (object_id,)
    ).fetchone()
    return KnowledgeObjectView.model_validate(row) if row else None


def get_object_detail(connection: DbConnection, object_id: UUID) -> KnowledgeObjectDetailView | None:
    knowledge_object = get_object(connection, object_id)
    if knowledge_object is None:
        return None
    object_id = knowledge_object.object_id
    if knowledge_object.object_type in IDENTITY_TYPES:
        identity = get_identity(connection, object_id)
        return KnowledgeObjectDetailView(
            object=knowledge_object,
            type_details={**knowledge_object.attributes, "identity_profile": identity["profile"],
                          "name_variants": identity["names"]},
            identifiers=[KnowledgeObjectIdentifierView(
                identifier_type=i["identifier_type"],value=i["normalized_value"],
                is_primary=True,verification_status=i["verification_status"])
                for i in identity["identifiers"]],
            institution_associations=(
                get_institution_associations(connection, object_id)
                if knowledge_object.object_type in {"organization", "department"}
                else None
            ),
        )
    if knowledge_object.object_type != "publication":
        return KnowledgeObjectDetailView(
            object=knowledge_object,
            type_details=knowledge_object.attributes,
        )

    metadata = connection.execute(
        """SELECT title,subtitle,abstract,journal_name,journal_abbreviation,issn,eissn,
                  publication_year,published_online_at,published_print_at,volume,issue,pages,
                  article_number,publication_type,language_code,publication_status,
                  metadata_version,identity_state,enrichment_state,fulltext_state,last_enriched_at
             FROM smartlib.publication_metadata WHERE publication_id = %s""",
        (object_id,),
    ).fetchone()
    identifier_rows = connection.execute(
        """SELECT identifier_type,normalized_value AS value,is_primary,verification_status
             FROM smartlib.publication_identifier
            WHERE publication_id = %s AND verification_status <> 'rejected'
            ORDER BY is_primary DESC,identifier_type,normalized_value""",
        (object_id,),
    ).fetchall()
    contributor_rows = connection.execute(
        """SELECT authorship.author_order,
                  COALESCE(person.canonical_name,authorship.author_name_raw) AS author_display_name,
                  authorship.orcid,authorship.affiliation_raw,authorship.is_first_author,
                  authorship.is_co_first_author,authorship.is_corresponding_author,
                  authorship.is_co_corresponding_author,authorship.person_object_id,
                  authorship.verification_status,authorship.role_source,authorship.role_evidence,
                  COALESCE(organizations.names,ARRAY[]::text[]) AS affiliation_names
             FROM smartlib.publication_authorship authorship
             LEFT JOIN smartlib.knowledge_object person
               ON person.object_id=authorship.person_object_id
             LEFT JOIN LATERAL (
                 SELECT array_agg(DISTINCT org.canonical_name ORDER BY org.canonical_name) AS names
                   FROM smartlib.analysis_relation relation
                   JOIN smartlib.knowledge_object org ON org.object_id=relation.object_id
                  WHERE relation.predicate='person.affiliated_with'
                    
                    AND relation.system_to='infinity'::timestamptz
                    AND relation.valid_from <= clock_timestamp()
                    AND relation.valid_to > clock_timestamp()
                    AND relation.subject_id=authorship.person_object_id
                    AND relation.context_object_id=authorship.publication_id
                    AND smartlib.publication_relation_authorship(relation.relation_id)=
                        authorship.publication_authorship_id
             ) organizations ON true
            WHERE authorship.publication_id = %s
              AND authorship.verification_status <> 'rejected'
            ORDER BY authorship.author_order""",
        (object_id,),
    ).fetchall()
    resource_rows = connection.execute(
        """SELECT fulltext_resource_id,file_name,mime_type,resource_role,size_bytes,
                  extraction_state,license_tags
             FROM smartlib.publication_fulltext_resource
            WHERE publication_id = %s
            ORDER BY CASE resource_role WHEN 'article' THEN 0 WHEN 'correction' THEN 1 ELSE 2 END,
                     created_at DESC""",
        (object_id,),
    ).fetchall()

    contributors = []
    for row in contributor_rows:
        roles = []
        if row["is_first_author"]:
            roles.append("first_author")
        if row["is_co_first_author"]:
            roles.append("co_first_author")
        if row["is_corresponding_author"]:
            roles.append("corresponding_author")
        if row["is_co_corresponding_author"]:
            roles.append("co_corresponding_author")
        contributors.append(
            KnowledgeObjectContributorView(
                order=row["author_order"],
                name=row["author_display_name"],
                orcid=row["orcid"],
                affiliation=row["affiliation_raw"],
                affiliations=list(row["affiliation_names"] or []),
                roles=roles,
                person_object_id=row["person_object_id"],
                verification_status=row["verification_status"],
                role_source=row["role_source"],
                role_evidence=row["role_evidence"] or {},
            )
        )
    return KnowledgeObjectDetailView(
        object=knowledge_object,
        type_details=dict(metadata) if metadata else knowledge_object.attributes,
        identifiers=[KnowledgeObjectIdentifierView.model_validate(row) for row in identifier_rows],
        contributors=contributors,
        journal_metrics=[PublicationJournalMetricDetail.model_validate(row)
                         for row in load_journal_metric_rows(connection, [object_id])],
        resources=[
            KnowledgeObjectResourceView(
                resource_id=row["fulltext_resource_id"],
                file_name=row["file_name"],
                mime_type=row["mime_type"],
                resource_role=row["resource_role"],
                size_bytes=row["size_bytes"],
                extraction_state=row["extraction_state"],
                license_tags=list(row["license_tags"] or []),
            )
            for row in resource_rows
        ],
    )


_INSTITUTION_ASSOCIATION_CTES = """WITH RECURSIVE parent_edges AS (
    SELECT relation.subject_id AS child_id,relation.object_id AS parent_id
      FROM smartlib.analysis_relation relation
     WHERE relation.predicate IN ('organization.part_of','department.part_of')
       
       AND relation.system_to='infinity'::timestamptz
       AND relation.valid_from <= clock_timestamp()
       AND relation.valid_to > clock_timestamp()
    UNION
    SELECT relation.object_id AS child_id,relation.subject_id AS parent_id
      FROM smartlib.analysis_relation relation
     WHERE relation.predicate='organization.has_department'
       
       AND relation.system_to='infinity'::timestamptz
       AND relation.valid_from <= clock_timestamp()
       AND relation.valid_to > clock_timestamp()
), institution_scope(object_id) AS (
    SELECT %s::uuid
    UNION
    SELECT edge.child_id
      FROM institution_scope scope
      JOIN parent_edges edge ON edge.parent_id=scope.object_id
), scholars(object_id) AS (
    SELECT DISTINCT relation.subject_id
      FROM smartlib.analysis_relation relation
      JOIN smartlib.knowledge_object person ON person.object_id=relation.subject_id
     WHERE relation.object_id IN (SELECT object_id FROM institution_scope)
       AND relation.predicate IN ('person.affiliated_with','person.authoritatively_affiliated_with')
       
       AND relation.system_to='infinity'::timestamptz
       AND relation.valid_from <= clock_timestamp()
       AND relation.valid_to > clock_timestamp()
       AND person.object_type='person'
       AND person.system_to='infinity'::timestamptz
       AND person.review_state NOT IN ('rejected','superseded')
), outputs AS (
    SELECT DISTINCT relation.subject_id AS scholar_id,target.object_id,target.object_type,
           target.canonical_name,
           CASE WHEN target.object_type='publication' THEN metadata.publication_year
                WHEN target.attributes->>'year' ~ '^[0-9]{4}$'
                THEN (target.attributes->>'year')::int END AS year
      FROM scholars
      JOIN smartlib.analysis_relation relation ON relation.subject_id=scholars.object_id
      JOIN smartlib.knowledge_object target ON target.object_id=relation.object_id
      LEFT JOIN smartlib.publication_metadata metadata ON metadata.publication_id=target.object_id
     WHERE relation.predicate IN ('person.authored','person.leads_project','person.participates_in')
       
       AND relation.system_to='infinity'::timestamptz
       AND relation.valid_from <= clock_timestamp()
       AND relation.valid_to > clock_timestamp()
       AND target.object_type IN ('publication','project')
       AND target.system_to='infinity'::timestamptz
       AND target.review_state NOT IN ('rejected','superseded')
)"""


def get_institution_associations(
    connection: DbConnection, object_id: UUID, *, limit: int = 20
) -> InstitutionAssociationSummary:
    count_row = connection.execute(
        _INSTITUTION_ASSOCIATION_CTES + """
        SELECT (SELECT count(*) FROM scholars)::integer AS scholar_count,
               (SELECT count(DISTINCT object_id) FROM outputs)::integer AS output_count""",
        (object_id,),
    ).fetchone() or {"scholar_count": 0, "output_count": 0}
    scholar_rows = connection.execute(
        _INSTITUTION_ASSOCIATION_CTES + """
        SELECT person.object_id,person.canonical_name,
               count(DISTINCT outputs.object_id)::integer AS output_count
          FROM scholars
          JOIN smartlib.knowledge_object person ON person.object_id=scholars.object_id
          LEFT JOIN outputs ON outputs.scholar_id=scholars.object_id
         GROUP BY person.object_id,person.canonical_name
         ORDER BY output_count DESC,person.canonical_name
         LIMIT %s""",
        (object_id, limit),
    ).fetchall()
    output_rows = connection.execute(
        _INSTITUTION_ASSOCIATION_CTES + """
        SELECT object_id,object_type,canonical_name,year,
               count(DISTINCT scholar_id)::integer AS scholar_count
          FROM outputs
         GROUP BY object_id,object_type,canonical_name,year
         ORDER BY year DESC NULLS LAST,canonical_name
         LIMIT %s""",
        (object_id, limit),
    ).fetchall()
    scholar_count = int(count_row["scholar_count"])
    output_count = int(count_row["output_count"])
    return InstitutionAssociationSummary(
        scholar_count=scholar_count,
        output_count=output_count,
        scholars=[InstitutionAssociatedScholarView.model_validate(row) for row in scholar_rows],
        outputs=[InstitutionAssociatedOutputView.model_validate(row) for row in output_rows],
        truncated=scholar_count > len(scholar_rows) or output_count > len(output_rows),
    )


def get_publication_resource_reference(
    connection: DbConnection, publication_id: UUID, resource_id: UUID
) -> PublicationResourceReference | None:
    row = connection.execute(
        """SELECT resource.file_name,resource.mime_type,resource.size_bytes,resource.storage_uri
             FROM smartlib.publication_fulltext_resource resource
             JOIN smartlib.knowledge_object publication
               ON publication.object_id=resource.publication_id
            WHERE resource.publication_id=%s
              AND resource.fulltext_resource_id=%s
              AND publication.object_type='publication'""",
        (publication_id, resource_id),
    ).fetchone()
    return PublicationResourceReference(**row) if row else None


def create_object(
    connection: DbConnection, command: KnowledgeObjectCreate, actor_id: UUID, trace_id: str
) -> KnowledgeObjectView:
    row = connection.execute(
        f"""INSERT INTO smartlib.knowledge_object
                  (object_type, canonical_name, description, visibility, attributes, created_by)
             VALUES (%s, %s, %s, %s, %s, %s)
             RETURNING {_COLUMNS}""",
        (
            command.object_type,
            command.canonical_name,
            command.description,
            command.visibility,
            Jsonb(command.attributes),
            actor_id,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("knowledge object insert returned no row")
    connection.execute(
        """INSERT INTO smartlib.outbox_event
                  (aggregate_type, aggregate_id, event_type, event_version, payload, trace_id)
             VALUES ('knowledge_object', %s, 'knowledge.object.created', 1, %s, %s)""",
        (row["object_id"], Jsonb({"object_id": str(row["object_id"]), "version": row["version"]}), trace_id),
    )
    return KnowledgeObjectView.model_validate(row)
