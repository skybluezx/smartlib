"""Release-scoped metrics: never mix vintages or multiply papers through joins."""
from uuid import UUID

from smartlib_platform.foundation.database import DbConnection


def metric_releases(connection: DbConnection) -> list[dict]:
    return connection.execute("SELECT * FROM smartlib.publication_metric_release ORDER BY indexed_through DESC,exported_on DESC,created_at DESC").fetchall()


def publication_metrics(connection: DbConnection, publication_id: UUID, release_id: UUID) -> list[dict]:
    return connection.execute("""SELECT a.*,d.label,d.definition,d.definition_version,d.documentation_url,
        r.exported_on,r.dataset_updated_on,r.indexed_through,r.context,
        s.source_row,s.raw_fields->>'DOI' AS source_doi
        FROM smartlib.publication_metric_analysis a JOIN smartlib.publication_metric_definition d USING(metric_code)
        JOIN smartlib.publication_metric_release r USING(release_id)
        JOIN smartlib.publication_metric_snapshot s USING(release_id,publication_id)
        WHERE a.publication_id=%s AND a.release_id=%s ORDER BY metric_code""",(publication_id,release_id)).fetchall()


def metric_summary(connection: DbConnection, release_id: UUID, publication_ids: list[UUID] | None) -> dict:
    # ANY eliminates repeated requested IDs. No author/funding join can multiply rows.
    scope = connection.execute("""SELECT publication_id FROM smartlib.publication_metadata
        WHERE (%s::uuid[] IS NULL OR publication_id=ANY(%s::uuid[]))""",(publication_ids,publication_ids)).fetchall()
    ids=[r['publication_id'] for r in scope]
    release=connection.execute("SELECT release_id,exported_on,indexed_through,dataset_updated_on,context FROM smartlib.publication_metric_release WHERE release_id=%s AND release_state='validated'",(release_id,)).fetchone()
    if release is None:
        raise ValueError('validated metric release not found')
    metrics=connection.execute("""SELECT d.metric_code,d.label,d.semantic_level,d.unit,d.aggregation_rule,
        count(a.publication_id)::integer AS source_papers,
        count(a.numeric_value)::integer AS value_papers,
        count(*) FILTER(WHERE a.numeric_value=0)::integer AS zero_papers,
        count(*) FILTER(WHERE a.value_status='source_blank')::integer AS source_blank_papers,
        CASE WHEN d.aggregation_rule='sum_and_mean' THEN sum(a.numeric_value) END AS sum_value,
        CASE WHEN d.aggregation_rule IN ('sum_and_mean','mean') THEN avg(a.numeric_value) END AS mean_value,
        percentile_cont(0.5) WITHIN GROUP(ORDER BY a.numeric_value) AS median_value,
        min(a.numeric_value) AS min_value,max(a.numeric_value) AS max_value
        FROM smartlib.publication_metric_definition d LEFT JOIN smartlib.publication_metric_analysis a
        ON a.metric_code=d.metric_code AND a.release_id=%s AND a.publication_id=ANY(%s::uuid[])
        WHERE d.metric_code IN (SELECT unnest(expected_metric_codes) FROM smartlib.publication_metric_release WHERE release_id=%s)
        GROUP BY d.metric_code ORDER BY d.metric_code""",(release_id,ids,release_id)).fetchall()
    for m in metrics:
        m['uncovered_papers']=len(ids)-m['source_papers']
        m['coverage_rate']=m['value_papers']/len(ids) if ids else None
    return {'release':release,'scope_papers':len(ids),'counting_rule':'distinct publication; fixed release; missing excluded from mean, never zero-filled','metrics':metrics}
