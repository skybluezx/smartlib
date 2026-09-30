import json
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from psycopg.types.json import Jsonb

from smartlib_platform.foundation.database import DbConnection

from .models import (
    PublicationChangeCandidateView,
    PublicationFulltextResourceView,
    PublicationIncrementalStatus,
    PublicationSupplementCreate,
    PublicationSupplementDecisionCommand,
    PublicationSupplementView,
)
from .verification_state import refresh_effective_verification_state

SUPPLEMENT_NAMESPACE = UUID("43b77eb8-c04a-42dd-a5a7-4ab776b48608")

DIRECT_METADATA_FIELDS = {
    "title",
    "subtitle",
    "abstract",
    "journal_name",
    "journal_abbreviation",
    "issn",
    "eissn",
    "publication_year",
    "published_online_at",
    "published_print_at",
    "volume",
    "issue",
    "pages",
    "article_number",
    "publication_type",
    "language_code",
    "publication_status",
}
IDENTITY_FIELDS = {"title", "journal_name", "publication_year"}
LIST_ATTRIBUTE_FIELDS = {
    "keywords",
    "mesh_terms",
    "licenses",
    "fulltext_urls",
    "funders",
    "grants",
}
IDENTIFIER_FIELDS = {"doi", "pmid", "pmcid"}


def _json_safe(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _same(left: object, right: object) -> bool:
    return json.dumps(_json_safe(left), sort_keys=True, ensure_ascii=False) == json.dumps(
        _json_safe(right), sort_keys=True, ensure_ascii=False
    )


def _metadata_row(connection: DbConnection, publication_id: UUID) -> dict[str, Any]:
    row = connection.execute(
        """SELECT metadata.*, object.version AS object_version
            
                 FROM smartlib.publication_metadata metadata
            
                 JOIN smartlib.knowledge_object object ON object.object_id=metadata.publication_id
           
                 WHERE metadata.publication_id=%s
                 AND object.system_to='infinity'::timestamptz
            FOR UPDATE OF metadata, object""",
        (publication_id,),
    ).fetchone()
    if not row:
        raise LookupError("publication not found")
    return dict(row)


def _current_identifiers(connection: DbConnection, publication_id: UUID) -> dict[str, str]:
    rows = connection.execute(
        """SELECT identifier_type, normalized_value
            
                 FROM smartlib.publication_identifier
           
                 WHERE publication_id=%s
                 AND verification_status <> 'rejected'""",
        (publication_id,),
    ).fetchall()
    return {str(row["identifier_type"]): str(row["normalized_value"]) for row in rows}


def _merge_list(current: object, proposed: object) -> list[object]:
    current_items = current if isinstance(current, list) else []
    proposed_items = proposed if isinstance(proposed, list) else [proposed]
    merged: list[object] = []
    fingerprints: set[str] = set()
    for item in [*current_items, *proposed_items]:
        fingerprint = json.dumps(_json_safe(item), sort_keys=True, ensure_ascii=False)
        if fingerprint not in fingerprints:
            merged.append(item)
            fingerprints.add(fingerprint)
    return merged


def _candidate_drafts(
    current: dict[str, Any], identifiers: dict[str, str], command: PublicationSupplementCreate
) -> list[dict[str, object]]:
    incoming = dict(command.metadata)
    if command.fulltext:
        incoming.update(command.fulltext.extracted_metadata)
    attributes = current.get("attributes") if isinstance(current.get("attributes"), dict) else {}
    drafts: list[dict[str, object]] = []

    for field, proposed in incoming.items():
        if proposed in (None, "", []):
            continue
        if field in DIRECT_METADATA_FIELDS:
            existing = current.get(field)
            if _same(existing, proposed):
                drafts.append(
                    {"field_path": field, "current": existing, "proposed": proposed,
                     "change_type": "confirm", "risk": "safe", "status": "auto_applied"}
                )
            elif existing in (None, "") and field not in IDENTITY_FIELDS:
                drafts.append(
                    {"field_path": field, "current": existing, "proposed": proposed,
                     "change_type": "add", "risk": "safe", "status": "auto_applied"}
                )
            else:
                critical = field in IDENTITY_FIELDS or (
                    field == "publication_status" and str(proposed) in {"corrected", "retracted"}
                )
                drafts.append(
                    {"field_path": field, "current": existing, "proposed": proposed,
                     "change_type": "replace", "risk": "critical" if critical else "review",
                     "status": "pending"}
                )
            continue

        existing = attributes.get(field)
        if field in LIST_ATTRIBUTE_FIELDS:
            merged = _merge_list(existing, proposed)
            drafts.append(
                {"field_path": f"attributes.{field}", "current": existing, "proposed": merged,
                 "change_type": "confirm" if _same(existing, merged) else "add",
                 "risk": "safe", "status": "auto_applied"}
            )
        elif _same(existing, proposed):
            drafts.append(
                {"field_path": f"attributes.{field}", "current": existing, "proposed": proposed,
                 "change_type": "confirm", "risk": "safe", "status": "auto_applied"}
            )
        else:
            drafts.append(
                {"field_path": f"attributes.{field}", "current": existing, "proposed": proposed,
                 "change_type": "add" if existing in (None, "") else "replace",
                 "risk": "safe" if existing in (None, "") else "review",
                 "status": "auto_applied" if existing in (None, "") else "pending"}
            )

    for kind, proposed in command.identifiers.model_dump().items():
        if not proposed:
            continue
        existing = identifiers.get(kind)
        drafts.append(
            {"field_path": f"identifiers.{kind}", "current": existing, "proposed": proposed,
             "change_type": "confirm" if _same(existing, proposed) else "add" if not existing else "replace",
             "risk": "safe" if _same(existing, proposed) else "critical",
             "status": "auto_applied" if _same(existing, proposed) else "pending"}
        )

    for index, funding in enumerate(command.funding):
        payload = funding.model_dump(mode="json")
        drafts.append(
            {"field_path": f"funding.{index + 1}", "current": None, "proposed": payload,
             "change_type": "relation_add", "risk": "review", "status": "pending"}
        )

    if command.fulltext:
        drafts.append(
            {"field_path": f"fulltext.{command.fulltext.content_checksum}", "current": None,
             "proposed": command.fulltext.model_dump(mode="json"), "change_type": "add",
             "risk": "safe", "status": "auto_applied"}
        )
    return drafts


def _impact(drafts: list[dict[str, object]]) -> str:
    risks = {draft["risk"] for draft in drafts if draft["status"] == "pending"}
    if "critical" in risks:
        return "critical"
    if "review" in risks:
        return "corrective"
    return "additive"


def _insert_outbox(
    connection: DbConnection, publication_id: UUID, object_version: int, trace_id: str, changed: list[str]
) -> int:
    return connection.execute(
        """INSERT INTO smartlib.outbox_event
                  (event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
             VALUES (%s,'knowledge_object',%s,'knowledge.publication.updated',%s,%s,%s)""",
        (
            uuid4(), publication_id, object_version,
            Jsonb({"object_id": str(publication_id), "version": object_version,
                   "changed_fields": changed}), trace_id,
        ),
    ).rowcount


def _apply_funding_relation(
    connection: DbConnection, publication_id: UUID, evidence_id: UUID, value: object,
    actor_id: UUID, trace_id: str
) -> None:
    if not isinstance(value, dict):
        return
    funder_name = str(value.get("funder_name") or "").strip()
    if not funder_name:
        return
    grant_id = str(value.get("grant_id") or "").strip()
    if not grant_id:
        # A funder name alone cannot identify a project. Retain the original
        # evidence as a matchable clue, without inventing a project or edge.
        connection.execute(
            """UPDATE smartlib.knowledge_object
               SET attributes=jsonb_set(attributes,'{funding_source_clues}',
                   coalesce(attributes->'funding_source_clues','{}'::jsonb) || %s),
                   version=version+1
               WHERE object_id=%s""",
            (Jsonb({str(uuid5(SUPPLEMENT_NAMESPACE, f"funding-clue:{evidence_id}:{funder_name.casefold()}")): {**value, "evidence_id": str(evidence_id),
                    "source": "publication_supplement", "match_state": "project_unresolved"}}),
             publication_id),
        )
        return
    identity = f"{funder_name.casefold()}:{grant_id}"
    target_type = "project"
    predicate = "publication.supported_by_project"
    identity_kind = "funding-project"
    target_id = uuid5(SUPPLEMENT_NAMESPACE, f"{identity_kind}:{identity}")
    connection.execute(
        """INSERT INTO smartlib.knowledge_object
                  (object_id,object_type,canonical_name,description,visibility,quality_state,
                   review_state,attributes,created_by)
             VALUES (%s,%s,%s,%s,'restricted','validated','approved',%s,%s)
            
                 ON CONFLICT (object_id) DO UPDATE SET
                 attributes=smartlib.knowledge_object.attributes || excluded.attributes,
                 version=smartlib.knowledge_object.version+1""",
        (
            target_id, target_type, grant_id or funder_name,
            f"{funder_name}{f' · {grant_id}' if grant_id else ''}",
            Jsonb({**value, "record_kind": "supplement_funding",
                   "source": "publication_supplement",
                   **({"identity_resolution_status": "name_only"} if not grant_id else {})}), actor_id,
        ),
    )
    relation_id = uuid5(SUPPLEMENT_NAMESPACE, f"{predicate}:{publication_id}:{target_id}")
    relation = connection.execute(
        """INSERT INTO smartlib.relation_assertion
                  (relation_id,subject_id,predicate,object_id,fact_class,confidence,visibility,
                   license_tags,review_state,model_version,created_by,attributes)
             VALUES (%s,%s,%s,%s,'human_confirmed',1.0,'restricted',
                     ARRAY['supplemental-evidence'],'approved','publication-supplement-v1',%s,%s)
            
                 ON CONFLICT (relation_id) DO UPDATE
                 SET review_state='approved',
                 fact_class='human_confirmed',confidence=1.0,version=relation_assertion.version+1,
                 attributes=relation_assertion.attributes || excluded.attributes
             RETURNING version""",
        (relation_id, publication_id, predicate, target_id, actor_id,
         Jsonb({"source": "publication_supplement", "funding_source_note": value})),
    ).fetchone()
    connection.execute(
        """INSERT INTO smartlib.relation_evidence (relation_id,evidence_id)
             VALUES (%s,%s)
                 ON CONFLICT DO NOTHING""",
        (relation_id, evidence_id),
    )
    connection.execute(
        """INSERT INTO smartlib.outbox_event
                  (event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
             VALUES (%s,'relation_assertion',%s,'knowledge.relation.updated',%s,%s,%s)""",
        (
            uuid4(), relation_id, int(relation["version"]),
            Jsonb({"relation_id": str(relation_id), "version": int(relation["version"])}), trace_id,
        ),
    )


def _apply_candidates(
    connection: DbConnection, submission_id: UUID, publication_id: UUID, evidence_id: UUID,
    proposal_ids: list[UUID], actor_id: UUID, trace_id: str, decision_reason: str
) -> tuple[int | None, list[str]]:
    if not proposal_ids:
        return None, []
    rows = connection.execute(
        """SELECT *
                 FROM smartlib.change_proposal
           
                 WHERE submission_id=%s
                 AND proposal_id=ANY(%s)
            FOR UPDATE""",
        (submission_id, proposal_ids),
    ).fetchall()
    changed: list[str] = []
    for row in rows:
        path = str(row["field_path"])
        value = row["proposed_value"]
        if row["change_type"] == "confirm":
            continue
        if path in DIRECT_METADATA_FIELDS:
            connection.execute(
                f"UPDATE smartlib.publication_metadata SET {path}=%s WHERE publication_id=%s",
                (value, publication_id),
            )
        elif path.startswith("attributes."):
            key = path.removeprefix("attributes.")
            connection.execute(
                """UPDATE smartlib.publication_metadata
                     
                 SET attributes=jsonb_set(attributes,%s,%s,true)
                   
                 WHERE publication_id=%s""",
                ([key], Jsonb(value), publication_id),
            )
        elif path.startswith("identifiers."):
            kind = path.removeprefix("identifiers.")
            normalized = str(value).strip().upper() if kind == "pmcid" else str(value).strip().lower()
            duplicate = connection.execute(
                """SELECT publication_id
                 FROM smartlib.publication_identifier
                   
                 WHERE identifier_type=%s
                 AND lower(normalized_value)=lower(%s)
                     
                 AND verification_status <> 'rejected' LIMIT 1""",
                (kind, normalized),
            ).fetchone()
            if duplicate and duplicate["publication_id"] != publication_id:
                raise ValueError(f"{kind.upper()} already belongs to another publication")
            connection.execute(
                """UPDATE smartlib.publication_identifier
                 SET verification_status='rejected'
                   
                 WHERE publication_id=%s
                 AND identifier_type=%s
                     
                 AND lower(normalized_value)<>lower(%s)""",
                (publication_id, kind, normalized),
            )
            connection.execute(
                """INSERT INTO smartlib.publication_identifier
                          (publication_identifier_id,publication_id,identifier_type,raw_value,
                           normalized_value,is_primary,verification_status,created_by)
                     VALUES (%s,%s,%s,%s,%s,true,'matched',%s)
                    
                 ON CONFLICT DO NOTHING""",
                (uuid4(), publication_id, kind, str(value), normalized, actor_id),
            )
        elif path.startswith("funding."):
            _apply_funding_relation(
                connection, publication_id, evidence_id, value, actor_id, trace_id
            )
        changed.append(path)
    if not changed:
        return None, []

    updated = connection.execute(
        """UPDATE smartlib.publication_metadata
             
                 SET metadata_version=metadata_version+1,last_enriched_at=clock_timestamp()
           
                 WHERE publication_id=%s RETURNING metadata_version""",
        (publication_id,),
    ).fetchone()
    object_row = connection.execute(
        """UPDATE smartlib.knowledge_object
                 SET version=version+1
           
                 WHERE object_id=%s RETURNING version""",
        (publication_id,),
    ).fetchone()
    metadata_version = int(updated["metadata_version"])
    snapshot = _metadata_row(connection, publication_id)
    connection.execute(
        """INSERT INTO smartlib.publication_metadata_revision
                  (revision_id,publication_id,submission_id,metadata_version,snapshot,
                   changed_fields,change_reason,created_by)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            uuid4(), publication_id, submission_id, metadata_version,
            Jsonb(_json_safe(snapshot)), changed, decision_reason, actor_id,
        ),
    )
    _insert_outbox(connection, publication_id, int(object_row["version"]), trace_id, changed)
    return metadata_version, changed


def _refresh_publication_states(connection: DbConnection, publication_id: UUID) -> None:
    pending = connection.execute(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE candidate.risk_level='critical') AS critical
            
                 FROM smartlib.change_proposal candidate
            
                 JOIN smartlib.change_submission supplement
               ON supplement.submission_id=candidate.submission_id
           
                 WHERE supplement.workflow_key='publication'
                 AND supplement.context_object_id=%s
                 AND candidate.status='pending'""",
        (publication_id,),
    ).fetchone()
    fulltext = connection.execute(
        """SELECT extraction_state
                 FROM smartlib.publication_fulltext_resource
           
                 WHERE publication_id=%s ORDER BY created_at DESC LIMIT 1""",
        (publication_id,),
    ).fetchone()
    fulltext_state = "missing"
    if fulltext:
        fulltext_state = "extracted" if fulltext["extraction_state"] == "extracted" else "registered"
    connection.execute(
        """UPDATE smartlib.publication_metadata SET
               identity_state=%s,enrichment_state=%s,fulltext_state=%s
           
                 WHERE publication_id=%s""",
        (
            "review_required" if pending["critical"] else "verified",
            "review_required" if pending["total"] else "partial",
            fulltext_state,
            publication_id,
        ),
    )
    refresh_effective_verification_state(connection, publication_id=publication_id)


def get_incremental_status(
    connection: DbConnection, publication_id: UUID
) -> PublicationIncrementalStatus | None:
    row = connection.execute(
        """SELECT metadata.publication_id,metadata.metadata_version,metadata.identity_state,
                  metadata.enrichment_state,metadata.fulltext_state,
                  count(supplement.submission_id) FILTER (
                   
                 WHERE supplement.status='needs_review') AS open_supplement_count,
                  max(supplement.created_at) AS latest_supplement_at
            
                 FROM smartlib.publication_metadata metadata
             LEFT
                 JOIN smartlib.change_submission supplement
               ON supplement.context_object_id=metadata.publication_id
                 AND supplement.workflow_key='publication'
           
                 WHERE metadata.publication_id=%s
            GROUP BY metadata.publication_id""",
        (publication_id,),
    ).fetchone()
    return PublicationIncrementalStatus.model_validate(row) if row else None


def _supplement_view(connection: DbConnection, submission_id: UUID) -> PublicationSupplementView:
    supplement = connection.execute(
        """SELECT *,context_object_id AS publication_id
                 FROM smartlib.change_submission
                 WHERE submission_id=%s
                 AND workflow_key='publication'""",
        (submission_id,),
    ).fetchone()
    if not supplement:
        raise LookupError("publication supplement not found")
    candidates = connection.execute(
        """SELECT proposal_id,field_path,current_value,proposed_value,change_type,risk_level,
                  status,decision_reason,application_state,applied_at
            
                 FROM smartlib.change_proposal
           
                 WHERE submission_id=%s ORDER BY created_at,field_path""",
        (submission_id,),
    ).fetchall()
    return PublicationSupplementView(
        **supplement,
        candidates=[PublicationChangeCandidateView.model_validate(row) for row in candidates],
    )


def list_publication_supplements(
    connection: DbConnection, publication_id: UUID
) -> list[PublicationSupplementView]:
    rows = connection.execute(
        """SELECT submission_id
                 FROM smartlib.change_submission
           
                 WHERE workflow_key='publication'
                 AND context_object_id=%s ORDER BY created_at DESC""",
        (publication_id,),
    ).fetchall()
    return [_supplement_view(connection, row["submission_id"]) for row in rows]


def list_publication_fulltexts(
    connection: DbConnection, publication_id: UUID
) -> list[PublicationFulltextResourceView]:
    rows = connection.execute(
        """SELECT fulltext_resource_id,publication_id,submission_id,file_name,storage_uri,
                  content_checksum,mime_type,resource_role,size_bytes,license_tags,extraction_state,
                  extraction_method,extraction_version,extracted_text_uri,page_count,text_length,
                  ocr_page_count,extracted_at,extraction_error,extracted_metadata,created_at,updated_at
            
                 FROM smartlib.publication_fulltext_resource
           
                 WHERE publication_id=%s ORDER BY created_at DESC""",
        (publication_id,),
    ).fetchall()
    return [PublicationFulltextResourceView.model_validate(row) for row in rows]


def promote_staged_fulltext(
    connection: DbConnection,
    *,
    record_id: UUID,
    publication_id: UUID,
    actor_id: UUID,
    trace_id: str,
) -> tuple[UUID | None, bool]:
    """Attach an already-staged and parsed PDF to its approved publication object."""
    staged = connection.execute(
        """SELECT preverification_id,content_checksum,file_name,size_bytes,page_count,
                  text_length,extraction_method,proposed_metadata,proposed_identifiers,checks,
                  rule_version,evaluated_at,storage_uri,extracted_text_uri
            
                 FROM smartlib.publication_fulltext_preverification
           
                 WHERE record_id=%s
                 AND storage_state='stored'
             
                 AND preverification_status NOT IN ('conflict','superseded')
            ORDER BY match_score DESC,evaluated_at DESC LIMIT 1""",
        (record_id,),
    ).fetchone()
    if not staged:
        return None, False

    existing = connection.execute(
        """SELECT fulltext_resource_id
                 FROM smartlib.publication_fulltext_resource
           
                 WHERE publication_id=%s
                 AND content_checksum=%s""",
        (publication_id, staged["content_checksum"]),
    ).fetchone()
    if existing:
        connection.execute(
            """UPDATE smartlib.publication_fulltext_preverification pre
                 
                 SET preverification_status='applied',applied_at=coalesce(applied_at,clock_timestamp())
                
                 FROM (smartlib.publication_intake_record item
                 
                 JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT
                 JOIN smartlib.representative_work_submission submission USING(record_id))
               
                 WHERE pre.record_id=item.record_id
                 
                 AND item.matched_publication_id=%s
                 AND pre.content_checksum=%s
                 
                 AND pre.preverification_status NOT IN ('conflict','superseded')""",
            (publication_id, staged["content_checksum"]),
        )
        connection.execute(
            """UPDATE smartlib.publication_metadata
                 SET fulltext_state='extracted'
                 WHERE publication_id=%s""",
            (publication_id,),
        )
        return existing["fulltext_resource_id"], False

    metadata = connection.execute(
        "SELECT metadata_version FROM smartlib.publication_metadata WHERE publication_id=%s",
        (publication_id,),
    ).fetchone()
    if not metadata:
        raise LookupError("publication metadata not found for staged fulltext promotion")

    checksum = str(staged["content_checksum"])
    evidence_id = uuid5(SUPPLEMENT_NAMESPACE, f"staged-fulltext-evidence:{publication_id}:{checksum}")
    submission_id = uuid5(SUPPLEMENT_NAMESPACE, f"staged-fulltext-supplement:{publication_id}:{checksum}")
    resource_id = uuid5(SUPPLEMENT_NAMESPACE, f"staged-fulltext-resource:{publication_id}:{checksum}")
    provenance = {
        "preverification_id": str(staged["preverification_id"]),
        "rule_version": staged["rule_version"],
        "proposed_metadata": staged["proposed_metadata"],
        "proposed_identifiers": staged["proposed_identifiers"],
        "checks": staged["checks"],
        "trace_id": trace_id,
    }
    connection.execute(
        """INSERT INTO smartlib.evidence_record
                  (evidence_id,object_id,evidence_type,citation,excerpt,visibility,license_tags,
                   content_checksum,metadata,created_by)
             VALUES (%s,%s,'publication',%s,%s,'restricted',%s,%s,%s,%s)
            
                 ON CONFLICT (evidence_id) DO NOTHING""",
        (
            evidence_id,
            publication_id,
            f"全文预核验文件: {staged['file_name']}",
            "论文核验通过后, 将MinIO暂存全文提升为正式论文全文资源。",
            ["controlled-file", "fulltext-preverification"],
            checksum,
            Jsonb({"storage_uri": staged["storage_uri"], **provenance}),
            actor_id,
        ),
    )
    connection.execute(
        """INSERT INTO smartlib.change_submission
                  (submission_id,context_object_id,evidence_id,source_kind,source_label,source_uri,
                   content_checksum,payload,status,impact,base_version,
                   applied_version,decision_reason,decided_by,decided_at,created_by)
             VALUES (%s,%s,%s,'fulltext','全文预核验转正式资源',%s,%s,%s,
                     'auto_applied','additive',%s,%s,%s,%s,clock_timestamp(),%s)
            
                 ON CONFLICT (submission_id) DO NOTHING""",
        (
            submission_id,
            publication_id,
            evidence_id,
            staged["storage_uri"],
            checksum,
            Jsonb(provenance),
            metadata["metadata_version"],
            metadata["metadata_version"],
            "复用已完成完整性、解析和身份预核验的暂存全文。",
            actor_id,
            actor_id,
        ),
    )
    inserted = connection.execute(
        """INSERT INTO smartlib.publication_fulltext_resource
                  (fulltext_resource_id,publication_id,submission_id,file_name,storage_uri,
                   content_checksum,mime_type,size_bytes,license_tags,extraction_state,
                   extraction_method,extraction_version,extracted_text_uri,page_count,text_length,
                   extracted_at,extracted_metadata,created_by)
             VALUES (%s,%s,%s,%s,%s,%s,'application/pdf',%s,%s,'extracted',%s,%s,%s,%s,%s,%s,%s,%s)
            
                 ON CONFLICT (publication_id,content_checksum) DO NOTHING""",
        (
            resource_id,
            publication_id,
            submission_id,
            staged["file_name"],
            staged["storage_uri"],
            checksum,
            staged["size_bytes"],
            ["controlled-file", "fulltext-preverification"],
            staged["extraction_method"],
            staged["rule_version"],
            staged["extracted_text_uri"],
            staged["page_count"],
            staged["text_length"],
            staged["evaluated_at"],
            Jsonb(provenance),
            actor_id,
        ),
    ).rowcount
    connection.execute(
        """UPDATE smartlib.publication_fulltext_preverification pre
             
                 SET preverification_status='applied',applied_at=coalesce(applied_at,clock_timestamp())
            
                 FROM (smartlib.publication_intake_record item
                 
                 JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT
                 JOIN smartlib.representative_work_submission submission USING(record_id))
           
                 WHERE pre.record_id=item.record_id
             
                 AND item.matched_publication_id=%s
                 AND pre.content_checksum=%s
             
                 AND pre.preverification_status NOT IN ('conflict','superseded')""",
        (publication_id, checksum),
    )
    connection.execute(
        """UPDATE smartlib.publication_metadata
                 SET fulltext_state='extracted'
                 WHERE publication_id=%s""",
        (publication_id,),
    )
    if inserted:
        connection.execute(
            """INSERT INTO audit.audit_event
                      (actor_id,action,resource_type,resource_id,decision,trace_id,details)
                 VALUES (%s,'publication.fulltext.promoted','publication_fulltext_resource',%s,
                         'recorded',%s,%s)""",
            (
                actor_id,
                str(resource_id),
                trace_id,
                Jsonb(
                    {
                        "publication_id": str(publication_id),
                        "preverification_id": str(staged["preverification_id"]),
                        "content_checksum": checksum,
                        "storage_uri": staged["storage_uri"],
                    }
                ),
            ),
        )
    return resource_id, bool(inserted)


def submit_publication_supplement(
    connection: DbConnection, publication_id: UUID, command: PublicationSupplementCreate,
    actor_id: UUID, trace_id: str
) -> PublicationSupplementView:
    current = _metadata_row(connection, publication_id)
    identifiers = _current_identifiers(connection, publication_id)
    checksum = command.content_checksum or (
        command.fulltext.content_checksum if command.fulltext else None
    )
    if checksum:
        existing = connection.execute(
            """SELECT submission_id
                 FROM smartlib.change_submission
               
                 WHERE workflow_key='publication'
                 AND context_object_id=%s
                 AND source_kind=%s
                 AND content_checksum=%s""",
            (publication_id, command.source_kind, checksum),
        ).fetchone()
        if existing:
            return _supplement_view(connection, existing["submission_id"])
    drafts = _candidate_drafts(current, identifiers, command)
    if not drafts:
        raise ValueError("supplement contains no usable publication information")

    payload = command.model_dump(mode="json")
    source_uri = command.source_uri or (command.fulltext.storage_uri if command.fulltext else None)
    evidence_id = uuid4()
    license_tags = command.fulltext.license_tags if command.fulltext else ["supplemental-evidence"]
    connection.execute(
        """INSERT INTO smartlib.evidence_record
                  (evidence_id,object_id,evidence_type,citation,excerpt,visibility,license_tags,
                   content_checksum,metadata,created_by)
             VALUES (%s,%s,'publication',%s,%s,'restricted',%s,%s,%s,%s)""",
        (
            evidence_id, publication_id, command.source_label, command.note,
            license_tags, checksum, Jsonb({"source_uri": source_uri, "payload": payload}), actor_id,
        ),
    )
    submission_id = uuid4()
    impact = _impact(drafts)
    initial_status = "needs_review" if any(draft["status"] == "pending" for draft in drafts) else "received"
    connection.execute(
        """INSERT INTO smartlib.change_submission
                  (submission_id,context_object_id,evidence_id,source_kind,source_label,source_uri,
                   content_checksum,payload,status,impact,base_version,created_by)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            submission_id, publication_id, evidence_id, command.source_kind,
            command.source_label, source_uri, checksum, Jsonb(payload), initial_status,
            impact, current["metadata_version"], actor_id,
        ),
    )
    proposal_ids: list[UUID] = []
    for draft in drafts:
        proposal_id = uuid4()
        connection.execute(
            """INSERT INTO smartlib.change_proposal
                      (proposal_id,submission_id,field_path,current_value,proposed_value,
                       change_type,risk_level,status,created_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                proposal_id, submission_id, draft["field_path"], Jsonb(_json_safe(draft["current"])),
                Jsonb(_json_safe(draft["proposed"])), draft["change_type"], draft["risk"],
                draft["status"], actor_id,
            ),
        )
        if draft["status"] == "auto_applied":
            proposal_ids.append(proposal_id)

    if command.fulltext:
        fulltext = command.fulltext
        connection.execute(
            """INSERT INTO smartlib.publication_fulltext_resource
                      (fulltext_resource_id,publication_id,submission_id,file_name,storage_uri,
                       content_checksum,mime_type,resource_role,size_bytes,license_tags,extraction_state,
                       extracted_metadata,created_by)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                uuid4(), publication_id, submission_id, fulltext.file_name, fulltext.storage_uri,
                fulltext.content_checksum, fulltext.mime_type, fulltext.resource_role, fulltext.size_bytes,
                fulltext.license_tags, fulltext.extraction_state,
                Jsonb(fulltext.extracted_metadata), actor_id,
            ),
        )

    version, _ = _apply_candidates(
        connection, submission_id, publication_id, evidence_id, proposal_ids,
        actor_id, trace_id, command.note or f"自动补充: {command.source_label}",
    )
    if initial_status == "received":
        initial_status = "auto_applied"
    connection.execute(
        """UPDATE smartlib.change_submission
             
                 SET status=%s,applied_version=%s
                 WHERE submission_id=%s""",
        (initial_status, version, submission_id),
    )
    if version is not None:
        connection.execute("""UPDATE smartlib.change_proposal
                 SET base_version=%s
                 WHERE submission_id=%s
                 AND status='pending'""",
                           (version, submission_id))
    _refresh_publication_states(connection, publication_id)
    connection.execute(
        """INSERT INTO audit.audit_event
                  (actor_id,action,resource_type,resource_id,decision,trace_id,details)
             VALUES (%s,'publication.supplement.submitted','publication_supplement',%s,
                     'recorded',%s,%s)""",
        (
            actor_id, str(submission_id), trace_id,
            Jsonb({"publication_id": str(publication_id), "source_kind": command.source_kind,
                   "impact": impact, "status": initial_status}),
        ),
    )
    return _supplement_view(connection, submission_id)


def decide_publication_supplement(
    connection: DbConnection, submission_id: UUID, command: PublicationSupplementDecisionCommand,
    actor_id: UUID, trace_id: str
) -> PublicationSupplementView:
    supplement = connection.execute(
        """SELECT *,context_object_id AS publication_id
                 FROM smartlib.change_submission
                 WHERE submission_id=%s
                 AND workflow_key='publication' FOR UPDATE""",
        (submission_id,),
    ).fetchone()
    if not supplement:
        raise LookupError("publication supplement not found")
    if supplement["status"] != "needs_review":
        raise ValueError(f"supplement is already {supplement['status']}")
    pending = connection.execute(
        """SELECT proposal_id
                 FROM smartlib.change_proposal
           
                 WHERE submission_id=%s
                 AND status='pending' FOR UPDATE""",
        (submission_id,),
    ).fetchall()
    pending_ids = {row["proposal_id"] for row in pending}
    selected_ids = set(command.proposal_ids) if command.proposal_ids else pending_ids
    if not selected_ids or not selected_ids <= pending_ids:
        raise ValueError("candidate selection is empty or contains unavailable changes")

    version: int | None = None
    if command.decision == "accept":
        current_version = _metadata_row(connection, supplement["publication_id"])["metadata_version"]
        stale = connection.execute(
            """SELECT 1
                 FROM smartlib.change_proposal
                 WHERE submission_id=%s
                
                 AND proposal_id=ANY(%s)
                 AND base_version<>%s LIMIT 1""",
            (submission_id, list(selected_ids), current_version),
        ).fetchone()
        if stale:
            connection.execute(
                """UPDATE smartlib.change_proposal
                 SET application_state='conflict',
                     decision_reason='论文版本已变化。请基于当前信息重新提交。'
                    
                 WHERE submission_id=%s
                 AND proposal_id=ANY(%s)""",
                (submission_id, list(selected_ids)),
            )
            return _supplement_view(connection, submission_id)

        version, _ = _apply_candidates(
            connection, submission_id, supplement["publication_id"], supplement["evidence_id"],
            list(selected_ids), actor_id, trace_id, command.reason,
        )
        candidate_status = "accepted"
    else:
        candidate_status = "rejected"
    connection.execute(
        """UPDATE smartlib.change_proposal
             
                 SET status=%s,decision_reason=%s,decided_by=%s,decided_at=clock_timestamp()
           
                 WHERE submission_id=%s
                 AND proposal_id=ANY(%s)""",
        (candidate_status, command.reason, actor_id, submission_id, list(selected_ids)),
    )
    remaining = connection.execute(
        """SELECT count(*) AS total
                 FROM smartlib.change_proposal
           
                 WHERE submission_id=%s
                 AND status='pending'""",
        (submission_id,),
    ).fetchone()["total"]
    if remaining:
        status = "needs_review"
    else:
        accepted = connection.execute(
            """SELECT count(*) AS total
                 FROM smartlib.change_proposal
               
                 WHERE submission_id=%s
                 AND status IN ('accepted','auto_applied')""",
            (submission_id,),
        ).fetchone()["total"]
        status = "accepted" if accepted else "rejected"
    connection.execute(
        """UPDATE smartlib.change_submission
                 SET status=%s,
               applied_version=COALESCE(%s,applied_version),decision_reason=%s,
               decided_by=%s,decided_at=clock_timestamp()
           
                 WHERE submission_id=%s""",
        (status, version, command.reason, actor_id, submission_id),
    )
    if version is not None:
        connection.execute("""UPDATE smartlib.change_proposal
                 SET base_version=%s
                 WHERE submission_id=%s
                 AND status='pending'""",
                           (version, submission_id))
    _refresh_publication_states(connection, supplement["publication_id"])
    connection.execute(
        """INSERT INTO audit.audit_event
                  (actor_id,action,resource_type,resource_id,decision,trace_id,details)
             VALUES (%s,'publication.supplement.decided','publication_supplement',%s,
                     'recorded',%s,%s)""",
        (
            actor_id, str(submission_id), trace_id,
            Jsonb({"decision": command.decision, "proposal_ids": [str(value) for value in selected_ids],
                   "reason": command.reason, "status": status}),
        ),
    )
    return _supplement_view(connection, submission_id)
