# ruff: noqa: RUF001 -- Chinese explanatory copy.
"""Paper-level descriptive comparisons. Never derive features from truncated graph edges."""
from collections import defaultdict
from hashlib import sha256
from statistics import mean, median
from typing import Any
from uuid import UUID

from smartlib_platform.foundation.database import DbConnection

from .models import (
    CollaborationOutcomes,
    OutcomeAffiliation,
    OutcomeDiscipline,
    OutcomeGroup,
    OutcomePaper,
    OutcomeProject,
)

MODES = ("多机构共同署名", "单机构共同署名", "单作者署名", "机构或作者信息不完整")


def summarize_outcomes(papers: list[OutcomePaper]) -> list[OutcomeGroup]:
    result = []
    for mode in MODES:
        rows = [p for p in papers if p.mode == mode]
        cnci = [p.cnci for p in rows if p.cnci is not None]
        cited = [p.times_cited for p in rows if p.times_cited is not None]
        jif = [p.impact_factor for p in rows if p.impact_factor is not None]
        result.append(OutcomeGroup(
            mode=mode, publication_count=len(rows), cnci_covered=len(cnci),
            cnci_median=median(cnci) if cnci else None, cnci_mean=mean(cnci) if cnci else None,
            cited_covered=len(cited), citations_median=median(cited) if cited else None,
            jcr_covered=len(jif), jif_median=median(jif) if jif else None,
        ))
    return result


def institution_roots(parents: dict[str, set[str]], node: str) -> set[str]:
    """A cyclic or ambiguous hierarchy must not be silently treated as a known root."""
    def visit(current: str, path: set[str]) -> set[str]:
        if current in path:
            return set()
        if not parents.get(current):
            return {current}
        branches = [visit(p, path | {current}) for p in parents[current]]
        return set().union(*branches) if all(branches) else set()
    return visit(node, set())


def classify_mode(author_count: int, registered_authors: int, affiliated_authors: int,
                  institution_count: int, ambiguous: bool) -> str:
    if author_count == 1:
        return MODES[2]
    complete = author_count > 1 and affiliated_authors == author_count == registered_authors
    if complete and not ambiguous and institution_count:
        return MODES[0] if institution_count > 1 else MODES[1]
    return MODES[3]


def collaboration_outcomes(
    connection: DbConnection, publication_ids: list[UUID], author_rows: list[dict[str, Any]],
    affiliation_rows: list[dict[str, Any]], journal_metric_rows: list[dict[str, Any]],
) -> CollaborationOutcomes:
    rows = connection.execute("""SELECT p.object_id,p.canonical_name,m.publication_year,m.publication_type,
        (SELECT count(*) FROM smartlib.publication_authorship a
          WHERE a.publication_id=p.object_id AND a.verification_status<>'rejected') AS author_count
        FROM smartlib.knowledge_object p LEFT JOIN smartlib.publication_metadata m
        ON m.publication_id=p.object_id WHERE p.object_id=ANY(%s::uuid[])
        ORDER BY m.publication_year DESC NULLS LAST,p.canonical_name""", (publication_ids,)).fetchall()
    hierarchy = connection.execute("""SELECT r.subject_id,r.object_id,r.predicate,
          s.canonical_name AS subject_name,t.canonical_name AS target_name
        FROM smartlib.analysis_relation r
        JOIN smartlib.knowledge_object s ON s.object_id=r.subject_id
        JOIN smartlib.knowledge_object t ON t.object_id=r.object_id
        WHERE r.predicate IN ('organization.part_of','department.part_of','organization.has_department')
          AND r.system_to='infinity' AND s.system_to='infinity' AND t.system_to='infinity'
          AND smartlib.analysis_state_eligible(r.review_state)
          AND smartlib.analysis_state_eligible(s.review_state)
          AND smartlib.analysis_state_eligible(t.review_state)""").fetchall()
    parents: dict[str, set[str]] = defaultdict(set)
    names = {}
    for r in hierarchy:
        child, parent = str(r['subject_id']), str(r['object_id'])
        names[child], names[parent] = r['subject_name'], r['target_name']
        if r['predicate'] == 'organization.has_department':
            child, parent = parent, child
        parents[child].add(parent)
    countries = {str(r['object_id']): r['country_code'] for r in connection.execute(
        'SELECT object_id,country_code FROM smartlib.organization_profile').fetchall()}
    role_rows = connection.execute("""SELECT a.* FROM smartlib.publication_authorship a
        WHERE a.publication_id=ANY(%s::uuid[]) AND a.verification_status<>'rejected'""",
        (publication_ids,)).fetchall()
    roles: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in role_rows:
        if r['person_object_id']:
            roles[str(r['publication_id']), str(r['person_object_id'])].append(r)
    topics: dict[str, list[OutcomeDiscipline]] = defaultdict(list)
    projects: dict[str, list[OutcomeProject]] = defaultdict(list)
    for r in connection.execute("""SELECT r.subject_id,r.object_id,r.review_state,
            t.canonical_name FROM smartlib.analysis_relation r
        JOIN smartlib.knowledge_object t ON t.object_id=r.object_id
        WHERE r.predicate='publication.has_research_topic' AND r.subject_id=ANY(%s::uuid[])""",
        (publication_ids,)).fetchall():
        topics[str(r['subject_id'])].append(OutcomeDiscipline(object_id=r['object_id'],
            name=r['canonical_name'],scheme='研究主题',review_state=r['review_state']))
    for r in connection.execute("""SELECT r.relation_id,r.review_state,r.predicate,
            CASE WHEN r.predicate='project.has_representative_publication'
              THEN r.object_id ELSE r.subject_id END AS publication_id,
            p.object_id,p.canonical_name,p.attributes
        FROM smartlib.analysis_relation r JOIN smartlib.knowledge_object p
          ON p.object_id=CASE WHEN r.predicate='project.has_representative_publication'
              THEN r.subject_id ELSE r.object_id END
        WHERE (r.predicate='project.has_representative_publication' AND r.object_id=ANY(%s::uuid[]))
           OR (r.predicate = 'publication.supported_by_project'
               AND r.subject_id=ANY(%s::uuid[]))""", (publication_ids,publication_ids)).fetchall():
        year = str((r['attributes'] or {}).get('funding_year', ''))
        projects[str(r['publication_id'])].append(OutcomeProject(
            object_id=r['object_id'],name=r['canonical_name'],predicate=r['predicate'],
            relation_id=r['relation_id'],review_state=r['review_state'],
            funding_year=int(year) if year.isdigit() and 1500 <= int(year) <= 2200 else None))
    person_names = {str(r['person_id']): r['person_name'] for r in author_rows}
    details: dict[str, list[OutcomeAffiliation]] = defaultdict(list)
    disciplines: dict[str, list[OutcomeDiscipline]] = defaultdict(list)
    for r in connection.execute("""SELECT r.subject_id,r.object_id,r.attributes,r.review_state,
            d.canonical_name FROM smartlib.analysis_relation r
        JOIN smartlib.knowledge_object d ON d.object_id=r.object_id
        WHERE r.predicate='publication.classified_as_discipline'
          AND r.subject_id=ANY(%s::uuid[]) ORDER BY r.object_id""", (publication_ids,)).fetchall():
        attrs = r['attributes'] or {}
        disciplines[str(r['subject_id'])].append(OutcomeDiscipline(
            object_id=r['object_id'], name=r['canonical_name'],
            scheme=attrs.get('scheme') or 'unknown', code=attrs.get('code') or attrs.get('discipline_code'),
            review_state=r['review_state']))
    authors: dict[str, set[str]] = defaultdict(set)
    affiliated: dict[str, set[str]] = defaultdict(set)
    institutions: dict[str, set[str]] = defaultdict(set)
    ambiguous = set()
    for r in author_rows:
        authors[str(r['publication_id'])].add(str(r['person_id']))
    for r in affiliation_rows:
        pid, oid = str(r['publication_id']), str(r['organization_id'])
        affiliated[pid].add(str(r['person_id']))
        names[oid] = r['organization_name']
        roots = institution_roots(parents, oid)
        if len(roots) != 1:
            ambiguous.add(pid)
        institutions[pid].update(roots)
        matched = roles[pid, str(r['person_id'])]
        role = matched[0] if len(matched) == 1 else None
        # Bibliographic order is not evidence of equal contribution or corresponding roles.
        role_labels = [label for key, label in (
            ('is_first_author', '第一作者'), ('is_co_first_author', '共同第一作者'),
            ('is_corresponding_author', '通讯作者'), ('is_co_corresponding_author', '共同通讯作者'),
        ) if role and role[key] and role['role_source'] != 'bibliographic_order'
            and role['role_evidence']]
        details[pid].append(OutcomeAffiliation(
            person_id=r['person_id'], person_name=person_names.get(str(r['person_id']), '姓名未收录'),
            organization_id=r['organization_id'], organization_name=r['organization_name'],
            root_ids=sorted(roots), country_code=countries.get(oid), roles=role_labels,
            role_source=role['role_source'] if role else None,
            relation_id=r['relation_id'], review_state=r['review_state']))
    # Pick exactly one visible validated release, never mix scopes or export vintages.
    release = connection.execute("""SELECT release_id,indexed_through
        FROM smartlib.publication_metric_latest_release r
        WHERE provider='incites' AND EXISTS (
          SELECT 1 FROM smartlib.publication_metric_snapshot s
          WHERE s.release_id=r.release_id AND s.publication_id=ANY(%s::uuid[]))
        ORDER BY indexed_through DESC,exported_on DESC,created_at DESC,release_id LIMIT 1""",
        (publication_ids,)).fetchone()
    values: dict[str, dict[str, float]] = defaultdict(dict)
    if release:
        for r in connection.execute("""SELECT publication_id,metric_code,numeric_value
            FROM smartlib.publication_metric_analysis WHERE release_id=%s
              AND publication_id=ANY(%s::uuid[]) AND value_status='present'
              AND metric_code IN ('incites.cnci','incites.times_cited')""",
            (release['release_id'], publication_ids)).fetchall():
            if r['numeric_value'] is not None:
                values[str(r['publication_id'])][r['metric_code']] = float(r['numeric_value'])
    jif: dict[str, set[float]] = defaultdict(set)
    for r in journal_metric_rows:
        if r['metric_system'] == 'jcr' and r['impact_factor'] is not None:
            jif[str(r['publication_id'])].add(float(r['impact_factor']))
    papers = []
    for r in rows:
        pid = str(r['object_id'])
        count = int(r['author_count'])
        mode = classify_mode(count, len(authors[pid]), len(affiliated[pid]),
                             len(institutions[pid]), pid in ambiguous)
        papers.append(OutcomePaper(
            publication_id=r['object_id'], title=r['canonical_name'],
            publication_year=r['publication_year'], mode=mode, author_count=count,
            institution_names=sorted(names[i] for i in institutions[pid]),
            institution_ids=sorted(institutions[pid]),
            institution_name_by_id={i: names[i] for i in sorted(institutions[pid])},
            institution_count=len(institutions[pid]), affiliation_author_count=len(affiliated[pid]),
            cnci=values[pid].get('incites.cnci'), times_cited=values[pid].get('incites.times_cited'),
            impact_factor=next(iter(jif[pid])) if len(jif[pid]) == 1 else None,
            publication_type=r['publication_type'], affiliations=details[pid],
            disciplines=disciplines[pid], topics=topics[pid], projects=projects[pid],
        ))
    return CollaborationOutcomes(
        scope_hash=sha256('\n'.join(sorted(str(p) for p in publication_ids)).encode()).hexdigest(),
        metric_release_id=release['release_id'] if release else None,
        metric_indexed_through=str(release['indexed_through']) if release else None,
        groups=summarize_outcomes(papers), papers=papers,
        notes=[
            '以当前范围的去重论文为单位；各组互斥。只使用论文署名机构，不用当前人事机构代替。',
            '按已登记的机构上下级关系归并至根机构；缺少作者机构或层次有歧义时单列，不推断国内外合作。',
            '共同署名仅代表署名结构；单作者的多个机构不计为多人合作。',
            'CNCI和被引次数只取一个可访问的已验证InCites版本；缺失不补零。JIF仅用发表年同年已发布指标，冲突保留缺失。',
            '当前代表性论著样本并非全校完整成果或全部项目申请。组间差异不证明因果，也不能据此计算获批概率。',
        ],
    )
