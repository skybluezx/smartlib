"""Full-scope, reproducible descriptive cooperation assessment (not team certification)."""

# ruff: noqa: RUF001
import json
from collections import Counter
from functools import lru_cache
from hashlib import sha256
from itertools import combinations
from math import ceil
from statistics import median

import networkx as nx

from .models import CooperationAssessment, CooperationCommunity, CommunityCenter

METHOD = "cooperation-louvain-v1"
PARAMETERS = {
    "resolution": 1.0,
    "seed": 42,
    "threshold": 1e-7,
    "minimum_shared_papers": 1,
    "weight": "distinct_shared_publication_count",
    "engine": "NetworkX on PostgreSQL analytical facts",
}


def _partition(graph, resolution=1.0, seed=42, weight="weight"):
    if not graph.number_of_edges():
        return [{n} for n in graph]
    return nx.community.louvain_communities(
        graph,
        weight=weight,
        resolution=resolution,
        seed=seed,
        threshold=1e-7,
    )


def _ari(left, right):
    """Adjusted Rand index on the identical node universe; not a confidence probability."""
    a = {n: i for i, c in enumerate(left) for n in c}
    b = {n: i for i, c in enumerate(right) for n in c}
    choose = lambda n: n * (n - 1) / 2  # noqa: E731
    total = choose(len(a))
    if not total:
        return 1.0
    observed = sum(choose(n) for n in Counter((a[n], b[n]) for n in a).values())
    sa = sum(choose(len(c)) for c in left)
    sb = sum(choose(len(c)) for c in right)
    expected = sa * sb / total
    denominator = (sa + sb) / 2 - expected
    return (observed - expected) / denominator if denominator else 1.0


def assess_cooperation(publications, organizations, scope_ids, entity_type="person", aggregation_context=None):
    # Canonical public input captures identities, titles, affiliation assignments and missing papers.
    payload = json.dumps(
        {
            **({"entity_type": entity_type} if entity_type != "person" else {}),
            **({"aggregation_context": aggregation_context} if aggregation_context else {}),
            "centers_policy": "top-5pct-median-1.2-v2",
            "scope": sorted(set(scope_ids)),
            "papers": [
                {
                    "publication_id": pid,
                    "title": p["title"],
                    "author_evidence": sorted(
                        p.get("author_evidence", {}).values(), key=lambda r: r["relation_id"]
                    ),
                    "authors": [
                        {
                            "id": n,
                            "name": name,
                            "organizations": dict(sorted(organizations.get(n, {}).items())),
                        }
                        for n, name in sorted(p["people"].items())
                    ],
                }
                for pid, p in sorted(publications.items())
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _assess_cached(payload).model_copy(deep=True)


@lru_cache(maxsize=8)
def _assess_cached(payload):
    source = json.loads(payload)
    graph = nx.Graph()
    for paper in source["papers"]:
        ids = sorted({a["id"] for a in paper["authors"]})
        graph.add_nodes_from(ids)
        for a, b in combinations(ids, 2):
            if not graph.has_edge(a, b):
                graph.add_edge(a, b, weight=0, fractional=0.0)
            graph[a][b]["weight"] += 1
            graph[a][b]["fractional"] += 1 / (len(ids) - 1)
    # Canonical insertion order prevents input row ordering changing the stochastic result.
    ordered = nx.Graph()
    ordered.add_nodes_from(sorted(graph))
    ordered.add_edges_from((a, b, graph[a][b]) for a, b in sorted(graph.edges()))
    graph = ordered
    baseline = sorted(_partition(graph), key=lambda c: (-len(c), sorted(c)))
    seed_runs = [_partition(graph, seed=seed) for seed in range(43, 47)]
    sensitivity = [
        {
            "kind": "seed",
            "value": seed,
            "adjusted_rand_index": _ari(baseline, run),
            "community_count": len(run),
        }
        for seed, run in zip(range(43, 47), seed_runs, strict=True)
    ]
    for resolution in (0.8, 1.2):
        run = _partition(graph, resolution=resolution)
        sensitivity.append(
            {
                "kind": "resolution",
                "value": resolution,
                "adjusted_rand_index": _ari(baseline, run),
                "community_count": len(run),
            }
        )
    fractional = _partition(graph, weight="fractional")
    sensitivity.append(
        {
            "kind": "weight",
            "value": "sum(1/(authors_per_paper-1))",
            "adjusted_rand_index": _ari(baseline, fractional),
            "community_count": len(fractional),
        }
    )
    groups = []
    for i, members in enumerate(baseline):
        sub = graph.subgraph(members)
        boundary = list(nx.edge_boundary(graph, members, data=True))
        internal_weight = sub.size(weight="weight")
        external_weight = sum(d["weight"] for _, _, d in boundary)
        volume = 2 * internal_weight + external_weight
        member_metrics = community_center_metrics(sub)
        groups.append(
            CooperationCommunity(
                community_id=i,
                centers=[c for c in member_metrics if c.roles],
                member_center_metrics=member_metrics,
                centers_method='top-5pct-median-1.2-v2',
                member_ids=sorted(members),
                publication_ids=[
                    p["publication_id"]
                    for p in source["papers"]
                    if len(members & {a["id"] for a in p["authors"]}) >= min(2, len(members))
                ],
                internal_edge_count=sub.number_of_edges(),
                external_edge_count=len(boundary),
                density=nx.density(sub),
                internal_weight_share=2 * internal_weight / volume if volume else None,
                connected_components=nx.number_connected_components(sub),
                seed_stability=sum(
                    max(len(members & other) / len(members | other) for other in run) for run in seed_runs
                )
                / len(seed_runs),
            )
        )
    people = {a["id"]: a for p in source["papers"] for a in p["authors"]}
    name_counts = Counter(a["name"].casefold().strip() for a in people.values())
    repeated_names = sum(count > 1 for count in name_counts.values())
    missing_orgs = sum(not a["organizations"] for a in people.values())
    present = {p["publication_id"] for p in source["papers"]}
    return CooperationAssessment(
        entity_type=source.get("entity_type", "person"),
        aggregation_context=source.get("aggregation_context", {}),
        method_version=METHOD,
        library_version=nx.__version__,
        parameters=PARAMETERS,
        input_hash=sha256(
            (METHOD + nx.__version__ + json.dumps(PARAMETERS, sort_keys=True) + payload).encode()
        ).hexdigest(),
        scope_publication_ids=source["scope"],
        missing_author_publication_ids=sorted(set(source["scope"]) - present),
        node_count=len(graph),
        edge_count=graph.number_of_edges(),
        isolated_node_count=len(list(nx.isolates(graph))),
        connected_component_count=nx.number_connected_components(graph),
        modularity=nx.community.modularity(graph, baseline) if graph.number_of_edges() else None,
        sensitivity=sensitivity,
        communities=groups,
        publications=source["papers"],
        warnings=([
            "机构先按所选粒度和编组归并，再按分析节点去重；层级关系不计为合作，不按名称猜测隶属关系。",
            "同一论文归并后的不同机构或组合两两连边，权重为去重共同论文数；同一节点内部不产生自连接。",
            "全部范围机构参与分簇，显示连线、合作阈值、探索机构和隐藏操作不改变分簇与成果指标。",
            "孤立机构表示当前论文范围内没有跨机构共同署名，不代表没有科研成果或现实合作。",
            "结构中心不等于牵头单位；分簇不认定正式联盟、行政归属或科研质量。",
        ] if source.get("entity_type") == "organization" else [
            f"当前有 {repeated_names} 组相同显示姓名对应多个人员对象；"
            "不自动视为重复，需结合原文与身份信息核查。"
            f"缺少署名机构关联的人员对象有 {missing_orgs} 个；存在关联也不代表对应关系已经完整正确。",
            "仅描述当前论文样本的合作结构，不认定正式团队，不用于个人质量排名或项目成功率推断。",
            "全范围全部署名人员与至少共同一篇论文的关系参与分簇；探索筛选、显示连线数和隐藏操作不改变评价分簇。",
            "人员按业务对象编号去重；姓名消歧、作者遗漏与机构对应完整性仍需核查。",
            "机构为论文范围内署名机构集合，不表示当前人事归属。",
            "模块度不是科研质量分数；随机种子和分辨率敏感性用于揭示划分不确定性，不是统计置信度。",
            "Louvain 存在分辨率限制且可能产生内部不连通的社区；内部连通分量大于1的簇须进一步核实。",
        ]),
    )


def community_centers(graph):
    return [c for c in community_center_metrics(graph) if c.roles]


def community_center_metrics(graph, strict=True):
    """Descriptive candidates: top 5 percent plus 1.2 times median, retaining ties.

    The percentile/prominence rule is a display heuristic, not a validated leadership threshold.
    Uniform scores do not identify a distinctive center. No external edges are used.
    """
    if len(graph) == 0:
        return []
    ordered = nx.Graph()
    ordered.add_nodes_from(sorted(graph))
    ordered.add_edges_from((u, v, graph[u][v]) for u, v in sorted(
        tuple(sorted((a, b))) for a, b in graph.edges()))
    graph = ordered
    strengths = dict(graph.degree(weight="weight"))
    bridges = {n: round(v, 12) for n, v in
               nx.betweenness_centrality(graph, normalized=True, weight=None).items()}
    selected = {}
    for role, scores in (("合作联系突出", strengths), ("簇内桥梁", bridges)):
        values = sorted(scores.values(), reverse=True)
        if values[0] == values[-1]:
            continue
        threshold = values[max(0, ceil(len(values) * (.05 if strict else .1)) - 1)]
        prominence = 1.2 * median(values) if strict else 0
        for node, score in scores.items():
            if score > 0 and score >= threshold and score >= prominence:
                selected.setdefault(node, []).append(role)
    max_strength = max(strengths.values(), default=0) or 1
    max_bridge = max(bridges.values(), default=0) or 1
    def rank(node):
        if not strict:
            return (-strengths[node], -bridges[node], node)
        return (-len(selected.get(node, [])),
                -max(strengths[node]/max_strength, bridges[node]/max_bridge),
                -strengths[node], -bridges[node], node)
    return [CommunityCenter(person_id=str(node), roles=selected.get(node, []),
                            internal_degree=graph.degree(node),
                            internal_strength=strengths[node], betweenness=bridges[node])
            for node in sorted(graph, key=rank)]
