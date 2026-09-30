"""Receive input without asserting identity, verification, or publication approval."""

import hashlib
import json
from uuid import UUID

from psycopg.types.json import Jsonb

from smartlib_platform.foundation.database import DbConnection

from .models import IngestionCreate, IngestionResult


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def receive_batch(connection: DbConnection, command: IngestionCreate, actor_id: UUID) -> IngestionResult:
    fingerprint = _digest(command.model_dump(mode="json"))
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (command.dataset_version,))
    existing = connection.execute(
        "SELECT batch_id,metadata FROM smartlib.ingestion_batch WHERE dataset_version=%s",
        (command.dataset_version,),
    ).fetchone()
    if existing:
        if existing["metadata"].get("request_fingerprint") != fingerprint:
            raise ValueError("dataset_version already exists with different input")
        rows = connection.execute(
            "SELECT record_id FROM smartlib.ingestion_record WHERE batch_id=%s ORDER BY source_record_key",
            (existing["batch_id"],),
        ).fetchall()
        return IngestionResult(
            batch_id=existing["batch_id"], record_ids=[r["record_id"] for r in rows], reused=True
        )
    batch = connection.execute(
        """INSERT INTO smartlib.ingestion_batch(source_system_id,dataset_version,source_kind,pipeline_key,
           source_uri,source_checksum,source_locator,expected_item_count,batch_state,metadata,created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'imported',%s,%s) RETURNING batch_id""",
        (
            command.source_system_id,
            command.dataset_version,
            command.source_kind,
            command.pipeline_key,
            command.source_uri,
            command.source_checksum,
            Jsonb(command.source_locator),
            len(command.records),
            Jsonb({"request_fingerprint": fingerprint}),
            actor_id,
        ),
    ).fetchone()
    record_ids = []
    for record in sorted(command.records, key=lambda r: r.source_record_key):
        row = connection.execute(
            """INSERT INTO smartlib.ingestion_record(batch_id,source_record_key,record_kind,source_locator,
               raw_payload,payload_checksum,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING record_id""",
            (
                batch["batch_id"],
                record.source_record_key,
                record.record_kind,
                Jsonb(record.source_locator),
                Jsonb(record.raw_payload),
                _digest(record.raw_payload),
                actor_id,
            ),
        ).fetchone()
        record_ids.append(row["record_id"])
    return IngestionResult(batch_id=batch["batch_id"], record_ids=record_ids)
