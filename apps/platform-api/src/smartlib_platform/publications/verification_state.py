from uuid import UUID

from smartlib_platform.foundation.database import DbConnection


def effective_verification_state(row: dict[str, object]) -> str | None:
    if row["verification_state"] in {"rejected", "superseded"}:
        return str(row["verification_state"])
    if row["has_blocking_conflict"] or row["fulltext_status"] == "conflict":
        return "verification_conflict"
    if (
        not row["has_blocking_layers"]
        or row["has_blocking_open"]
        or row["identity_state"] == "review_required"
        or row["fulltext_status"] == "review_required"
    ):
        return "reverification_required"
    if row.get("has_human_correction"):
        return "corrected"
    if row["current_decision"] in {"auto_verified", "human_verified", "corrected"}:
        return str(row["current_decision"])
    return None


def refresh_effective_verification_state(
    connection: DbConnection,
    *,
    record_id: UUID | None = None,
    publication_id: UUID | None = None,
) -> None:
    if not record_id and not publication_id:
        raise ValueError("record_id or publication_id is required")
    clause = "item.record_id=%s" if record_id else "item.matched_publication_id=%s"
    selected_id = record_id or publication_id
    rows = connection.execute(
        f"""SELECT item.record_id,item.verification_state,item.matched_publication_id,
                   decision.decision AS current_decision,
                   metadata.identity_state,
                   EXISTS (
                     SELECT 1
                       FROM smartlib.change_proposal candidate
                       JOIN smartlib.change_submission supplement
                         ON supplement.submission_id=candidate.submission_id
                      WHERE supplement.context_object_id=item.matched_publication_id
                        AND candidate.risk_level='critical' AND candidate.status='accepted'
                   ) AS has_human_correction,
                   EXISTS (
                     SELECT 1 FROM smartlib.publication_verification_layer layer
                      WHERE layer.record_id=item.record_id AND layer.is_blocking
                   ) AS has_blocking_layers,
                   EXISTS (
                     SELECT 1 FROM smartlib.publication_verification_layer layer
                      WHERE layer.record_id=item.record_id AND layer.is_blocking
                        AND layer.layer_status='conflict'
                   ) AS has_blocking_conflict,
                   EXISTS (
                     SELECT 1 FROM smartlib.publication_verification_layer layer
                      WHERE layer.record_id=item.record_id AND layer.is_blocking
                        AND layer.layer_status IN ('pending','incomplete')
                   ) AS has_blocking_open,
                   (SELECT pre.preverification_status
                      FROM smartlib.publication_fulltext_preverification pre
                     WHERE pre.record_id=item.record_id
                       AND pre.preverification_status <> 'superseded'
                     ORDER BY pre.evaluated_at DESC LIMIT 1) AS fulltext_status
              FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
              LEFT JOIN smartlib.publication_verification_decision decision
                ON decision.record_id=item.record_id AND decision.is_current
              LEFT JOIN smartlib.publication_metadata metadata
                ON metadata.publication_id=item.matched_publication_id
             WHERE {clause}""",
        (selected_id,),
    ).fetchall()
    for row in rows:
        target = effective_verification_state(row)
        if target is None:
            continue
        if target != row["verification_state"]:
            connection.execute(
                "UPDATE smartlib.publication_intake_record SET verification_state=%s WHERE record_id=%s",
                (target, row["record_id"]),
            )
