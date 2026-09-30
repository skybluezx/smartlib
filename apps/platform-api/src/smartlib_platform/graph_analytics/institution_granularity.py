"""Collapse affiliations before graph construction; hierarchy never becomes a cooperation edge."""
from collections import defaultdict
from hashlib import sha256
import json

from fastapi import HTTPException
from pydantic import ValidationError

from .models import InstitutionAnalysisSettings


def load_institution_hierarchy(connection):
    objects = connection.execute("""SELECT object_id,canonical_name FROM smartlib.knowledge_object
        WHERE object_type IN ('organization','department') AND system_to='infinity'::timestamptz
          AND smartlib.analysis_state_eligible(review_state)""").fetchall()
    edges = connection.execute("""SELECT relation.relation_id, relation.system_from AS version,
        CASE WHEN relation.predicate='organization.has_department' THEN relation.object_id ELSE relation.subject_id END AS child_id,
        CASE WHEN relation.predicate='organization.has_department' THEN relation.subject_id ELSE relation.object_id END AS parent_id
        FROM smartlib.analysis_relation relation
        WHERE relation.predicate IN ('organization.part_of','department.part_of','organization.has_department')
          AND relation.system_to='infinity'::timestamptz
          AND smartlib.analysis_state_eligible(relation.review_state)
          AND relation.valid_from<=clock_timestamp() AND relation.valid_to>clock_timestamp()""").fetchall()
    return objects, edges



def aggregate_institutions(rows, hierarchy, raw_settings=None):
    try:
        settings = InstitutionAnalysisSettings.model_validate_json(raw_settings) if raw_settings else InstitutionAnalysisSettings()
    except ValidationError as exc:
        raise HTTPException(422, "机构分析配置无效，请检查粒度、机构和组合成员") from exc
    objects, edges = hierarchy
    names = {str(o['object_id']): o['canonical_name'] for o in objects}
    parents = defaultdict(set)
    for e in edges:
        parents[str(e['child_id'])].add(str(e['parent_id']))
    cache = {}

    def path(node):
        if node in cache:
            return cache[node]
        seen, route = set(), []
        cursor = node
        while True:
            if cursor in seen or cursor not in names or len(parents[cursor]) > 1:
                cache[node] = None  # Never arbitrarily choose a parent or break a cycle.
                return None
            seen.add(cursor)
            route.append(cursor)
            if not parents[cursor]:
                cache[node] = list(reversed(route))
                return cache[node]
            cursor = next(iter(parents[cursor]))

    options = []
    for node in sorted(names):
        route = path(node)
        if route and len(route) <= 2:
            options.append({'id': node, 'name': names[node], 'root_id': route[0], 'level': len(route)})
    roots = {o['id'] for o in options if o['level'] == 1}
    chosen = set(map(str, settings.root_ids))
    if not chosen <= roots:
        raise HTTPException(422, "所选机构不是有效一级机构，请重新选择")
    if settings.mode == 'internal' and len(chosen) != 1:
        raise HTTPException(422, "校内单位合作须选择一个一级机构")
    if settings.mode == 'expanded' and not chosen:
        raise HTTPException(422, "请选择至少一个需要展开的一级机构")
    def eligible_member(route):
        if not route:
            return False
        if settings.mode == 'root':
            return len(route) == 1
        if settings.mode == 'internal':
            return len(route) == 2 and route[0] in chosen
        return (len(route) == 2 and route[0] in chosen) or (len(route) == 1 and route[0] not in chosen)
    group_by_member, groups, group_names = {}, {}, set()
    for group in settings.groups:
        label = group.name.strip()
        members = sorted(set(map(str, group.member_ids)))
        if not label or label in group_names:
            raise HTTPException(422, "组合名称不能为空或重复")
        group_names.add(label)
        for member in members:
            route = path(member)
            if not eligible_member(route):
                raise HTTPException(422, "组合成员必须是当前分析粒度下的机构：一级机构，或已展开的二级机构")
            if member in group_by_member:
                raise HTTPException(422, "同一机构不能重复加入多个组合")
        gid = 'group:' + sha256(json.dumps([sorted(chosen), members], sort_keys=True).encode()).hexdigest()[:20]
        groups[gid] = {'name': label, 'member_ids': members, 'member_names': {m: names[m] for m in members}}
        for member in members:
            group_by_member[member] = gid
    mapped, mapping, unresolved_pairs, outside, ambiguous = [], {}, set(), set(), set()
    localized_pairs = set()
    root_only_rows = []
    for row in rows:
        raw = str(row['organization_id'])
        pid = str(row['publication_id'])
        route = path(raw)
        if not route:
            ambiguous.add(pid)
            continue
        root = route[0]
        if settings.mode == 'internal' and root not in chosen:
            outside.add(pid)
            continue
        expand = settings.mode == 'internal' or (settings.mode == 'expanded' and root in chosen)
        if expand and len(route) == 1:
            unresolved_pairs.add((pid, root))
            root_only_rows.append((row, pid, root))
            continue
        if expand:
            localized_pairs.add((pid, root))
        target = route[1] if expand else root
        target = group_by_member.get(target, target)
        label = groups[target]['name'] if target in groups else names[target]
        mapping[raw] = {'target_id': target, 'target_name': label, 'path': route}
        mapped.append({**row, 'organization_id': target, 'organization_name': label})
    unresolved = {pid for pid, root in unresolved_pairs - localized_pairs}
    unspecified_nodes = {}
    for row, pid, root in root_only_rows:
        if (pid, root) in localized_pairs:
            continue  # Same-paper parent text is redundant when a lower unit is known.
        node_id = f"unassigned:{root}"
        label = f"{names[root]} · 下属单位未明确"
        unspecified_nodes[node_id] = {'root_id': root, 'name': label}
        mapped.append({**row, 'organization_id': node_id, 'organization_name': label})
    present = {str(r['publication_id']) for r in mapped}
    context = {
        'version': 'institution-granularity-v2', 'settings': settings.model_dump(mode='json'),
        'unspecified_nodes': unspecified_nodes,
        'groups': groups, 'mapping': dict(sorted(mapping.items())),
        'hierarchy_evidence': sorted([{'relation_id': str(e.get('relation_id','')), 'version': str(e.get('version','')),
              'child_id':str(e['child_id']), 'parent_id':str(e['parent_id'])} for e in edges], key=lambda e:(e['child_id'],e['parent_id'],e['relation_id'])),
        'root_only_publication_ids': sorted(unresolved),
        'invalid_hierarchy_publication_ids': sorted(ambiguous),
        'outside_only_publication_ids': sorted(outside-present-unresolved-ambiguous),
        'mapped_publication_count': len(present),
    }
    return mapped, options, context
