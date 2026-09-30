from uuid import UUID

from smartlib_platform.foundation.database import DbConnection
from .overview import load_overview

from .models import (
    ScholarAffiliation,
    ScholarDirection,
    ScholarEvidenceBundle,
    ScholarEvidenceItem,
    ScholarMetrics,
    ScholarProfile,
    ScholarRelatedItem,
    ScholarSummary,
)


def list_scholars(
    connection: DbConnection,
    *,
    object_id: UUID | None = None,
    query: str | None = None,
    department: str | None = None,
    research_direction: str | None = None,
    limit: int = 50,
) -> list[ScholarSummary]:
    query_pattern = f"%{query.strip()}%" if query and query.strip() else None
    department_pattern = f"%{department.strip()}%" if department and department.strip() else None
    direction_pattern = (
        f"%{research_direction.strip()}%" if research_direction and research_direction.strip() else None
    )
    rows = connection.execute(
        """SELECT person.object_id,
                  COALESCE(person.attributes ->> 'scholar_id', person.object_id::text) AS scholar_id,
                  person.canonical_name,
                  COALESCE(person.attributes ->> 'initials', left(person.canonical_name, 1)) AS initials,
                  person.attributes ->> 'title' AS title,
                  department.canonical_name AS department,
                  COALESCE(department.names, ARRAY[]::text[]) AS authoritative_organizations,
                  ARRAY(SELECT DISTINCT org.canonical_name
                    FROM smartlib.analysis_relation ar
                    JOIN smartlib.knowledge_object org ON org.object_id=ar.object_id
                    WHERE ar.subject_id=person.object_id AND ar.predicate='person.affiliated_with'
                       AND ar.system_to='infinity'::timestamptz
                      AND org.system_to='infinity'::timestamptz
                    ORDER BY org.canonical_name) AS output_organizations,
                  discipline.canonical_name AS discipline,
                  direction.canonical_name AS primary_direction,
                  COALESCE(metrics.publications, 0) AS publications,
                  COALESCE(metrics.projects, 0) AS projects,
                  COALESCE(metrics.collaborators, 0) AS collaborators,
                  COALESCE((person.attributes ->> 'synthetic')::boolean, false) AS synthetic,
                  person.attributes ->> 'dataset_version' AS dataset_version,
                  person.version AS object_version,
                  person.updated_at
             FROM smartlib.knowledge_object person
             LEFT JOIN LATERAL (
                 SELECT string_agg(DISTINCT target.canonical_name, '、'
                                   ORDER BY target.canonical_name) AS canonical_name,
                        array_agg(DISTINCT target.canonical_name ORDER BY target.canonical_name) AS names
                   FROM smartlib.relation_assertion relation
                   JOIN smartlib.knowledge_object target ON target.object_id = relation.object_id
                  WHERE relation.subject_id = person.object_id
                    AND relation.predicate = 'person.authoritatively_affiliated_with'
                    AND relation.review_state = 'approved'
                    AND relation.system_to = 'infinity'::timestamptz
                    AND target.system_to = 'infinity'::timestamptz
                    AND relation.valid_from <= now() AND relation.valid_to > now()
             ) department ON true
             LEFT JOIN LATERAL (
                 SELECT target.canonical_name
                   FROM smartlib.relation_assertion relation
                   JOIN smartlib.knowledge_object target ON target.object_id = relation.object_id
                  WHERE relation.subject_id = person.object_id
                    AND relation.predicate = 'person.member_of_discipline'
                    AND relation.review_state = 'approved'
                  ORDER BY target.canonical_name LIMIT 1
             ) discipline ON true
             LEFT JOIN LATERAL (
                 SELECT target.canonical_name
                   FROM smartlib.analysis_relation authored
                   JOIN smartlib.analysis_relation classification
                     ON classification.subject_id=authored.object_id
                   JOIN smartlib.knowledge_object target ON target.object_id=classification.object_id
                  WHERE authored.subject_id=person.object_id AND authored.predicate='person.authored'
                    AND classification.predicate='publication.classified_as_discipline'
                  GROUP BY target.object_id,target.canonical_name
                  ORDER BY count(DISTINCT authored.object_id) DESC,target.canonical_name
                  LIMIT 1
             ) direction ON true
             LEFT JOIN LATERAL (
                 SELECT
                   count(DISTINCT relation.object_id) FILTER (
                     WHERE relation.predicate = 'person.authored'
                       AND target.object_type = 'publication')::integer AS publications,
                   count(DISTINCT relation.object_id) FILTER (
                     WHERE relation.predicate IN ('person.participates_in', 'person.leads_project')
                       AND target.object_type = 'project')::integer AS projects,
                   (SELECT count(DISTINCT coauthor.subject_id)::integer
                      FROM smartlib.analysis_relation authored
                      JOIN smartlib.analysis_relation coauthor ON coauthor.object_id=authored.object_id
                       AND coauthor.predicate='person.authored' AND coauthor.subject_id<>person.object_id
                     WHERE authored.subject_id=person.object_id AND authored.predicate='person.authored') AS collaborators
                   FROM smartlib.analysis_relation relation
                   JOIN smartlib.knowledge_object target ON target.object_id = relation.object_id
                  WHERE relation.subject_id = person.object_id
                    
             ) metrics ON true
            WHERE person.object_type = 'person'
              AND person.system_to = 'infinity'::timestamptz
              AND smartlib.analysis_state_eligible(person.review_state)
              AND (%s::uuid IS NULL OR person.object_id = %s)
              AND (%s::text IS NULL OR person.canonical_name ILIKE %s OR person.description ILIKE %s
                   OR EXISTS(SELECT 1 FROM smartlib.person_name_variant n
                     WHERE n.object_id=person.object_id AND n.verification_status='matched'
                       AND n.name ILIKE %s)
                   OR EXISTS(SELECT 1 FROM smartlib.person_identifier i
                     WHERE i.object_id=person.object_id AND i.verification_status='matched'
                       AND i.normalized_value ILIKE %s)
                   OR department.canonical_name ILIKE %s OR discipline.canonical_name ILIKE %s
                   OR direction.canonical_name ILIKE %s OR EXISTS (
                       SELECT 1 FROM smartlib.relation_assertion qr
                       JOIN smartlib.knowledge_object qo ON qo.object_id = qr.object_id
                       WHERE qr.subject_id = person.object_id
                         AND qr.predicate = 'person.researches'
                         AND qr.review_state IN ('approved', 'pending')
                         AND qo.canonical_name ILIKE %s))
              AND (%s::text IS NULL OR department.canonical_name ILIKE %s)
              AND (%s::text IS NULL OR direction.canonical_name ILIKE %s OR EXISTS (
                       SELECT 1 FROM smartlib.relation_assertion dr
                       JOIN smartlib.knowledge_object direction_object
                         ON direction_object.object_id = dr.object_id
                       WHERE dr.subject_id = person.object_id
                         AND dr.predicate = 'person.researches'
                         AND dr.review_state IN ('approved', 'pending')
                         AND direction_object.canonical_name ILIKE %s))
            ORDER BY person.canonical_name, person.object_id
            LIMIT %s""",
        (
            object_id,
            object_id,
            query_pattern,
            query_pattern,
            query_pattern,
            query_pattern,
            query_pattern,
            query_pattern,
            query_pattern,
            query_pattern,
            query_pattern,
            department_pattern,
            department_pattern,
            direction_pattern,
            direction_pattern,
            direction_pattern,
            limit,
        ),
    ).fetchall()
    return [_summary(row) for row in rows]


def resolve_scholar_object_id(connection: DbConnection, scholar_id: str) -> UUID | None:
    row = connection.execute(
        """SELECT object_id
             FROM smartlib.knowledge_object
            WHERE object_type = 'person'
              AND system_to = 'infinity'::timestamptz
              AND (attributes ->> 'scholar_id' = %s OR object_id::text = %s)
            ORDER BY object_id
            LIMIT 1""",
        (scholar_id, scholar_id),
    ).fetchone()
    return row["object_id"] if row else None


def get_scholar_profile(connection: DbConnection, scholar_id: UUID) -> ScholarProfile | None:
    summaries = _load_scholar_summary(connection, scholar_id)
    if summaries is None:
        return None
    description_row = connection.execute(
        "SELECT description FROM smartlib.knowledge_object WHERE object_id = %s AND object_type = 'person'",
        (scholar_id,),
    ).fetchone()
    disciplines = connection.execute(
        """SELECT target.canonical_name
             FROM smartlib.relation_assertion relation
             JOIN smartlib.knowledge_object target ON target.object_id = relation.object_id
            WHERE relation.subject_id = %s
              AND relation.predicate = 'person.member_of_discipline'
              AND relation.review_state = 'approved'
            ORDER BY target.canonical_name""",
        (scholar_id,),
    ).fetchall()
    direction_rows = connection.execute(
        """SELECT target.object_id, target.canonical_name, relation.relation_id,
                  relation.fact_class, relation.confidence, relation.review_state,
                  count(link.evidence_id)::integer AS evidence_count
             FROM smartlib.relation_assertion relation
             JOIN smartlib.knowledge_object target ON target.object_id = relation.object_id
             LEFT JOIN smartlib.relation_evidence link ON link.relation_id = relation.relation_id
            WHERE relation.subject_id = %s AND relation.predicate = 'person.researches'
              AND relation.review_state IN ('approved', 'pending')
            GROUP BY target.object_id, target.canonical_name, relation.relation_id,
                     relation.fact_class, relation.confidence, relation.review_state
            ORDER BY CASE relation.review_state WHEN 'approved' THEN 0 ELSE 1 END,
                     relation.confidence DESC NULLS LAST, target.canonical_name""",
        (scholar_id,),
    ).fetchall()
    return ScholarProfile(
        overview=load_overview(connection, scholar_id),
        summary=summaries,
        description=description_row["description"] if description_row else None,
        disciplines=[row["canonical_name"] for row in disciplines],
        research_directions=[ScholarDirection.model_validate(row) for row in direction_rows],
        representative_publications=_related_items(
            connection, scholar_id, predicate="person.authored", object_type="publication", limit=10
        ),
        projects=_related_items(
            connection,
            scholar_id,
            predicates=["person.leads_project", "person.participates_in"],
            object_type="project",
            limit=10,
        ),
        collaborators=_collaborators(connection, scholar_id, limit=10),
        affiliations=_affiliations(connection, scholar_id),
    )


def _affiliations(connection: DbConnection, scholar_id: UUID) -> list[ScholarAffiliation]:
    rows = connection.execute(
        """SELECT r.relation_id, o.object_id AS organization_id,
                  o.canonical_name AS organization_name,
                  CASE WHEN o.attributes->>'organization_level' ~ '^[0-9]+$'
                       THEN (o.attributes->>'organization_level')::int END AS organization_level,
                  ARRAY(SELECT DISTINCT parent.object_id
                    FROM smartlib.relation_assertion h
                    JOIN smartlib.knowledge_object parent ON parent.object_id = CASE
                      WHEN h.predicate='organization.has_department' THEN h.subject_id ELSE h.object_id END
                    WHERE ((h.subject_id=o.object_id AND h.predicate IN ('organization.part_of','department.part_of'))
                       OR (h.object_id=o.object_id AND h.predicate='organization.has_department'))
                      AND h.review_state='approved' AND h.system_to='infinity'::timestamptz
                      AND h.valid_from<=now() AND h.valid_to>now()
                      AND parent.system_to='infinity'::timestamptz
                      AND parent.review_state NOT IN ('rejected','superseded')) AS parent_organization_ids,
                  CASE WHEN r.predicate='person.authoritatively_affiliated_with'
                       THEN 'authoritative' ELSE 'output' END AS category,
                  r.context_object_id, context.canonical_name AS context_title,
                  r.attributes->>'raw_affiliation' AS raw_affiliation,
                  CASE WHEN isfinite(r.valid_from) THEN r.valid_from::text END AS valid_from,
                  CASE WHEN isfinite(r.valid_to) THEN r.valid_to::text END AS valid_to,
                  (r.valid_from <= now() AND r.valid_to > now()) AS is_current,
                  COALESCE((SELECT jsonb_agg(jsonb_build_object(
                      'evidence_id', e.evidence_id, 'citation', e.citation,
                      'excerpt', e.excerpt, 'page_number', e.page_number,
                      'fulltext_resource_id', e.fulltext_resource_id,
                      'source_name', s.name, 'source_reference_id', ref.source_reference_id,
                      'observed_at', ref.observed_at))
                    FROM smartlib.relation_evidence re
                    JOIN smartlib.evidence_record e USING(evidence_id)
                    LEFT JOIN smartlib.source_reference ref USING(source_reference_id)
                    LEFT JOIN smartlib.source_system s USING(source_system_id)
                    WHERE re.relation_id=r.relation_id), '[]'::jsonb) AS evidence
             FROM smartlib.relation_assertion r
             JOIN smartlib.knowledge_object o ON o.object_id=r.object_id
             LEFT JOIN smartlib.knowledge_object context ON context.object_id=r.context_object_id
            WHERE r.subject_id=%s AND r.predicate IN
              ('person.affiliated_with','person.authoritatively_affiliated_with')
              AND ((r.predicate='person.authoritatively_affiliated_with' AND r.review_state='approved')
                   OR (r.predicate='person.affiliated_with' AND EXISTS (SELECT 1 FROM smartlib.analysis_relation eligible WHERE eligible.relation_id=r.relation_id)))
              AND r.system_to='infinity'::timestamptz
              AND o.system_to='infinity'::timestamptz
            ORDER BY category, o.canonical_name, context.canonical_name, r.relation_id""",
        (scholar_id,),
    ).fetchall()
    return [ScholarAffiliation.model_validate(row) for row in rows]


def get_scholar_evidence(connection: DbConnection, scholar_id: UUID) -> ScholarEvidenceBundle | None:
    scholar = connection.execute(
        """SELECT object_id,
                  COALESCE(attributes ->> 'scholar_id', object_id::text) AS scholar_id,
                  version FROM smartlib.knowledge_object
            WHERE object_id = %s AND object_type = 'person'""",
        (scholar_id,),
    ).fetchone()
    if scholar is None:
        return None
    rows = connection.execute(
        """WITH evidence_scope AS (
               SELECT evidence.evidence_id, evidence.object_id, evidence.evidence_type,
                      evidence.citation, evidence.excerpt, evidence.source_reference_id,
                      source.name AS source_name, reference.source_version,
                      reference.observed_at,
                      COALESCE(evidence.metadata ->> 'dataset_version',
                               reference.metadata ->> 'dataset_version',
                               source.metadata ->> 'dataset_version') AS dataset_version,
                      COALESCE((evidence.metadata ->> 'synthetic')::boolean,
                               (reference.metadata ->> 'synthetic')::boolean,
                               (source.metadata ->> 'synthetic')::boolean, false) AS synthetic,
                      NULL::uuid AS relation_id, NULL::text AS predicate,
                      NULL::text AS fact_class, NULL::numeric AS confidence,
                      NULL::text AS review_state, 0 AS scope_order
                 FROM smartlib.evidence_record evidence
                 LEFT JOIN smartlib.source_reference reference
                   ON reference.source_reference_id = evidence.source_reference_id
                 LEFT JOIN smartlib.source_system source
                   ON source.source_system_id = reference.source_system_id
                WHERE evidence.object_id = %s
               UNION ALL
               SELECT DISTINCT evidence.evidence_id, evidence.object_id, evidence.evidence_type,
                      evidence.citation, evidence.excerpt, evidence.source_reference_id,
                      source.name AS source_name, reference.source_version,
                      reference.observed_at,
                      COALESCE(evidence.metadata ->> 'dataset_version',
                               reference.metadata ->> 'dataset_version',
                               source.metadata ->> 'dataset_version') AS dataset_version,
                      COALESCE((evidence.metadata ->> 'synthetic')::boolean,
                               (reference.metadata ->> 'synthetic')::boolean,
                               (source.metadata ->> 'synthetic')::boolean, false) AS synthetic,
                      relation.relation_id, relation.predicate, relation.fact_class,
                      relation.confidence, relation.review_state, 1 AS scope_order
                 FROM smartlib.relation_assertion relation
                 JOIN smartlib.relation_evidence link ON link.relation_id = relation.relation_id
                 JOIN smartlib.evidence_record evidence ON evidence.evidence_id = link.evidence_id
                 LEFT JOIN smartlib.source_reference reference
                   ON reference.source_reference_id = evidence.source_reference_id
                 LEFT JOIN smartlib.source_system source
                   ON source.source_system_id = reference.source_system_id
                WHERE relation.subject_id = %s OR relation.object_id = %s
           )
           SELECT evidence_id, object_id, evidence_type, citation, excerpt,
                  source_reference_id, source_name, source_version, observed_at,
                  dataset_version, synthetic, relation_id, predicate, fact_class,
                  confidence, review_state
             FROM evidence_scope
            ORDER BY scope_order, predicate NULLS FIRST, citation, evidence_id""",
        (scholar_id, scholar_id, scholar_id),
    ).fetchall()
    return ScholarEvidenceBundle(
        scholar_id=scholar["scholar_id"],
        object_version=scholar["version"],
        items=[ScholarEvidenceItem.model_validate(row) for row in rows],
    )


def _load_scholar_summary(connection: DbConnection, scholar_id: UUID) -> ScholarSummary | None:
    rows = list_scholars(connection, object_id=scholar_id, limit=1)
    return rows[0] if rows else None


def _related_items(
    connection: DbConnection,
    scholar_id: UUID,
    *,
    predicate: str | None = None,
    predicates: list[str] | None = None,
    object_type: str,
    limit: int,
) -> list[ScholarRelatedItem]:
    rows = connection.execute(
        """SELECT target.object_id, target.object_type, target.canonical_name,
                  target.description, relation.relation_id, relation.predicate,
                  relation.fact_class, relation.confidence, relation.review_state,
                  count(link.evidence_id)::integer AS evidence_count,
                  target.version AS object_version,
                  CASE WHEN target.object_type='publication' THEN (SELECT publication_year FROM smartlib.publication_metadata WHERE publication_id=target.object_id) WHEN target.attributes ->> 'year' ~ '^[0-9]{4}$'
                       THEN (target.attributes ->> 'year')::integer END AS year,
                  COALESCE(target.attributes ->> 'publication_type',
                           target.attributes ->> 'project_state') AS item_type
             FROM smartlib.analysis_relation relation
             JOIN smartlib.knowledge_object target ON target.object_id = relation.object_id
             LEFT JOIN smartlib.relation_evidence link ON link.relation_id = relation.relation_id
            WHERE relation.subject_id = %s AND relation.predicate = ANY(%s)
              AND target.object_type = %s 
            GROUP BY target.object_id, target.object_type, target.canonical_name,
                     target.description, relation.relation_id, relation.predicate,
                     relation.fact_class, relation.confidence, relation.review_state,
                     target.version, target.attributes
            ORDER BY year DESC NULLS LAST, target.canonical_name
            LIMIT %s""",
        (scholar_id, predicates or ([predicate] if predicate else []), object_type, limit),
    ).fetchall()
    return [ScholarRelatedItem.model_validate(row) for row in rows]


def _collaborators(connection: DbConnection, scholar_id: UUID, *, limit: int) -> list[ScholarRelatedItem]:
    rows = connection.execute(
        """SELECT person.object_id,person.object_type,person.canonical_name,person.description,
            min(coauthor.relation_id::text)::uuid AS relation_id,
            'derived.coauthorship' AS predicate,'literature_fact' AS fact_class,
            NULL::float AS confidence,'pending' AS review_state,
            count(DISTINCT evidence.evidence_id)::integer AS evidence_count,
            person.version AS object_version,NULL::integer AS year,
            person.attributes->>'title' AS item_type
        FROM smartlib.analysis_relation authored
        JOIN smartlib.analysis_relation coauthor ON coauthor.object_id=authored.object_id
            AND coauthor.predicate='person.authored' AND coauthor.subject_id<>%s
        JOIN smartlib.knowledge_object person ON person.object_id=coauthor.subject_id
        LEFT JOIN smartlib.relation_evidence evidence ON evidence.relation_id=coauthor.relation_id
        WHERE authored.subject_id=%s AND authored.predicate='person.authored'
        GROUP BY person.object_id,person.object_type,person.canonical_name,person.description,
                 person.version,person.attributes
        ORDER BY count(DISTINCT authored.object_id) DESC,person.canonical_name
        LIMIT %s""", (scholar_id,scholar_id,limit)).fetchall()
    return [ScholarRelatedItem.model_validate(row) for row in rows]


def _summary(row: dict[str, object]) -> ScholarSummary:
    return ScholarSummary(
        object_id=row["object_id"],
        scholar_id=str(row["scholar_id"]),
        canonical_name=str(row["canonical_name"]),
        initials=str(row["initials"]),
        title=str(row["title"]) if row["title"] is not None else None,
        department=str(row["department"]) if row["department"] is not None else None,
        authoritative_organizations=row.get("authoritative_organizations", []),
        output_organizations=row.get("output_organizations", []),
        discipline=str(row["discipline"]) if row["discipline"] is not None else None,
        primary_direction=(str(row["primary_direction"]) if row["primary_direction"] is not None else None),
        metrics=ScholarMetrics(
            publications=int(row["publications"]),
            projects=int(row["projects"]),
            collaborators=int(row["collaborators"]),
        ),
        synthetic=bool(row["synthetic"]),
        dataset_version=(str(row["dataset_version"]) if row["dataset_version"] is not None else None),
        object_version=int(row["object_version"]),
        updated_at=row["updated_at"],
    )
