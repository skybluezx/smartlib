"""Publication-deduplicated community portfolios, with frozen metric evidence."""
import json
from collections import defaultdict
from hashlib import sha256
from math import isfinite
from statistics import mean, median

from .models import CommunityMetric, CommunityQuartiles

METRICS = {
    'journal.jif': '同年 JCR 影响因子',
    'incites.times_cited': '被引频次',
    'incites.cnci': 'CNCI',
    'incites.jnci': 'JNCI',
    'incites.collab_cnci': 'Collab-CNCI',
    'incites.subject_percentile': '学科领域百分位',
    'incites.jif_context': 'InCites 来源 JIF（独立背景值）',
    'incites.category_expected_citations': '类别预期被引频次',
    'incites.journal_expected_citations': '期刊预期被引频次',
    'incites.collaboration_expected_citations': '合作学科预期被引频次',
}
METHOD = 'community-portfolios-v1'


def load_metric_inputs(connection, publication_ids, journal_rows):
    # Same authorized analytical view and one-release selection as collaboration outcomes.
    release = connection.execute("""SELECT release_id,indexed_through,exported_on,dataset_updated_on
        FROM smartlib.publication_metric_latest_release r
        WHERE provider='incites' AND EXISTS (
          SELECT 1 FROM smartlib.publication_metric_snapshot s
          WHERE s.release_id=r.release_id AND s.publication_id=ANY(%s::uuid[]))
        ORDER BY indexed_through DESC,exported_on DESC,created_at DESC,release_id LIMIT 1""",
        (publication_ids,)).fetchone()
    rows = connection.execute("""SELECT publication_id,metric_code,numeric_value,value_status,
        source_reference_id,source_publication_year,source_document_type
        FROM smartlib.publication_metric_analysis
        WHERE release_id=%s AND publication_id=ANY(%s::uuid[])""",
        (release['release_id'], publication_ids)).fetchall() if release else []
    context = {'method': METHOD, 'incites_release': dict(release) if release else None,
               'centers_method': 'see-per-community-centers-method'}
    inputs = ([{'source': 'incites', **dict(r)} for r in rows]
              + [{'source': 'journal', **dict(r)} for r in journal_rows])
    # Convert UUID/Decimal/date into stable public JSON values; values parsed explicitly below.
    inputs = json.loads(json.dumps(inputs, default=str))
    inputs.sort(key=lambda r: json.dumps(r, sort_keys=True))
    return json.loads(json.dumps(context, default=str)), inputs


def enrich_assessment(assessment, context, inputs):
    values = defaultdict(lambda: defaultdict(set))
    partitions = defaultdict(lambda: defaultdict(dict))
    for row in inputs:
        pid = str(row['publication_id'])
        if row['source'] == 'incites':
            if row['value_status'] == 'present' and row['numeric_value'] is not None:
                value = float(row['numeric_value'])
                if isfinite(value):
                    values[pid][row['metric_code']].add(value)
        else:
            if row['metric_system'] == 'jcr' and row['impact_factor'] is not None:
                values[pid]['journal.jif'].add(float(row['impact_factor']))
            if row.get('quartile') in ('Q1', 'Q2', 'Q3', 'Q4'):
                # Preserve per-category weight while eliminating duplicate joined records.
                partitions[pid][row['metric_system']][str(row['record_id'])] = row['quartile']
    for community in assessment.communities:
        ids = sorted(set(community.publication_ids))
        community.metrics = []
        for code, label in METRICS.items():
            # Conflicting values are missing/ambiguous, never averaged as extra papers.
            observed = {pid: next(iter(values[pid][code])) for pid in ids
                        if len(values[pid][code]) == 1}
            nums = list(observed.values())
            ref = 1 if code in ('incites.cnci', 'incites.jnci', 'incites.collab_cnci') else None
            community.metrics.append(CommunityMetric(
                code=code, label=label, publication_ids=sorted(observed),
                missing_publication_ids=sorted(set(ids) - observed.keys()), count=len(nums),
                mean=mean(nums) if nums else None, median=median(nums) if nums else None,
                minimum=min(nums) if nums else None, maximum=max(nums) if nums else None,
                total=sum(nums) if nums and code == 'incites.times_cited' else None,
                reference=ref,
                above_reference_count=sum(v > ref for v in nums) if ref is not None and nums else None,
            ))
        community.quartiles = {}
        for system in ('jcr', 'cas_partition'):
            covered = [pid for pid in ids if partitions[pid][system]]
            weights = dict.fromkeys(('Q1', 'Q2', 'Q3', 'Q4'), 0.0)
            for pid in covered:
                qs = list(partitions[pid][system].values())
                for q in qs:
                    weights[q] += 1 / len(qs)
            community.quartiles[system] = CommunityQuartiles(**{
                'publication_ids': covered,
                'missing_publication_ids': sorted(set(ids) - set(covered)),
                'count': len(covered), 'paper_equivalents': weights,
                'shares': {q: w / len(covered) if covered else None for q, w in weights.items()},
            })
    assessment.metric_context = context
    assessment.metric_inputs = inputs
    assessment.metric_input_hash = sha256(json.dumps(
        {'method': METHOD, 'structure': assessment.input_hash, 'context': context, 'inputs': inputs},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return assessment
