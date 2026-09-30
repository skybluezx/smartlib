# ruff: noqa: RUF001 -- Chinese user-facing explanatory text.
import json
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
from itertools import combinations
from statistics import mean, median
from typing import Any
from uuid import UUID

from smartlib_platform.foundation.database import DbConnection
from smartlib_platform.publications.analysis_metrics import load_journal_metric_rows

from .community_research import enrich_community_research, load_funding_inputs
from .cooperation import assess_cooperation
from .cooperation_metrics import enrich_assessment, load_metric_inputs
from .disciplines import discipline_workspace
from .institution_granularity import aggregate_institutions, load_institution_hierarchy
from .models import (
    AnalysisCoverage,
    AnalysisScopeOption,
    AnnualProjectMetricPortfolio,
    AppliedAnalysisScope,
    CollaborationEdge,
    CollaborationNetwork,
    CollaborationNode,
    DisciplineAnalysis,
    DisciplineShare,
    EvidencePublication,
    FundingAnalysis,
    FundingCandidateShare,
    FundingShare,
    GraphAnalysisScopeOptions,
    ImpactFactorSummary,
    InCitesJournalAnalysis,
    InCitesPublicationMetric,
    JournalAnalysis,
    JournalShare,
    ProjectJournalMetricAnalysis,
    ProjectMetricCoverage,
    ProjectMetricSummary,
    ProjectPublicationMetric,
    PublicationMetricAggregate,
    QuartileShare,
    ScholarGraphAnalytics,
)
from .outcomes import collaboration_outcomes


def get_graph_analysis_scope_options(connection: DbConnection) -> GraphAnalysisScopeOptions:
    year_row = connection.execute(
        """SELECT min(metadata.publication_year)::integer AS minimum_year,
                  max(metadata.publication_year)::integer AS maximum_year
             FROM smartlib.publication_metadata metadata
             JOIN smartlib.knowledge_object publication
               ON publication.object_id=metadata.publication_id
            WHERE publication.object_type='publication'
              AND publication.system_to='infinity'::timestamptz
              AND smartlib.analysis_state_eligible(publication.review_state)"""
    ).fetchone()
    project_kind_rows = connection.execute(
        """WITH project_publications AS (
                 SELECT relation.subject_id AS project_id,relation.object_id AS publication_id
                   FROM smartlib.analysis_relation relation
                  WHERE relation.predicate='project.has_representative_publication'
                    AND smartlib.analysis_state_eligible(relation.review_state)
                    AND relation.system_to='infinity'::timestamptz
                 UNION
                 SELECT relation.object_id,relation.subject_id
                   FROM smartlib.analysis_relation relation
                  WHERE relation.predicate='publication.supported_by_project'
                    AND smartlib.analysis_state_eligible(relation.review_state)
                    AND relation.system_to='infinity'::timestamptz
             ), project_kinds AS (
                 SELECT project.object_id AS project_id,
                        kind.object_id AS kind_id,kind.canonical_name AS kind_name
                   FROM smartlib.knowledge_object project
                   JOIN smartlib.knowledge_object kind
                     ON kind.object_type='funding_program'
                    AND kind.system_to='infinity'::timestamptz
                    AND smartlib.analysis_state_eligible(kind.review_state)
                    AND kind.attributes->>'record_kind'='funding_category'
                    AND (
                        project.attributes->>'funding_program_id'=kind.object_id::text
                        OR EXISTS (
                            SELECT 1 FROM smartlib.analysis_relation relation
                             WHERE relation.subject_id=project.object_id
                               AND relation.object_id=kind.object_id
                               AND relation.predicate='project.under_program'
                               AND smartlib.analysis_state_eligible(relation.review_state)
                               AND relation.system_to='infinity'::timestamptz
                        )
                    )
                  WHERE project.object_type='project'
                    AND project.system_to='infinity'::timestamptz
                    AND smartlib.analysis_state_eligible(project.review_state)
             )
             SELECT project_kinds.kind_id AS object_id,project_kinds.kind_name AS name,
                    count(DISTINCT project_publications.publication_id)::integer
                      AS publication_count
               FROM project_kinds
               JOIN project_publications USING (project_id)
              GROUP BY project_kinds.kind_id,project_kinds.kind_name
              ORDER BY publication_count DESC,project_kinds.kind_name"""
    ).fetchall()
    organization_rows = connection.execute(
        """WITH RECURSIVE organizations AS (
                 SELECT object_id,canonical_name
                   FROM smartlib.knowledge_object
                  WHERE object_type IN ('organization','department')
                    AND system_to='infinity'::timestamptz
                    AND smartlib.analysis_state_eligible(review_state)
             ), organization_tree(root_id,object_id) AS (
                 SELECT object_id,object_id FROM organizations
                 UNION
                 SELECT tree.root_id,
                        CASE WHEN relation.predicate='organization.has_department'
                             THEN relation.object_id ELSE relation.subject_id END
                   FROM organization_tree tree
                   JOIN smartlib.analysis_relation relation
                     ON tree.object_id=CASE
                          WHEN relation.predicate='organization.has_department'
                          THEN relation.subject_id ELSE relation.object_id END
                  WHERE relation.predicate IN ('organization.part_of','department.part_of',
                                               'organization.has_department')
                    AND smartlib.analysis_state_eligible(relation.review_state)
                    AND relation.system_to='infinity'::timestamptz
             ), publication_organizations AS (
                 SELECT affiliation.object_id AS organization_id,authorship.object_id AS publication_id
                   FROM smartlib.analysis_relation affiliation
                   JOIN smartlib.analysis_relation authorship
                     ON authorship.subject_id=affiliation.subject_id
                    AND authorship.predicate='person.authored'
                    AND smartlib.analysis_state_eligible(authorship.review_state)
                    AND authorship.system_to='infinity'::timestamptz
                  WHERE affiliation.predicate='person.authoritatively_affiliated_with'
                    AND smartlib.analysis_state_eligible(affiliation.review_state)
                    AND affiliation.system_to='infinity'::timestamptz
                 UNION
                 SELECT affiliation.object_id,
                        (affiliation.attributes->>'publication_id')::uuid
                   FROM smartlib.analysis_relation affiliation
                  WHERE affiliation.predicate='person.affiliated_with'
                    AND smartlib.analysis_state_eligible(affiliation.review_state)
                    AND affiliation.system_to='infinity'::timestamptz
                    AND affiliation.attributes->>'publication_id'
                        ~ '^[0-9a-fA-F-]{36}$'
             )
             SELECT organization.object_id,organization.canonical_name AS name,
                    count(DISTINCT link.publication_id)::integer AS publication_count
               FROM organizations organization
               LEFT JOIN organization_tree tree ON tree.root_id=organization.object_id
               LEFT JOIN publication_organizations link
                 ON link.organization_id=tree.object_id
              GROUP BY organization.object_id,organization.canonical_name
             HAVING count(DISTINCT link.publication_id) > 0
              ORDER BY publication_count DESC,organization.canonical_name"""
    ).fetchall()
    scholar_rows = connection.execute(
        """SELECT person.object_id,person.canonical_name AS name,
                  count(DISTINCT relation.object_id)::integer AS publication_count
             FROM smartlib.analysis_relation relation
             JOIN smartlib.knowledge_object person ON person.object_id=relation.subject_id
             JOIN smartlib.knowledge_object publication ON publication.object_id=relation.object_id
            WHERE relation.predicate='person.authored'
              AND smartlib.analysis_state_eligible(relation.review_state)
              AND relation.system_to='infinity'::timestamptz
              AND person.object_type='person'
              AND person.system_to='infinity'::timestamptz
              AND smartlib.analysis_state_eligible(person.review_state)
              AND publication.object_type='publication'
              AND publication.system_to='infinity'::timestamptz
              AND smartlib.analysis_state_eligible(publication.review_state)
            GROUP BY person.object_id,person.canonical_name
            ORDER BY publication_count DESC,person.canonical_name"""
    ).fetchall()
    return GraphAnalysisScopeOptions(
        minimum_year=year_row["minimum_year"] if year_row else None,
        maximum_year=year_row["maximum_year"] if year_row else None,
        project_kinds=[AnalysisScopeOption.model_validate(row) for row in project_kind_rows],
        organizations=[AnalysisScopeOption.model_validate(row) for row in organization_rows],
        scholars=[AnalysisScopeOption.model_validate(row) for row in scholar_rows],
    )


def _scoped_publication_ids(
    connection: DbConnection,
    *,
    start_year: int | None,
    end_year: int | None,
    project_kind_ids: list[UUID],
    organization_ids: list[UUID],
    scholar_ids: list[UUID],
    custom_publication_ids: list[UUID] | None = None,
) -> list[UUID]:
    clauses = [
        "publication.object_type='publication'",
        "publication.system_to='infinity'::timestamptz",
        "smartlib.analysis_state_eligible(publication.review_state)",
    ]
    params: list[object] = []
    if custom_publication_ids is not None:
        clauses.append("publication.object_id=ANY(%s::uuid[])")
        params.append(custom_publication_ids)
    year_expression = (
        "COALESCE(metadata.publication_year,CASE WHEN publication.attributes->>'year' "
        "~ '^[0-9]{4}$' THEN (publication.attributes->>'year')::integer END)"
    )
    if start_year is not None:
        clauses.append(f"{year_expression} >= %s")
        params.append(start_year)
    if end_year is not None:
        clauses.append(f"{year_expression} <= %s")
        params.append(end_year)
    if project_kind_ids:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM smartlib.knowledge_object project
                 WHERE project.object_type='project'
                   AND project.system_to='infinity'::timestamptz
                   AND smartlib.analysis_state_eligible(project.review_state)
                   AND (
                       project.attributes->>'funding_program_id'=ANY(%s::text[])
                       OR EXISTS (
                           SELECT 1 FROM smartlib.analysis_relation kind_relation
                            WHERE kind_relation.subject_id=project.object_id
                              AND kind_relation.object_id=ANY(%s::uuid[])
                              AND kind_relation.predicate='project.under_program'
                              AND smartlib.analysis_state_eligible(kind_relation.review_state)
                              AND kind_relation.system_to='infinity'::timestamptz
                       )
                   )
                   AND (
                       EXISTS (
                           SELECT 1 FROM smartlib.analysis_relation project_publication
                            WHERE project_publication.subject_id=project.object_id
                              AND project_publication.object_id=publication.object_id
                              AND project_publication.predicate='project.has_representative_publication'
                              AND smartlib.analysis_state_eligible(project_publication.review_state)
                              AND project_publication.system_to='infinity'::timestamptz
                       ) OR EXISTS (
                           SELECT 1 FROM smartlib.analysis_relation publication_project
                            WHERE publication_project.subject_id=publication.object_id
                              AND publication_project.object_id=project.object_id
                              AND publication_project.predicate='publication.supported_by_project'
                              AND smartlib.analysis_state_eligible(publication_project.review_state)
                              AND publication_project.system_to='infinity'::timestamptz
                       )
                   )
            )"""
        )
        params.extend([[str(value) for value in project_kind_ids], project_kind_ids])
    organization_cte = ""
    if organization_ids:
        organization_cte = """WITH RECURSIVE organization_scope(object_id) AS (
            SELECT unnest(%s::uuid[])
            UNION
            SELECT CASE WHEN relation.predicate='organization.has_department'
                        THEN relation.object_id ELSE relation.subject_id END
              FROM organization_scope scope
              JOIN smartlib.analysis_relation relation
                ON scope.object_id=CASE WHEN relation.predicate='organization.has_department'
                                        THEN relation.subject_id ELSE relation.object_id END
             WHERE relation.predicate IN ('organization.part_of','department.part_of',
                                          'organization.has_department')
               AND smartlib.analysis_state_eligible(relation.review_state)
               AND relation.system_to='infinity'::timestamptz
        ) """
        params.insert(0, organization_ids)
        clauses.append(
            """(
                EXISTS (
                    SELECT 1 FROM smartlib.analysis_relation authorship
                    JOIN smartlib.analysis_relation affiliation
                      ON affiliation.subject_id=authorship.subject_id
                     AND affiliation.object_id IN (SELECT object_id FROM organization_scope)
                     AND affiliation.predicate='person.authoritatively_affiliated_with'
                     AND smartlib.analysis_state_eligible(affiliation.review_state)
                     AND affiliation.system_to='infinity'::timestamptz
                   WHERE authorship.object_id=publication.object_id
                     AND authorship.predicate='person.authored'
                     AND smartlib.analysis_state_eligible(authorship.review_state)
                     AND authorship.system_to='infinity'::timestamptz
                ) OR EXISTS (
                    SELECT 1 FROM smartlib.analysis_relation affiliation
                     WHERE affiliation.object_id IN (SELECT object_id FROM organization_scope)
                       AND affiliation.predicate='person.affiliated_with'
                       AND smartlib.analysis_state_eligible(affiliation.review_state)
                       AND affiliation.system_to='infinity'::timestamptz
                       AND affiliation.attributes->>'publication_id'=publication.object_id::text
                )
            )"""
        )
    if scholar_ids:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM smartlib.analysis_relation authorship
                 WHERE authorship.subject_id=ANY(%s::uuid[])
                   AND authorship.object_id=publication.object_id
                   AND authorship.predicate='person.authored'
                   AND smartlib.analysis_state_eligible(authorship.review_state)
                   AND authorship.system_to='infinity'::timestamptz
            )"""
        )
        params.append(scholar_ids)
    rows = connection.execute(
        f"""{organization_cte}
            SELECT publication.object_id
              FROM smartlib.knowledge_object publication
              LEFT JOIN smartlib.publication_metadata metadata
                ON metadata.publication_id=publication.object_id
             WHERE {' AND '.join(clauses)}
             ORDER BY publication.object_id""",
        tuple(params),
    ).fetchall()
    return [row["object_id"] for row in rows]


def get_scholar_graph_analytics(
    connection: DbConnection,
    *,
    graph_backend: str,
    minimum_publication_count: int = 2,
    edge_limit: int = 120,
    people_focus_id: UUID | None = None,
    people_organization_id: UUID | None = None,
    people_include_external: bool = False,
    start_year: int | None = None,
    end_year: int | None = None,
    project_kind_ids: list[UUID] | None = None,
    organization_ids: list[UUID] | None = None,
    scholar_ids: list[UUID] | None = None,
    custom_publication_ids: list[UUID] | None = None,
    custom_scope_id: UUID | None = None,
    custom_scope_name: str | None = None,
    institution_settings: str | None = None,
    selected_module: str | None = None,
) -> ScholarGraphAnalytics:
    project_kind_ids = project_kind_ids or []
    organization_ids = organization_ids or []
    scholar_ids = scholar_ids or []
    publication_ids = _scoped_publication_ids(
        connection,
        start_year=start_year,
        end_year=end_year,
        project_kind_ids=project_kind_ids,
        organization_ids=organization_ids,
        scholar_ids=scholar_ids,
        custom_publication_ids=custom_publication_ids,
    )
    author_rows = connection.execute(
        """SELECT relation.subject_id AS person_id, person.canonical_name AS person_name,
                         relation.object_id AS publication_id, publication.canonical_name AS publication_title,
                         relation.relation_id AS author_relation_id,
                         relation.system_from AS author_relation_version
                    FROM smartlib.analysis_relation relation
                    JOIN smartlib.knowledge_object person ON person.object_id = relation.subject_id
                    JOIN smartlib.knowledge_object publication ON publication.object_id = relation.object_id
                   WHERE relation.predicate = 'person.authored'
                     AND smartlib.analysis_state_eligible(relation.review_state)
                     AND relation.system_to='infinity'::timestamptz
                     AND person.object_type = 'person' AND publication.object_type = 'publication'
                     AND smartlib.analysis_state_eligible(person.review_state)
                     AND smartlib.analysis_state_eligible(publication.review_state)
                     AND person.system_to='infinity'::timestamptz
                     AND publication.system_to='infinity'::timestamptz
                     AND relation.object_id=ANY(%s::uuid[])
                   ORDER BY relation.object_id, relation.subject_id""",
        (publication_ids,),
    ).fetchall()
    affiliation_rows = connection.execute(
        """SELECT relation.subject_id AS person_id, relation.relation_id, relation.review_state,
                         relation.system_from AS relation_version,
                         coalesce(relation.context_object_id,
                         CASE WHEN relation.attributes->>'publication_id'
                           ~ '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$'
                         THEN (relation.attributes->>'publication_id')::uuid END) AS publication_id,
                         organization.object_id AS organization_id,
                         organization.canonical_name AS organization_name,
                         relation.attributes->>'raw_affiliation' AS raw_affiliation,
                         publication.canonical_name AS publication_title
                    FROM smartlib.analysis_relation relation
                    JOIN smartlib.knowledge_object organization ON organization.object_id = relation.object_id
                    JOIN smartlib.knowledge_object publication
                      ON publication.object_id=coalesce(relation.context_object_id,
                         CASE WHEN relation.attributes->>'publication_id'
                           ~ '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$'
                         THEN (relation.attributes->>'publication_id')::uuid END)
                   WHERE relation.predicate = 'person.affiliated_with'
                     AND smartlib.analysis_state_eligible(relation.review_state)
                     AND relation.system_to='infinity'::timestamptz
                     AND smartlib.analysis_state_eligible(organization.review_state)
                     AND smartlib.analysis_state_eligible(publication.review_state)
                     AND organization.system_to='infinity'::timestamptz
                     AND publication.system_to='infinity'::timestamptz
                     AND EXISTS (
                         SELECT 1 FROM smartlib.analysis_relation authored
                         JOIN smartlib.knowledge_object person ON person.object_id=authored.subject_id
                         WHERE authored.subject_id=relation.subject_id
                           AND authored.object_id=publication.object_id
                           AND authored.predicate='person.authored'
                           AND authored.system_to='infinity'::timestamptz
                           AND person.system_to='infinity'::timestamptz
                           AND smartlib.analysis_state_eligible(authored.review_state)
                           AND smartlib.analysis_state_eligible(person.review_state)
                     )
                     AND coalesce(relation.context_object_id,
                         CASE WHEN relation.attributes->>'publication_id'
                           ~ '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$'
                         THEN (relation.attributes->>'publication_id')::uuid END)=ANY(%s::uuid[])
                   ORDER BY publication_id, organization.canonical_name""",
        (publication_ids,),
    ).fetchall()
    funding_rows = []  # Funding is counted through specific projects below.
    funding_candidate_rows = connection.execute(
        """SELECT kind.object_id,kind.canonical_name,
                         kind.attributes->>'funding_source_category_label' AS category_label,
                         array_agg(DISTINCT relation.subject_id) AS publication_ids,
                         jsonb_agg(DISTINCT jsonb_build_object(
                           'object_id',project.object_id::text,'name',project.canonical_name,
                           'kind_name',kind.canonical_name,
                           'grant_number',nullif(project.attributes->>'grant_number','')
                         )) AS projects,
                         count(*)::integer AS relation_count,
                         count(DISTINCT relation.subject_id)::integer AS linked_item_count,
                         count(*) FILTER (WHERE relation.review_state='pending')::integer
                           AS pending_relation_count,
                         count(*) FILTER (WHERE relation.review_state='approved')::integer
                           AS approved_relation_count,
                         coalesce(avg(relation.confidence),0)::double precision
                           AS average_confidence
                    FROM smartlib.analysis_relation relation
                    JOIN smartlib.knowledge_object project ON project.object_id=relation.object_id
                    JOIN smartlib.knowledge_object kind
                      ON kind.object_id=(project.attributes->>'funding_program_id')::uuid
                   WHERE relation.predicate='publication.supported_by_project'
                     AND smartlib.analysis_state_eligible(relation.review_state)
                     AND relation.system_to='infinity'::timestamptz
                     AND project.object_type='project'
                     AND project.system_to='infinity'::timestamptz
                     AND smartlib.analysis_state_eligible(project.review_state)
                     AND kind.object_type='funding_program'
                     AND kind.system_to='infinity'::timestamptz
                     AND smartlib.analysis_state_eligible(kind.review_state)
                     AND relation.subject_id=ANY(%s::uuid[])
                   GROUP BY kind.object_id,kind.canonical_name,kind.attributes->>'funding_source_category_label'
                   ORDER BY relation_count DESC,kind.canonical_name""",
        (publication_ids,),
    ).fetchall()
    funding_pending = connection.execute(
        """SELECT count(*)::integer AS relation_count,
                         count(DISTINCT relation.object_id)::integer AS candidate_count,
                         count(*) FILTER (
                           WHERE nullif(program.attributes ->> 'grant_number','') IS NULL
                         )::integer AS program_relation_count,
                         count(*) FILTER (
                           WHERE nullif(program.attributes ->> 'grant_number','') IS NOT NULL
                         )::integer AS grant_relation_count,
                         count(DISTINCT relation.object_id) FILTER (
                           WHERE nullif(program.attributes ->> 'grant_number','') IS NULL
                         )::integer AS program_candidate_count,
                         count(DISTINCT relation.object_id) FILTER (
                           WHERE nullif(program.attributes ->> 'grant_number','') IS NOT NULL
                         )::integer AS grant_candidate_count
                    FROM smartlib.analysis_relation relation
                    JOIN smartlib.knowledge_object program ON program.object_id = relation.object_id
                   WHERE relation.predicate='publication.supported_by_project'
                     AND relation.review_state = 'pending'
                     AND relation.system_to='infinity'::timestamptz
                     AND program.object_type='project'
                     AND program.system_to='infinity'::timestamptz
                     AND relation.subject_id=ANY(%s::uuid[])""",
        (publication_ids,),
    ).fetchone()
    funding_validated = connection.execute(
        """SELECT count(DISTINCT project.object_id)::integer AS project_count,
                         count(DISTINCT relation.relation_id)::integer AS relation_count,
                         count(DISTINCT relation.subject_id)::integer AS publication_count
                    FROM smartlib.knowledge_object project
                    LEFT JOIN smartlib.analysis_relation relation
                     ON relation.object_id=project.object_id
                     AND relation.predicate='publication.supported_by_project'
                     AND relation.review_state='approved'
                     AND relation.system_to='infinity'::timestamptz
                     AND relation.subject_id=ANY(%s::uuid[])
                   WHERE project.object_type='project'
                     AND project.attributes->>'record_kind'='individual_grant_validated'
                     AND project.system_to='infinity'::timestamptz
                     AND coalesce((project.attributes->>'analysis_enabled')::boolean,false)
                     AND relation.relation_id IS NOT NULL""",
        (publication_ids,),
    ).fetchone()
    discipline_rows = connection.execute(
        """SELECT relation.object_id, relation.relation_id, discipline.canonical_name,
                         relation.subject_id AS publication_id, relation.review_state,
                         publication.canonical_name AS publication_title, metadata.publication_year,
                         coalesce(relation.attributes->>'scheme_version',discipline.attributes->>'scheme_version')
                           AS scheme_version,
                         relation.attributes->>'source_kind' AS source_kind,
                         relation.attributes->>'rationale' AS rationale,
                         relation.attributes->>'evidence_excerpt' AS evidence_excerpt,
                         relation.attributes ->> 'scheme' AS scheme,
                         relation.attributes ->> 'classification_role' AS classification_role,
                         coalesce(relation.attributes ->> 'code',
                                  relation.attributes ->> 'discipline_code') AS discipline_code,
                         CASE WHEN relation.attributes ->> 'discipline_level' ~ '^[0-9]+$'
                              THEN (relation.attributes ->> 'discipline_level')::integer
                         ELSE CASE WHEN discipline.attributes->>'level' ~ '^[0-9]+$'
                                   THEN (discipline.attributes->>'level')::integer END
                         END AS discipline_level
                    FROM smartlib.analysis_relation relation
                    JOIN smartlib.knowledge_object discipline ON discipline.object_id = relation.object_id
                    JOIN smartlib.knowledge_object publication ON publication.object_id=relation.subject_id
                    LEFT JOIN smartlib.publication_metadata metadata
                      ON metadata.publication_id=relation.subject_id
                   WHERE relation.predicate = 'publication.classified_as_discipline'
                     AND smartlib.analysis_state_eligible(relation.review_state)
                     AND smartlib.analysis_state_eligible(discipline.review_state)
                     AND relation.system_to='infinity'::timestamptz
                     AND discipline.system_to='infinity'::timestamptz
                     AND relation.subject_id=ANY(%s::uuid[])
                   ORDER BY scheme, discipline.canonical_name""",
        (publication_ids,),
    ).fetchall()
    discipline_catalog = connection.execute(
        """SELECT attributes->>'scheme' AS scheme, attributes->>'scheme_version' AS scheme_version,
                  count(DISTINCT object_id)::integer AS concept_count
             FROM smartlib.knowledge_object
            WHERE object_type='discipline' AND system_to='infinity'::timestamptz
              AND smartlib.analysis_state_eligible(review_state)
            GROUP BY 1,2"""
    ).fetchall()
    journal_rows = connection.execute(
        """SELECT journal.object_id,journal.canonical_name,
                         count(DISTINCT relation.subject_id)::integer AS publication_count
                    FROM smartlib.analysis_relation relation
                    JOIN smartlib.knowledge_object journal ON journal.object_id=relation.object_id
                   WHERE relation.predicate='publication.published_in'
                     AND smartlib.analysis_state_eligible(relation.review_state)
                     AND smartlib.analysis_state_eligible(journal.review_state)
                     AND journal.object_type='journal'
                     AND relation.system_to='infinity'::timestamptz
                     AND journal.system_to='infinity'::timestamptz
                     AND relation.subject_id=ANY(%s::uuid[])
                   GROUP BY journal.object_id,journal.canonical_name
                   ORDER BY publication_count DESC,journal.canonical_name""",
        (publication_ids,),
    ).fetchall()
    journal_metric_rows = load_journal_metric_rows(connection, publication_ids)
    project_publication_rows = connection.execute(
        """WITH project_publications AS (
                 SELECT relation.subject_id AS project_id,
                        relation.object_id AS publication_id,
                        relation.attributes AS relation_attributes
                   FROM smartlib.analysis_relation relation
                  WHERE relation.predicate='project.has_representative_publication'
                    AND smartlib.analysis_state_eligible(relation.review_state)
                    AND relation.system_to='infinity'::timestamptz
                 UNION
                 SELECT relation.object_id,relation.subject_id,relation.attributes
                   FROM smartlib.analysis_relation relation
                  WHERE relation.predicate='publication.supported_by_project'
                    AND smartlib.analysis_state_eligible(relation.review_state)
                    AND relation.system_to='infinity'::timestamptz
             )
             SELECT project.object_id AS project_id,project.canonical_name AS project_name,
                         CASE WHEN project.attributes->>'year' ~ '^[0-9]{4}$'
                              THEN (project.attributes->>'year')::integer
                              WHEN link.relation_attributes->>'year' ~ '^[0-9]{4}$'
                              THEN (link.relation_attributes->>'year')::integer END AS funding_year,
                         publication.object_id AS publication_id,
                         publication.canonical_name AS publication_title,
                         metadata.publication_year,journal.object_id AS journal_id,
                         journal.canonical_name AS journal_name
                    FROM project_publications link
                    JOIN smartlib.knowledge_object project ON project.object_id=link.project_id
                    JOIN smartlib.knowledge_object publication
                      ON publication.object_id=link.publication_id
                    LEFT JOIN smartlib.publication_metadata metadata
                      ON metadata.publication_id=publication.object_id
                    LEFT JOIN smartlib.analysis_relation published_in
                      ON published_in.subject_id=publication.object_id
                     AND published_in.predicate='publication.published_in'
                     AND smartlib.analysis_state_eligible(published_in.review_state)
                     AND published_in.system_to='infinity'::timestamptz
                    LEFT JOIN smartlib.knowledge_object journal
                      ON journal.object_id=published_in.object_id
                     AND journal.system_to='infinity'::timestamptz
                     AND smartlib.analysis_state_eligible(journal.review_state)
                   WHERE project.object_type='project' AND publication.object_type='publication'
                     AND smartlib.analysis_state_eligible(project.review_state)
                     AND smartlib.analysis_state_eligible(publication.review_state)
                     AND project.system_to='infinity'::timestamptz
                     AND publication.system_to='infinity'::timestamptz
                     AND link.publication_id=ANY(%s::uuid[])
                     AND (
                       %s::boolean
                       OR project.attributes->>'funding_program_id'=ANY(%s::text[])
                       OR EXISTS (
                         SELECT 1 FROM smartlib.analysis_relation kind_relation
                          WHERE kind_relation.subject_id=project.object_id
                            AND kind_relation.object_id=ANY(%s::uuid[])
                            AND kind_relation.predicate='project.under_program'
                            AND smartlib.analysis_state_eligible(kind_relation.review_state)
                            AND kind_relation.system_to='infinity'::timestamptz
                       )
                     )
                   ORDER BY project.canonical_name,metadata.publication_year DESC,
                            publication.canonical_name""",
        (
            publication_ids,
            not project_kind_ids,
            [str(value) for value in project_kind_ids],
            project_kind_ids,
        ),
    ).fetchall()

    people = None
    institutions = None
    if selected_module in (None, 'people_collaboration', 'institution_collaboration'):
        metric_context, metric_inputs = load_metric_inputs(connection, publication_ids, journal_metric_rows)
    if selected_module in (None, 'people_collaboration'):
        people = _people_network(
            author_rows, minimum_publication_count, edge_limit, affiliation_rows,
            str(people_focus_id) if people_focus_id else None,
            str(people_organization_id) if people_organization_id else None,
            people_include_external, scope_ids=[str(pid) for pid in publication_ids],
        )
        if people.assessment is not None:
            enrich_assessment(people.assessment, metric_context, metric_inputs)
            enrich_community_research(people.assessment, load_funding_inputs(connection, publication_ids), discipline_rows)
    if selected_module in (None, 'institution_collaboration'):
        institution_rows, institution_options, aggregation_context = aggregate_institutions(
            affiliation_rows,
            load_institution_hierarchy(connection), institution_settings)
        institutions = _institution_network(institution_rows, minimum_publication_count, edge_limit,
                                            scope_ids=[str(pid) for pid in publication_ids],
                                            aggregation_context=aggregation_context)
        institutions.institution_options = institution_options
        institutions.aggregation_context = aggregation_context
        if institutions.assessment is not None:
            enrich_assessment(institutions.assessment, metric_context, metric_inputs)
            enrich_community_research(institutions.assessment, load_funding_inputs(connection, publication_ids), discipline_rows)
    verified_project_links = sum(int(row["linked_project_count"]) for row in funding_rows)
    verified_programs = [
        FundingShare(
            object_id=str(row["object_id"]),
            name=str(row["canonical_name"]),
            funding_agency=row["funding_agency"],
            linked_project_count=int(row["linked_project_count"]),
            share=(
                int(row["linked_project_count"]) / verified_project_links
                if verified_project_links
                else 0
            ),
        )
        for row in funding_rows
    ]
    validated_project_count = int(
        funding_validated["project_count"] if funding_validated else 0
    )
    validated_relation_count = int(
        funding_validated["relation_count"] if funding_validated else 0
    )
    validated_publication_count = int(
        funding_validated["publication_count"] if funding_validated else 0
    )
    validated_project_note = (
        f"另有 {validated_project_count} 个经 InCites 与论文PDF全文双重核验的项目对象，"
        f"通过 {validated_relation_count} 条关系关联 {validated_publication_count} 篇论文，"
        "已进入搜索、关系查询和图谱；"
        if validated_project_count
        else "当前没有已核准的全文项目对象；"
    )
    verified_funding_note = (
        "当前基金分布以 InCites 导出的论文—资助机构关系为有效统计口径。"
        if verified_project_links
        else "当前没有已核准的论文—资助机构历史关系；"
    )
    generated_at = datetime.now().astimezone()
    journal_analysis, project_analysis = _journal_analyses(
        journal_rows,
        journal_metric_rows,
        project_publication_rows,
        scoped_publication_ids={str(value) for value in publication_ids},
    )
    journal_analysis = journal_analysis.model_copy(
        update={"incites": _incites_journal_analysis(connection, publication_ids)}
    )
    version_rows = [publication_ids, author_rows, affiliation_rows, discipline_rows,
                    journal_rows, journal_metric_rows, project_publication_rows]
    canonical_rows = [sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)
                      for rows in version_rows]
    data_version = sha256(json.dumps([canonical_rows, journal_analysis.incites.model_dump(mode="json")
                                    if journal_analysis.incites else None],
                                   sort_keys=True, default=str).encode()).hexdigest()
    return ScholarGraphAnalytics(
        data_version=data_version,
        scope=AppliedAnalysisScope(
            start_year=start_year,
            end_year=end_year,
            project_kind_ids=project_kind_ids,
            organization_ids=organization_ids,
            scholar_ids=scholar_ids,
            custom_scope_id=custom_scope_id,
            custom_scope_name=custom_scope_name,
            publication_count=len(publication_ids),
        ),
        coverage=AnalysisCoverage(
            publications=len(publication_ids),
            publications_with_authors=len({row["publication_id"] for row in author_rows}),
            publications_with_affiliations=len(
                {row["publication_id"] for row in affiliation_rows}
            ),
            publications_with_disciplines=len(
                {row["publication_id"] for row in discipline_rows}
            ),
            graph_backend=graph_backend,
            generated_at=generated_at,
        ),
        funding=FundingAnalysis(
            category_shares=_funding_category_shares(funding_candidate_rows, len(publication_ids)),
            verified_programs=verified_programs,
            verified_project_links=verified_project_links,
            candidate_programs=_funding_candidate_shares(funding_candidate_rows),
            pending_program_relation_count=int(
                funding_pending["program_relation_count"] if funding_pending else 0
            ),
            pending_grant_relation_count=int(
                funding_pending["grant_relation_count"] if funding_pending else 0
            ),
            pending_program_candidate_count=int(
                funding_pending["program_candidate_count"] if funding_pending else 0
            ),
            pending_grant_candidate_count=int(
                funding_pending["grant_candidate_count"] if funding_pending else 0
            ),
            pending_project_kind_count=sum(
                1 for row in funding_candidate_rows if int(row["pending_relation_count"]) > 0
            ),
            included_project_kind_count=len(funding_candidate_rows),
            pending_relation_count=int(funding_pending["relation_count"] if funding_pending else 0),
            pending_candidate_count=int(funding_pending["candidate_count"] if funding_pending else 0),
            scope_note=(
                f"{verified_funding_note}"
                f"{validated_project_note}"
                "全文提取的待核与已核项目关系均按统一准入规则纳入分析；"
                "核验完成后统计会随关系状态和规范化结果更新。"
            ),
        ) if selected_module in (None, 'funding') else None,
        people_collaboration=people,
        institution_collaboration=institutions,
        disciplines=_discipline_analysis(discipline_rows).model_copy(update={
            "workspace": discipline_workspace(discipline_rows, discipline_catalog, publication_ids,
                                               author_rows, affiliation_rows),
        }) if selected_module in (None, 'disciplines') else None,
        journals=journal_analysis if selected_module in (None, 'journals') else None,
        project_journal_metrics=project_analysis if selected_module == 'project_journal_metrics' else None,
        collaboration_outcomes=collaboration_outcomes(
            connection, publication_ids, author_rows, affiliation_rows, journal_metric_rows,
        ) if selected_module in (None, 'collaboration_outcomes') else None,
    )


def _journal_analyses(
    journal_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    project_rows: list[dict[str, Any]],
    *,
    scoped_publication_ids: set[str] | None = None,
) -> tuple[JournalAnalysis, ProjectJournalMetricAnalysis]:
    metrics: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in metric_rows:
        metrics[str(row["publication_id"])][str(row["metric_system"])].append(row)

    linked_publications = sum(int(row["publication_count"]) for row in journal_rows)
    journal_denominator = (
        len(scoped_publication_ids) if scoped_publication_ids is not None else linked_publications
    )
    top_journals = [
        JournalShare(
            object_id=str(row["object_id"]),
            name=str(row["canonical_name"]),
            publication_count=int(row["publication_count"]),
            share=int(row["publication_count"]) / journal_denominator if journal_denominator else 0,
        )
        for row in journal_rows
    ]
    all_publication_ids = (
        scoped_publication_ids
        if scoped_publication_ids is not None
        else {str(row["publication_id"]) for row in project_rows}
    )
    jcr_ids = {value for value in all_publication_ids if metrics[value].get("jcr")}
    cas_ids = {value for value in all_publication_ids if metrics[value].get("cas_partition")}
    journal_analysis = JournalAnalysis(
        linked_publications=linked_publications,
        journal_count=len(journal_rows),
        top_journals=top_journals,
        jcr_matched_publications=len(jcr_ids),
        cas_matched_publications=len(cas_ids),
        impact_factor=_impact_summary(jcr_ids, metrics),
        jcr_quartiles=_quartile_distribution(jcr_ids, metrics, "jcr"),
        cas_partitions=_quartile_distribution(cas_ids, metrics, "cas_partition"),
        scope_note=(
            "期刊关系包含符合统一准入规则的待核与已核记录。影响因子、JCR分区和中科院分区只采用与论文发表年"
            "完全一致且已经发布的指标版本；没有同年数据时保持缺失，不用最新年份替代。"
        ),
    )

    grouped: dict[str, dict[str, Any]] = {}
    for row in project_rows:
        project_id = str(row["project_id"])
        group = grouped.setdefault(
            project_id,
            {
                "name": str(row["project_name"]),
                "funding_year": row["funding_year"],
                "publications": {},
            },
        )
        group["publications"][str(row["publication_id"])] = row
    project_summaries: list[ProjectMetricSummary] = []
    for project_id, group in grouped.items():
        rows = list(group["publications"].values())
        publication_ids = {str(row["publication_id"]) for row in rows}
        project_jcr_ids = {value for value in publication_ids if metrics[value].get("jcr")}
        project_cas_ids = {
            value for value in publication_ids if metrics[value].get("cas_partition")
        }
        publications = []
        for row in rows:
            publication_id = str(row["publication_id"])
            jcr = metrics[publication_id].get("jcr", [])
            cas = metrics[publication_id].get("cas_partition", [])
            impact_values = sorted(
                {float(value["impact_factor"]) for value in jcr if value["impact_factor"] is not None}
            )
            publications.append(
                ProjectPublicationMetric(
                    publication_id=publication_id,
                    title=str(row["publication_title"]),
                    publication_year=row["publication_year"],
                    journal_id=str(row["journal_id"]) if row["journal_id"] else None,
                    journal_name=row["journal_name"],
                    impact_factor=impact_values[0] if len(impact_values) == 1 else None,
                    jcr_quartiles=sorted({str(value["quartile"]) for value in jcr if value["quartile"]}),
                    cas_partitions=sorted({str(value["quartile"]) for value in cas if value["quartile"]}),
                    jcr_metric_year=int(jcr[0]["metric_year"]) if jcr else None,
                    cas_metric_year=int(cas[0]["metric_year"]) if cas else None,
                )
            )
        project_summaries.append(
            ProjectMetricSummary(
                project_id=project_id,
                project_name=group["name"],
                funding_year=group["funding_year"],
                publication_count=len(rows),
                publications_with_journal=sum(1 for row in rows if row["journal_id"]),
                jcr_matched_publications=len(project_jcr_ids),
                cas_matched_publications=len(project_cas_ids),
                impact_factor=_impact_summary(project_jcr_ids, metrics),
                jcr_quartiles=_quartile_distribution(project_jcr_ids, metrics, "jcr"),
                cas_partitions=_quartile_distribution(project_cas_ids, metrics, "cas_partition"),
                publications=publications,
            )
        )
    project_summaries.sort(key=lambda item: (-item.publication_count, item.project_name))
    annual_portfolios = _annual_project_portfolios(project_summaries, metrics)
    return journal_analysis, ProjectJournalMetricAnalysis(
        projects=project_summaries,
        annual_portfolios=annual_portfolios,
        scope_note=(
            "每个项目内按论文对象去重；同一论文可以归属于不同项目。中位影响因子作为主摘要，"
            "均值与范围作为补充。多学科期刊保留全部分区，每篇论文在各分区间等权分摊，"
            "不暗中选取最高分区。指标覆盖不足时不输出替代分值。"
        ),
    )


def _incites_journal_analysis(
    connection: DbConnection,
    publication_ids: list[UUID],
) -> InCitesJournalAnalysis | None:
    if not publication_ids:
        return None
    release = connection.execute(
        """SELECT release_id,exported_on,indexed_through,dataset_updated_on
             FROM smartlib.publication_metric_latest_release release
            WHERE provider='incites'
              AND EXISTS (
                  SELECT 1 FROM smartlib.publication_metric_snapshot snapshot
                   WHERE snapshot.release_id=release.release_id
                     AND snapshot.publication_id=ANY(%s::uuid[])
              )
            ORDER BY indexed_through DESC,exported_on DESC,created_at DESC,release_id
            LIMIT 1""",
        (publication_ids,),
    ).fetchone()
    if release is None:
        return None
    rows = connection.execute(
        """SELECT analysis.publication_id,analysis.metric_code,analysis.numeric_value,
                         analysis.value_status,definition.label,definition.semantic_level,
                         definition.unit,definition.aggregation_rule,definition.definition,
                         publication.canonical_name AS publication_title,
                         metadata.publication_year,journal.canonical_name AS journal_name,
                         snapshot.source_document_type,snapshot.source_research_areas,
                         snapshot.source_collaboration_type
                    FROM smartlib.publication_metric_analysis analysis
                    JOIN smartlib.publication_metric_definition definition
                      ON definition.metric_code=analysis.metric_code
                    JOIN smartlib.publication_metric_snapshot snapshot
                      ON snapshot.release_id=analysis.release_id
                     AND snapshot.publication_id=analysis.publication_id
                    JOIN smartlib.knowledge_object publication
                      ON publication.object_id=analysis.publication_id
                     AND publication.object_type='publication'
                     AND publication.system_to='infinity'::timestamptz
                    LEFT JOIN smartlib.publication_metadata metadata
                      ON metadata.publication_id=analysis.publication_id
                    LEFT JOIN smartlib.analysis_relation published_in
                      ON published_in.subject_id=analysis.publication_id
                     AND published_in.predicate='publication.published_in'
                     AND smartlib.analysis_state_eligible(published_in.review_state)
                     AND published_in.system_to='infinity'::timestamptz
                    LEFT JOIN smartlib.knowledge_object journal
                      ON journal.object_id=published_in.object_id
                     AND journal.object_type='journal'
                     AND journal.system_to='infinity'::timestamptz
                   WHERE analysis.release_id=%s
                     AND analysis.publication_id=ANY(%s::uuid[])
                   ORDER BY analysis.publication_id,analysis.metric_code""",
        (release["release_id"], publication_ids),
    ).fetchall()
    return _build_incites_analysis(
        release,
        rows,
        scoped_publication_ids={str(value) for value in publication_ids},
    )


def _build_incites_analysis(
    release: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    scoped_publication_ids: set[str],
) -> InCitesJournalAnalysis:
    definitions: dict[str, dict[str, Any]] = {}
    values: dict[str, dict[str, float]] = defaultdict(dict)
    papers: dict[str, dict[str, Any]] = {}
    for row in rows:
        publication_id = str(row["publication_id"])
        code = str(row["metric_code"])
        definitions.setdefault(code, row)
        paper = papers.setdefault(
            publication_id,
            {
                "publication_id": publication_id,
                "title": str(row["publication_title"]),
                "publication_year": row.get("publication_year"),
                "journal_name": row.get("journal_name"),
                "source_document_type": row.get("source_document_type"),
                "source_research_areas": row.get("source_research_areas"),
                "source_collaboration_type": row.get("source_collaboration_type"),
                "metric_values": {},
            },
        )
        value = row.get("numeric_value")
        numeric_value = (
            float(value)
            if row.get("value_status") == "present" and value is not None
            else None
        )
        paper["metric_values"][code] = numeric_value
        if numeric_value is not None:
            values[code][publication_id] = numeric_value

    metric_summaries: list[PublicationMetricAggregate] = []
    for code in sorted(definitions):
        definition = definitions[code]
        observed = list(values[code].values())
        reference = 1.0 if code in {"incites.cnci", "incites.jnci", "incites.collab_cnci"} else None
        metric_summaries.append(
            PublicationMetricAggregate(
                code=code,
                label=str(definition["label"]),
                semantic_level=str(definition["semantic_level"]),
                unit=str(definition["unit"]),
                aggregation_rule=str(definition["aggregation_rule"]),
                definition=str(definition["definition"]),
                covered_publications=len(observed),
                missing_publications=max(0, len(scoped_publication_ids) - len(observed)),
                mean=mean(observed) if observed else None,
                median=median(observed) if observed else None,
                minimum=min(observed) if observed else None,
                maximum=max(observed) if observed else None,
                total=sum(observed) if code == "incites.times_cited" and observed else None,
                reference=reference,
                above_reference_count=(
                    sum(value > reference for value in observed) if reference is not None else None
                ),
            )
        )
    publication_rows = [InCitesPublicationMetric(**paper) for paper in papers.values()]
    publication_rows.sort(
        key=lambda paper: (
            -(paper.metric_values.get("incites.times_cited") or 0),
            -(paper.metric_values.get("incites.cnci") or 0),
            paper.title,
        )
    )
    return InCitesJournalAnalysis(
        release_id=release["release_id"],
        exported_on=release["exported_on"],
        indexed_through=release["indexed_through"],
        dataset_updated_on=release["dataset_updated_on"],
        scope_publications=len(scoped_publication_ids),
        snapshot_publications=len(papers),
        metrics=metric_summaries,
        publications=publication_rows,
        scope_note=(
            "固定使用当前范围内最新一份已验证 InCites 快照；论文对象先去重，缺失值不按零填充。"
            "被引频次为截至索引日期的累计值；CNCI、JNCI 与 Collab-CNCI 的基准值为 1。"
            "InCites 来源 JIF 仅作导出上下文，不替代按论文发表年份匹配的 JCR 指标。"
        ),
    )


def _annual_project_portfolios(
    projects: list[ProjectMetricSummary],
    metrics: dict[str, dict[str, list[dict[str, Any]]]],
) -> list[AnnualProjectMetricPortfolio]:
    by_year: dict[int, list[ProjectMetricSummary]] = defaultdict(list)
    for project in projects:
        if project.funding_year is not None:
            by_year[project.funding_year].append(project)

    portfolios: list[AnnualProjectMetricPortfolio] = []
    for funding_year, year_projects in sorted(by_year.items(), reverse=True):
        publications = {
            paper.publication_id: paper
            for project in year_projects
            for paper in project.publications
        }
        publication_ids = set(publications)
        jcr_ids = {value for value in publication_ids if metrics[value].get("jcr")}
        cas_ids = {value for value in publication_ids if metrics[value].get("cas_partition")}
        journal_counts: dict[str, dict[str, Any]] = {}
        for paper in publications.values():
            if not paper.journal_id or not paper.journal_name:
                continue
            journal = journal_counts.setdefault(
                paper.journal_id,
                {"name": paper.journal_name, "count": 0},
            )
            journal["count"] += 1
        linked = sum(value["count"] for value in journal_counts.values())
        top_journals = [
            JournalShare(
                object_id=journal_id,
                name=value["name"],
                publication_count=value["count"],
                share=value["count"] / linked if linked else 0,
            )
            for journal_id, value in sorted(
                journal_counts.items(),
                key=lambda item: (-item[1]["count"], item[1]["name"]),
            )[:10]
        ]
        portfolios.append(
            AnnualProjectMetricPortfolio(
                funding_year=funding_year,
                project_count=len(year_projects),
                project_publication_links=sum(item.publication_count for item in year_projects),
                unique_publications=len(publications),
                shared_publication_links=(
                    sum(item.publication_count for item in year_projects) - len(publications)
                ),
                publications_with_journal=sum(
                    1 for paper in publications.values() if paper.journal_id
                ),
                jcr_matched_publications=len(jcr_ids),
                cas_matched_publications=len(cas_ids),
                impact_factor=_impact_summary(jcr_ids, metrics),
                jcr_quartiles=_quartile_distribution(jcr_ids, metrics, "jcr"),
                cas_partitions=_quartile_distribution(cas_ids, metrics, "cas_partition"),
                jcr_project_coverage=_project_metric_coverage(year_projects, "jcr"),
                cas_project_coverage=_project_metric_coverage(year_projects, "cas"),
                top_journals=top_journals,
                projects=year_projects,
            )
        )
    return portfolios


def _project_metric_coverage(
    projects: list[ProjectMetricSummary], metric_system: str
) -> ProjectMetricCoverage:
    field = "jcr_matched_publications" if metric_system == "jcr" else "cas_matched_publications"
    full = partial = none = 0
    for project in projects:
        matched = getattr(project, field)
        if matched == 0:
            none += 1
        elif matched >= project.publication_count:
            full += 1
        else:
            partial += 1
    return ProjectMetricCoverage(full=full, partial=partial, none=none)


def _impact_summary(
    publication_ids: set[str], metrics: dict[str, dict[str, list[dict[str, Any]]]]
) -> ImpactFactorSummary:
    values: list[float] = []
    for publication_id in publication_ids:
        distinct = {
            float(row["impact_factor"])
            for row in metrics[publication_id].get("jcr", [])
            if row["impact_factor"] is not None
        }
        if len(distinct) == 1:
            values.append(distinct.pop())
    return ImpactFactorSummary(
        matched_publications=len(values),
        mean=round(mean(values), 3) if values else None,
        median=round(median(values), 3) if values else None,
        minimum=round(min(values), 3) if values else None,
        maximum=round(max(values), 3) if values else None,
    )


def _quartile_distribution(
    publication_ids: set[str],
    metrics: dict[str, dict[str, list[dict[str, Any]]]],
    metric_system: str,
) -> list[QuartileShare]:
    weights = {quartile: 0.0 for quartile in ("Q1", "Q2", "Q3", "Q4")}
    covered = 0
    for publication_id in publication_ids:
        quartiles = [
            str(row["quartile"])
            for row in metrics[publication_id].get(metric_system, [])
            if row["quartile"] in weights
        ]
        if not quartiles:
            continue
        covered += 1
        weight = 1 / len(quartiles)
        for quartile in quartiles:
            weights[quartile] += weight
    return [
        QuartileShare(
            quartile=quartile,
            paper_equivalents=round(value, 3),
            share=min(max(value / covered, 0.0), 1.0) if covered else 0,
        )
        for quartile, value in weights.items()
    ]


def _funding_category_shares(rows: list[dict[str, Any]], publication_count: int) -> list[FundingShare]:
    """Union publications across kinds; never sum overlapping kind coverage."""
    publications: dict[str, set[Any]] = defaultdict(set)
    kinds: dict[str, set[str]] = defaultdict(set)
    projects: dict[str, dict[str, Any]] = defaultdict(dict)
    kind_items: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in rows:
        category = row.get("category_label") or "来源待确认"
        publications[category].update(row.get("publication_ids", []))
        kinds[category].add(str(row["object_id"]))
        kind_items[category][str(row['object_id'])] = dict(
            object_id=str(row['object_id']), name=str(row.get('canonical_name', row['object_id'])),
            project_count=len({p['object_id'] for p in row.get('projects', [])}),
            publication_count=len(set(row.get('publication_ids', []))),
        )
        for project in row.get("projects", []):
            projects[category][project["object_id"]] = project
    return [FundingShare(
        object_id=f"category:{category}", name=category,
        kinds=sorted(kind_items[category].values(), key=lambda item: (-item['publication_count'], item['name'])),
        funding_agency=f"{len(kinds[category])} 个项目种类 · 类内论文去重",
        linked_project_count=len(ids),
        projects=sorted(projects[category].values(), key=lambda item: (item['kind_name'], item['name'], item['object_id'])),
        share=len(ids) / publication_count if publication_count else 0,
    ) for category, ids in sorted(publications.items(), key=lambda item: (-len(item[1]), item[0]))]


def _funding_candidate_shares(
    rows: list[dict[str, Any]], *, display_limit: int | None = None
) -> list[FundingCandidateShare]:
    total = sum(int(row["linked_item_count"]) for row in rows)
    if total == 0:
        return []
    rows = sorted(rows, key=lambda row: (-int(row["linked_item_count"]), str(row["canonical_name"])))
    selected = list(rows[:display_limit])
    remaining = rows[display_limit:] if display_limit is not None else []
    if remaining:
        remaining_relations = sum(int(row["relation_count"]) for row in remaining)
        remaining_items = sum(int(row["linked_item_count"]) for row in remaining)
        selected.append(
            {
                "object_id": "candidate:other",
                "canonical_name": "其他项目种类",
                "relation_count": remaining_relations,
                "linked_item_count": remaining_items,
                "pending_relation_count": sum(
                    int(row.get("pending_relation_count", row["relation_count"]))
                    for row in remaining
                ),
                "approved_relation_count": sum(
                    int(row.get("approved_relation_count", 0)) for row in remaining
                ),
                "average_confidence": sum(
                    float(row["average_confidence"]) * int(row["relation_count"])
                    for row in remaining
                )
                / remaining_relations,
            }
        )
    return [
        FundingCandidateShare(
            projects=sorted({p['object_id']: p for p in row.get('projects', [])}.values(), key=lambda p: (p['name'], p['object_id'])),
            object_id=str(row["object_id"]),
            name=str(row["canonical_name"]),
            relation_count=int(row["relation_count"]),
            linked_item_count=int(row["linked_item_count"]),
            share=int(row["linked_item_count"]) / total,
            average_confidence=float(row["average_confidence"]),
            review_state=_aggregate_review_state(row),
        )
        for row in selected
    ]


def _aggregate_review_state(row: dict[str, Any]) -> str:
    pending = int(row.get("pending_relation_count", 0))
    approved = int(row.get("approved_relation_count", 0))
    if pending and approved:
        return "mixed"
    return "approved" if approved else "pending"


def _people_network(
    rows: list[dict[str, Any]], minimum: int, limit: int,
    affiliations: list[dict[str, Any]] | None = None,
    focus_id: str | None = None, organization_id: str | None = None,
    include_external: bool = False,
    scope_ids: list[str] | None = None,
    entity_type: str = "person",
    aggregation_context: dict | None = None,
) -> CollaborationNetwork:
    publications: dict[str, dict[str, Any]] = {}
    person_publications: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        publication_id = str(row["publication_id"])
        person_id = str(row["person_id"])
        publication = publications.setdefault(
            publication_id,
            {"title": str(row["publication_title"]), "people": {}, "author_evidence": {}},
        )
        publication["people"][person_id] = str(row["person_name"])
        if row.get("author_relation_id"):
            publication["author_evidence"][str(row["author_relation_id"])] = {
                "person_id": person_id, "relation_id": str(row["author_relation_id"]),
                "version": str(row.get("author_relation_version", "")),
            }
        person_publications[person_id].add(publication_id)

    pair_publications: dict[tuple[str, str], set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    for publication_id, publication in publications.items():
        people = sorted(publication["people"].items())
        names.update(people)
        for (left_id, _), (right_id, _) in combinations(people, 2):
            pair_publications[(left_id, right_id)].add(publication_id)

    eligible = [
        (pair, publication_ids)
        for pair, publication_ids in pair_publications.items()
        if len(publication_ids) >= minimum
    ]
    eligible.sort(key=lambda item: (-len(item[1]), names[item[0][0]], names[item[0][1]]))
    person_organizations: dict[str, dict[str, str]] = defaultdict(dict)
    for affiliation in affiliations or []:
        person_id = str(affiliation["person_id"])
        if str(affiliation.get("publication_id")) in person_publications.get(person_id, set()):
            person_organizations[person_id][str(affiliation["organization_id"])] = str(
                affiliation["organization_name"]
            )
    directory = [
        CollaborationNode(
            object_id=person_id, name=names[person_id], node_type="person",
            publication_count=len(publication_ids), organizations=person_organizations[person_id],
        )
        for person_id, publication_ids in sorted(
            person_publications.items(), key=lambda item: (-len(item[1]), names[item[0]], item[0])
        )
    ]
    matched = [
        (pair, publication_ids) for pair, publication_ids in eligible
        if (focus_id is None or focus_id in pair)
        and (organization_id is None or (any if include_external else all)(
            organization_id in person_organizations[person_id] for person_id in pair
        ))
    ]
    assessment = assess_cooperation(publications, person_organizations,
                                    scope_ids if scope_ids is not None else list(publications), entity_type=entity_type, aggregation_context=aggregation_context)
    community_ids = {pid: c.community_id for c in assessment.communities for pid in c.member_ids}
    selected = matched[:limit]
    node_ids = {object_id for pair, _ in selected for object_id in pair}
    nodes = [
        CollaborationNode(
            object_id=object_id,
            name=names[object_id],
            community_id=community_ids[object_id],
            node_type="person",
            publication_count=len(person_publications[object_id]),
        )
        for object_id in sorted(node_ids, key=lambda value: (-len(person_publications[value]), names[value]))
    ]
    edges = [
        _collaboration_edge(pair, publication_ids, publications)
        for pair, publication_ids in selected
    ]
    all_node_ids = {object_id for pair, _ in eligible for object_id in pair}
    return CollaborationNetwork(
        directory=directory,
        assessment=assessment,
        scope_node_count=len(directory),
        matched_node_count=len({person_id for pair, _ in matched for person_id in pair}),
        matched_edge_count=len(matched),
        nodes=nodes,
        edges=edges,
        total_node_count=len(all_node_ids),
        total_edge_count=len(eligible),
        displayed_edge_count=len(edges),
        minimum_publication_count=minimum,
        truncated=len(matched) > len(edges),
        metric_note="两位作者共同署名同一篇正式论文记为一次合作。边上的数字为共同论文数。",
    )


def _institution_network(
    rows: list[dict[str, Any]], minimum: int, limit: int,
    scope_ids: list[str] | None = None,
    aggregation_context: dict | None = None,
) -> CollaborationNetwork:
    # Adapt the shared co-publication engine using real institution identities, never focus aliases.
    adapted = [{"publication_id": str(r["publication_id"]),
                "publication_title": r.get("publication_title") or "题名尚未收录",
                "person_id": str(r["organization_id"]), "person_name": r["organization_name"],
                "author_relation_id": r.get("relation_id"),
                "author_relation_version": r.get("relation_version", "")}
               for r in rows if r.get("publication_id")]
    n = len({r["person_id"] for r in adapted})
    result = _people_network(adapted, 1, max(1, n * (n - 1) // 2),
                             scope_ids=scope_ids, entity_type="organization", aggregation_context=aggregation_context)
    for node in result.nodes + result.directory:
        node.node_type = "organization"
    result.exploration_edges = result.edges
    eligible = [e for e in result.edges if e.publication_count >= minimum]
    result.edges = eligible[:limit]
    ids = {n for e in result.edges for n in (e.source_id, e.target_id)}
    result.nodes = [n for n in result.nodes if n.object_id in ids]
    result.total_node_count = len({n for e in eligible for n in (e.source_id, e.target_id)})
    result.total_edge_count = result.matched_edge_count = len(eligible)
    result.matched_node_count = result.total_node_count
    result.displayed_edge_count = len(result.edges)
    result.minimum_publication_count = minimum
    result.truncated = len(eligible) > len(result.edges)
    result.metric_note = "同篇署名先按所选粒度归并去重，再计算合作；层级关系不作为合作边。"
    return result


def _collaboration_edge(
    pair: tuple[str, str],
    publication_ids: set[str],
    publications: dict[str, dict[str, Any]],
    *,
    collaboration_kind: str | None = None,
) -> CollaborationEdge:
    evidence = sorted(publication_ids, key=lambda value: (publications[value]["title"], value))
    digest = sha256(f"{pair[0]}:{pair[1]}".encode()).hexdigest()[:20]
    return CollaborationEdge(
        edge_id=f"co-{digest}",
        source_id=pair[0],
        target_id=pair[1],
        publication_count=len(publication_ids),
        evidence_publications=[
            EvidencePublication(object_id=value, title=publications[value]["title"]) for value in evidence
        ],
        collaboration_kind=collaboration_kind,
        highlighted=collaboration_kind is not None,
    )


def _institution_group(object_id: str, name: str, raw_affiliation: str) -> tuple[str, str]:
    name_text = name.casefold().replace("aﬃliated", "affiliated")
    raw_text = raw_affiliation.casefold().replace("aﬃliated", "affiliated")
    text = f"{name_text} {raw_text}"
    if "dalian university of technology" in name_text or "大连理工大学" in name_text:
        return "focus:dut", "大连理工大学"
    if "dalian institute of chemical physics" in name_text or "大连化学物理研究所" in name_text:
        return "focus:dicp", "中国科学院大连化学物理研究所"
    dmu = "dalian medical university" in text or "大连医科大学" in text
    first = any(marker in name_text for marker in ("first affiliated hospital", "first hospital"))
    second = any(marker in name_text for marker in ("second affiliated hospital", "second hospital"))
    canonical_dmu = "dalian medical university" in name_text or "大连医科大学" in name_text
    if canonical_dmu:
        first = first or any(marker in raw_text for marker in ("first affiliated hospital", "first hospital"))
        second = second or any(
            marker in raw_text for marker in ("second affiliated hospital", "second hospital")
        )
    if dmu and first:
        return "focus:dmu-first", "大连医科大学附属第一医院"
    if dmu and second:
        return "focus:dmu-second", "大连医科大学附属第二医院"
    campus_unit = name_text.startswith(("college of ", "advanced institute", "institute of cancer"))
    if dmu and (canonical_dmu or campus_unit) and "hospital" not in name_text:
        return "focus:dmu-campus", "大连医科大学校本部"
    return f"organization:{object_id}", name


def _institution_class(group_key: str) -> str:
    return {
        "focus:dmu-campus": "campus",
        "focus:dmu-first": "first_hospital",
        "focus:dmu-second": "second_hospital",
        "focus:dut": "engineering_university",
        "focus:dicp": "research_institute",
    }.get(group_key, "other")


def _collaboration_kind(left: str, right: str) -> str | None:
    pair = {left, right}
    medical = {"focus:dmu-campus", "focus:dmu-first", "focus:dmu-second"}
    if "focus:dmu-campus" in pair and pair & {"focus:dmu-first", "focus:dmu-second"}:
        return "校院协同"
    if pair & medical and pair & {"focus:dut", "focus:dicp"}:
        return "医工合作"
    return None


def _discipline_analysis(rows: list[dict[str, Any]]) -> DisciplineAnalysis:
    grouped: dict[tuple[str, str, str, str | None, int | None, str], set[str]] = defaultdict(set)
    classified_publications: set[str] = set()
    primary_count = 0
    secondary_count = 0
    states: set[str] = set()
    for row in rows:
        scheme = str(row.get("scheme") or "UNKNOWN")
        scheme = {
            "NSFC_APPLICATION_CODE": "NSFC_APPLICATION_CODE_2026",
            "MOE_GRADUATE_DISCIPLINE": "MOE_GRADUATE_DISCIPLINE_2022",
            "GBT_13745": "GBT_13745_2009",
        }.get(scheme, scheme)
        role = str(row.get("classification_role") or "unspecified")
        publication_id = str(row["publication_id"])
        grouped[
            (
                scheme,
                str(row["object_id"]),
                str(row["canonical_name"]),
                row.get("discipline_code"),
                row.get("discipline_level"),
                role,
            )
        ].add(publication_id)
        classified_publications.add(publication_id)
        states.add(str(row["review_state"]))
        if role == "secondary":
            secondary_count += 1
        elif role == "primary":
            primary_count += 1

    def shares(scheme: str) -> list[DisciplineShare]:
        primary_total = len({
            publication_id
            for (item_scheme, _, _, _, _, role), ids in grouped.items()
            if item_scheme == scheme and role == "primary"
            for publication_id in ids
        })
        objects: dict[tuple[str, str, str | None, int | None], dict[str, set[str]]] = defaultdict(
            lambda: {"primary": set(), "secondary": set()}
        )
        for (item_scheme, object_id, name, code, level, role), ids in grouped.items():
            if item_scheme == scheme:
                objects[(object_id, name, code, level)].setdefault(role, set()).update(ids)
        result = [
            DisciplineShare(
                object_id=object_id,
                scheme=scheme,
                code=code,
                name=name,
                level=level,
                primary_publications=len(values["primary"]),
                secondary_publications=len(values["secondary"]),
                publication_count=len(set().union(*values.values())),
                share=(len(values["primary"]) / primary_total if primary_total else 0),
            )
            for (object_id, name, code, level), values in objects.items()
        ]
        result.sort(key=lambda item: (-item.primary_publications, -item.secondary_publications, item.name))
        return result

    review_state = "pending" if "pending" in states else (next(iter(states)) if states else "unavailable")
    return DisciplineAnalysis(
        broad_disciplines=shares("MOE_GRADUATE_DISCIPLINE_2022"),
        nsfc_directions=shares("NSFC_APPLICATION_CODE_2026"),
        gbt_directions=shares("GBT_13745_2009"),
        classified_publications=len(classified_publications),
        primary_relation_count=primary_count,
        secondary_relation_count=secondary_count,
        review_state=review_state,
        scope_note=(
            "学科方向由论文全文规则分析生成。占比以各体系的主分类论文数为分母。"
            "辅分类单列且不进入占比。"
        ),
    )
