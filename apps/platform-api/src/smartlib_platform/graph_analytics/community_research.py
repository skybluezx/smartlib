"""Cross existing complete-scope communities with paper-backed funding and classifications.

This enriches, never reclusters. A link is not a grant-award or team-ownership claim.
"""
import json
from collections import defaultdict
from hashlib import sha256

from .models import CommunityResearch


def load_funding_inputs(connection, publication_ids):
    return connection.execute("""
        WITH links AS (
          SELECT subject_id AS publication_id, object_id AS target_id,
                 relation_id, 'funded' AS basis
          FROM smartlib.analysis_relation
          WHERE predicate='publication.supported_by_project' AND subject_id=ANY(%s::uuid[])
          UNION ALL
          SELECT object_id, subject_id, relation_id, 'representative'
          FROM smartlib.analysis_relation
          WHERE predicate='project.has_representative_publication' AND object_id=ANY(%s::uuid[])
        )
        SELECT l.*, target.canonical_name AS target_name,
               kind.object_id AS kind_id, kind.canonical_name AS kind_name,
               coalesce(kind.attributes->>'funding_source_category_label','来源待确认') AS category_label,
               program.relation_id AS program_relation_id
        FROM links l JOIN smartlib.knowledge_object target ON target.object_id=l.target_id
        LEFT JOIN smartlib.analysis_relation program ON program.subject_id=l.target_id
          AND program.predicate='project.under_program'
        LEFT JOIN smartlib.knowledge_object kind ON kind.object_id=program.object_id
        ORDER BY l.publication_id,l.basis,l.target_id,kind.object_id,l.relation_id
    """, (publication_ids, publication_ids)).fetchall()


def enrich_community_research(assessment, funding_rows, direction_rows):
    by_funding, by_direction = defaultdict(list), defaultdict(list)
    for row in funding_rows:
        by_funding[str(row['publication_id'])].append(row)
    for row in direction_rows:
        by_direction[str(row['publication_id'])].append(row)
    for community in assessment.communities:
        ids = set(community.publication_ids)
        funding, directions, projects = {}, {}, {}
        for pid in sorted(ids):
            for row in by_funding[pid]:
                basis = row['basis']
                target = str(row['target_id'])
                object_id = str(row['kind_id']) if row['kind_id'] else None
                key = f'{basis}:{object_id or "unclassified"}'
                group = funding.setdefault(key, dict(key=key, basis=basis, object_id=object_id,
                    name=row['kind_name'] or '未登记项目种类', category_label=row.get('category_label'),
                    publication_ids=set(), project_ids=set(), relation_ids=set()))
                group['publication_ids'].add(pid)
                group['relation_ids'].add(str(row['relation_id']))
                if row.get('program_relation_id'):
                    group['relation_ids'].add(str(row['program_relation_id']))
                group['project_ids'].add(target)
                projects[target] = row['target_name']
            for row in by_direction[pid]:
                oid = str(row['object_id'])
                scheme = row.get('scheme') or '未标明体系'
                version = row.get('scheme_version') or '未标明版本'
                key = json.dumps([scheme, version, oid], ensure_ascii=False)
                group = directions.setdefault(key, dict(key=key, object_id=oid,
                    name=row['canonical_name'], scheme=scheme, version=version,
                    code=row.get('discipline_code') or '', publication_ids=set(),
                    primary_publication_ids=set(), secondary_publication_ids=set(), relation_ids=set()))
                group['publication_ids'].add(pid)
                if row.get('classification_role') in ('primary', 'secondary'):
                    group[row['classification_role'] + '_publication_ids'].add(pid)
                if row.get('relation_id'):
                    group['relation_ids'].add(str(row['relation_id']))
        intersections = [dict(funding_key=f['key'], direction_key=d['key'], publication_ids=sorted(shared))
                         for f in funding.values() for d in directions.values()
                         if (shared := f['publication_ids'] & d['publication_ids'])]
        intersections.sort(key=lambda x: (-len(x['publication_ids']), x['funding_key'], x['direction_key']))
        def covered(basis):
            return set().union(*(g['publication_ids'] for g in funding.values() if g['basis'] == basis))
        linked = set().union(*(g['publication_ids'] for g in funding.values()))
        classified = set().union(*(g['publication_ids'] for g in directions.values()))
        def serialize(groups):
            return [{k: sorted(v) if isinstance(v, set) else v for k,v in g.items()}
                    for g in sorted(groups.values(), key=lambda g: (-len(g['publication_ids']), g['key']))]
        payload = dict(funding=serialize(funding), directions=serialize(directions), intersections=intersections,
            projects=projects, funded_publication_ids=sorted(covered('funded')),
            representative_publication_ids=sorted(covered('representative')),
            unlinked_publication_ids=sorted(ids-linked), unclassified_publication_ids=sorted(ids-classified))
        digest = sha256(json.dumps({'method': 'community-funding-directions-v2',
            'community_papers': sorted(ids), 'result': payload}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        community.research = CommunityResearch(input_hash=digest, **payload)
    return assessment
