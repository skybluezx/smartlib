"""Fixed, permission-scoped queries. Never expose source credentials or arbitrary JSON."""

from psycopg import sql

QUERIES = {
    "domains": """SELECT d.governance_domain_id id,d.code,d.name,d.description,d.visibility,d.updated_at,
    (SELECT count(*) FROM smartlib.data_asset a WHERE a.governance_domain_id=d.governance_domain_id) assets
    FROM smartlib.governance_domain d""",
    "sources": """SELECT source_system_id id,code,name,owner_department,source_type,
    authorization_state state,update_schedule,version,updated_at FROM smartlib.source_system""",
    "resources": """SELECT a.data_asset_id id,a.code,a.name,a.asset_type,a.lifecycle_state state,
    a.description,a.synthetic,a.visibility,s.name source_name,d.name domain_name,a.updated_at,
    a.source_system_id,a.governance_domain_id FROM smartlib.data_asset a
    JOIN smartlib.source_system s USING(source_system_id)
    JOIN smartlib.governance_domain d USING(governance_domain_id)""",
    "licenses": """SELECT g.license_grant_id id,a.name,g.license_name,g.license_reference,
    g.authorization_state state,g.allowed_content,g.allowed_purposes,g.prohibited_purposes,
    g.valid_from::text valid_from,g.valid_to::text valid_to,g.synthetic,g.updated_at,
    CASE WHEN g.authorization_state<>'approved' THEN 'not_authorized'
      WHEN g.valid_from>clock_timestamp() THEN 'not_yet_valid'
      WHEN g.valid_to<=clock_timestamp() THEN 'expired' ELSE 'effective' END effective_state
    FROM smartlib.license_grant g JOIN smartlib.data_asset a USING(data_asset_id)""",
    "rules": """SELECT r.quality_rule_id id,r.code,r.name,a.name asset_name,r.rule_kind,
    r.severity,CASE WHEN r.enabled THEN 'active' ELSE 'paused' END state,r.updated_at,
    r.rule_definition->>'field' field,r.rule_definition->>'engine' engine,
    (SELECT run_state FROM smartlib.quality_run qr WHERE qr.quality_rule_id=r.quality_rule_id
      ORDER BY started_at DESC LIMIT 1) last_result
    FROM smartlib.quality_rule r JOIN smartlib.data_asset a USING(data_asset_id)""",
    "governance": """SELECT i.quality_issue_id id,i.title name,a.name asset_name,i.severity,
    i.issue_state state,i.description,i.resolution,i.requires_human_confirmation,i.updated_at
    FROM smartlib.quality_issue i JOIN smartlib.data_asset a USING(data_asset_id)""",
    "metadata": """SELECT f.data_schema_field_id id,a.name,v.version_number,v.schema_version,
    f.field_path,f.data_type,f.nullable,f.classification,f.description,f.created_at updated_at
    FROM smartlib.data_schema_field f JOIN smartlib.data_asset_version v USING(data_asset_version_id)
    JOIN smartlib.data_asset a USING(data_asset_id)""",
    "library": """SELECT record_id id,metric_code,metric_name name,period,organization,value,unit,
    source_reference,note,version,updated_at FROM smartlib.library_metric_record""",
    "applications": """SELECT application_id id,code,name,description,entry_path,owner_department,
    lifecycle_state state,version,updated_at FROM smartlib.hub_application""",
    "settings": """SELECT setting_id id,code,value,version,updated_at FROM smartlib.hub_setting""",
    "jobs": """SELECT b.batch_id id,b.dataset_version name,b.batch_state state,b.expected_item_count,
    b.pipeline_key,b.source_kind,b.processing_rule_version,b.created_at,b.updated_at,
    (SELECT count(*) FROM smartlib.ingestion_record r WHERE r.batch_id=b.batch_id) actual_records
    FROM smartlib.ingestion_batch b""",
    "audit": """SELECT event_id id,occurred_at updated_at,action name,resource_type,resource_id,decision state
    FROM smartlib.list_actor_audit_events(100)""",
    "access": """SELECT r.role_id id,r.name,r.code,r.description,a.valid_from::text valid_from,
    a.valid_to::text valid_to,a.assigned_at updated_at FROM smartlib.actor_role_assignment a
    JOIN smartlib.access_role r USING(role_id) WHERE a.actor_id=smartlib.current_actor_id()""",
    "journals": """SELECT release_id id,release_label name,metric_system,metric_year,edition_year,
    release_state state,authority_status,created_at updated_at FROM smartlib.journal_metric_release""",
}


def table(connection, section, query="", page=1, page_size=25):
    if section not in QUERIES:
        raise LookupError("工作区不存在")
    inner = sql.SQL(QUERIES[section])
    # Search only the explicit safe projection, never hidden/source metadata.
    where = sql.SQL(" WHERE strpos(lower(row_to_json(view)::text),lower(%s))>0")
    count = connection.execute(
        sql.SQL("SELECT count(*) total FROM ({}) view").format(inner) + where, (query,)
    ).fetchone()["total"]
    rows = connection.execute(
        sql.SQL("SELECT * FROM ({}) view").format(inner)
        + where
        + sql.SQL(" ORDER BY updated_at DESC,id LIMIT %s OFFSET %s"),
        (query, page_size, (page - 1) * page_size),
    ).fetchall()
    return {"items": rows, "total": count, "page": page, "page_size": page_size}


def options(connection):
    return {
        "sources": connection.execute(
            "SELECT source_system_id id,name FROM smartlib.source_system ORDER BY name"
        ).fetchall(),
        "domains": connection.execute(
            "SELECT governance_domain_id id,name FROM smartlib.governance_domain ORDER BY name"
        ).fetchall(),
        "assets": connection.execute("""SELECT a.data_asset_id id,a.name,
          COALESCE((SELECT max(version_number) FROM smartlib.data_asset_version v WHERE v.data_asset_id=a.data_asset_id),0) version
          FROM smartlib.data_asset a ORDER BY a.name""").fetchall(),
    }
