"""Leader-facing summaries use the SAME paper admission and RLS as graph analytics."""

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from smartlib_platform.graph_analytics.service import _scoped_publication_ids


def paper_ids(connection, scope, custom_ids=None):
    return _scoped_publication_ids(
        connection,
        start_year=scope.start_year,
        end_year=scope.end_year,
        organization_ids=[scope.organization_id] if scope.organization_id else [],
        project_kind_ids=[],
        scholar_ids=[],
        custom_publication_ids=custom_ids,
    )


def aggregate(papers, authors, affiliations):
    """Dedup at paper/person grain, never infer personnel membership from signatures."""
    people, orgs, years = {}, {}, defaultdict(set)
    valid_ids = {str(p["object_id"]) for p in papers}
    author_pairs = set()
    for a in authors:
        pid, sid = str(a["publication_id"]), str(a["object_id"])
        if pid not in valid_ids:
            continue
        author_pairs.add((sid, pid))
        person = people.setdefault(
            sid, {"object_id": sid, "name": a["name"], "papers": set(), "organizations": set()}
        )
        person["papers"].add(pid)
    for a in affiliations:
        sid, pid, oid = str(a["person_id"]), str(a["publication_id"]), str(a["object_id"])
        if (sid, pid) not in author_pairs:
            continue
        people[sid]["organizations"].add(a["name"])
        org = orgs.setdefault(oid, {"object_id": oid, "name": a["name"], "papers": set(), "scholars": set()})
        org["papers"].add(pid)
        org["scholars"].add(sid)
    for p in papers:
        years[p["year"]].add(str(p["object_id"]))

    def serialize(rows):
        return sorted(
            [
                {
                    **r,
                    "papers": sorted(r["papers"]),
                    **(
                        {"organizations": sorted(r["organizations"])}
                        if "organizations" in r
                        else {"scholar_count": len(r["scholars"])}
                    ),
                }
                for r in rows.values()
            ],
            key=lambda r: (-len(r["papers"]), r["name"], r["object_id"]),
        )

    organization_rows = serialize(orgs)
    for row in organization_rows:
        row.pop("scholars", None)
    return {
        "scholars": serialize(people),
        "organizations": organization_rows,
        "years": [
            {"year": y, "count": len(v), "publication_ids": sorted(v)}
            for y, v in sorted(years.items(), key=lambda x: x[0] or 0)
        ],
        "coverage": {
            "publications": len(valid_ids),
            "scholars": len(people),
            "organizations": len(orgs),
            "with_authors": len({pid for _, pid in author_pairs}),
            "with_affiliations": len(set().union(*(r["papers"] for r in orgs.values()))) if orgs else 0,
            "missing_year": len(years.get(None, set())),
        },
    }


def dashboard(connection, scope, ids, scope_name=None):
    papers = connection.execute(
        """SELECT o.object_id,o.canonical_name title,o.version,
      COALESCE(m.publication_year,CASE WHEN o.attributes->>'year' ~ '^[0-9]{4}$'
        THEN (o.attributes->>'year')::integer END) AS "year",m.journal_name
      FROM smartlib.knowledge_object o LEFT JOIN smartlib.publication_metadata m ON m.publication_id=o.object_id
      WHERE o.object_id=ANY(%s::uuid[]) ORDER BY "year" DESC NULLS LAST,title,o.object_id""",
        (ids,),
    ).fetchall()
    authors = connection.execute(
        """SELECT p.object_id,p.canonical_name name,r.object_id publication_id
      FROM smartlib.analysis_relation r JOIN smartlib.knowledge_object p ON p.object_id=r.subject_id
      WHERE r.predicate='person.authored' AND r.object_id=ANY(%s::uuid[])
      AND r.system_to='infinity' AND p.system_to='infinity'
      AND smartlib.analysis_state_eligible(r.review_state) AND smartlib.analysis_state_eligible(p.review_state)""",
        (ids,),
    ).fetchall()
    affiliations = connection.execute(
        """SELECT o.object_id,o.canonical_name name,r.subject_id person_id,
      coalesce(r.context_object_id,CASE WHEN r.attributes->>'publication_id'
        ~ '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$'
        THEN (r.attributes->>'publication_id')::uuid END) publication_id
      FROM smartlib.analysis_relation r JOIN smartlib.knowledge_object o ON o.object_id=r.object_id
      WHERE r.predicate='person.affiliated_with' AND r.system_to='infinity' AND o.system_to='infinity'
      AND smartlib.analysis_state_eligible(r.review_state) AND smartlib.analysis_state_eligible(o.review_state)
      AND coalesce(r.context_object_id,CASE WHEN r.attributes->>'publication_id'
        ~ '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$'
        THEN (r.attributes->>'publication_id')::uuid END)=ANY(%s::uuid[])""",
        (ids,),
    ).fetchall()
    sources = connection.execute(
        """SELECT DISTINCT s.name FROM smartlib.source_reference r
      JOIN smartlib.source_system s USING(source_system_id) WHERE r.object_id=ANY(%s::uuid[]) ORDER BY s.name""",
        (ids,),
    ).fetchall()
    return {
        **aggregate(papers, authors, affiliations),
        "papers": papers,
        "scope": scope.model_dump(mode="json"),
        "scope_name": scope_name or "当前可访问论文",
        "sources": [r["name"] for r in sources],
        "generated_at": datetime.now(UTC),
        "method_version": "leadership-summary-v1",
        "boundary": "当前可访问样本，不代表全校完整成果或在岗人员；论文署名机构不等同于人事归属。",
        "analysis_policy": "pending+approved; rejected+superseded excluded",
    }


def resources(connection):
    # Do not expose credentials, private license material or fake subscriptions.
    return connection.execute("""SELECT a.data_asset_id object_id,a.name,a.asset_type,a.lifecycle_state,
        a.description,a.updated_at,
        count(g.license_grant_id)::integer license_count,
        count(g.license_grant_id) FILTER (WHERE g.authorization_state='approved'
          AND g.valid_from<=clock_timestamp() AND g.valid_to>clock_timestamp())::integer effective_licenses
      FROM smartlib.data_asset a LEFT JOIN smartlib.license_grant g USING(data_asset_id)
      WHERE NOT a.synthetic GROUP BY a.data_asset_id ORDER BY a.name""").fetchall()


def list_records(connection, kind):
    return connection.execute(
        """SELECT record_id,kind,category,title,created_at,supersedes_id,result_hash,
      CASE WHEN kind='matter' THEN payload ELSE jsonb_build_object('scope',payload->'scope',
        'publication_count',payload->'summary'->'coverage'->'publications') END payload
      FROM smartlib.leadership_record WHERE kind=%s ORDER BY created_at DESC,record_id DESC LIMIT 1000""",
        (kind,),
    ).fetchall()


def get_record(connection, record_id):
    row = connection.execute(
        "SELECT * FROM smartlib.leadership_record WHERE record_id=%s", (record_id,)
    ).fetchone()
    if not row:
        raise LookupError("记录不存在或当前无权访问")
    return row


def save_matter(connection, command, actor):
    if command.supersedes_id:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(command.supersedes_id),)
        )
        previous = connection.execute(
            "SELECT * FROM smartlib.leadership_record WHERE record_id=%s", (command.supersedes_id,)
        ).fetchone()
        if not previous or previous["kind"] != "matter" or previous["category"] != command.category:
            raise ValueError("仅可修订本人可见的同类事项")
        if connection.execute(
            "SELECT 1 FROM smartlib.leadership_record WHERE supersedes_id=%s", (command.supersedes_id,)
        ).fetchone():
            raise ValueError("事项已被修订，请刷新后重试")
    ids = list(set(command.object_ids))
    visible = connection.execute(
        "SELECT object_id FROM smartlib.knowledge_object WHERE object_id=ANY(%s::uuid[])", (ids,)
    ).fetchall()
    if len(visible) != len(ids):
        raise ValueError("关联对象不存在或无权读取")
    return connection.execute(
        """INSERT INTO smartlib.leadership_record
       (kind,category,title,payload,object_ids,created_by,supersedes_id)
       VALUES ('matter',%s,%s,%s,%s,%s,%s) RETURNING record_id,created_at""",
        (
            command.category,
            command.title,
            Jsonb(command.model_dump(mode="json")),
            ids,
            actor,
            command.supersedes_id,
        ),
    ).fetchone()


def save_report(connection, command, actor, summary, journals):
    payload = json.loads(
        json.dumps(
            {
                "scope": command.scope.model_dump(mode="json"),
                "summary": summary,
                "journals": journals.model_dump(mode="json") if journals else None,
            },
            default=str,
        )
    )
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    ids = sorted(
        {str(p["object_id"]) for p in summary["papers"]}
        | {p["object_id"] for p in summary["scholars"]}
        | {o["object_id"] for o in summary["organizations"]}
    )
    return connection.execute(
        """INSERT INTO smartlib.leadership_record
      (kind,category,title,payload,object_ids,created_by,result_hash)
      VALUES ('report','overview',%s,%s,%s::uuid[],%s,%s) RETURNING record_id,created_at,result_hash""",
        (command.title, Jsonb(payload), ids, actor, digest),
    ).fetchone()
