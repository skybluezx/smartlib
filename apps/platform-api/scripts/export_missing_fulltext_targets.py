#!/usr/bin/env python3
"""Export import rows that have neither a formal nor a staged full text."""

from __future__ import annotations

import json
import os
import sys

import psycopg
from psycopg.rows import dict_row

QUERY = """
WITH coverage AS (
    SELECT
        item.*,input_record.raw_payload,input_record.normalized_payload,
        submission.representative_work_number,submission.awardee_name_raw,
        COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer) AS source_row_number,
        EXISTS (
            SELECT 1
            FROM smartlib.publication_fulltext_resource resource
            WHERE resource.publication_id = item.matched_publication_id
        ) AS has_formal_fulltext,
        EXISTS (
            SELECT 1
            FROM smartlib.publication_fulltext_preverification pre
            WHERE pre.record_id = item.record_id
              AND pre.preverification_status IN ('ready', 'review_required', 'applied')
              AND pre.storage_state = 'stored'
        ) AS has_staged_fulltext
    FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
)
SELECT
    source_row_number,
    record_id,
    representative_work_number,
    awardee_name_raw,
    raw_payload,
    normalized_payload,
    matched_publication_id,
    verification_state
FROM coverage
WHERE NOT has_formal_fulltext
  AND NOT has_staged_fulltext
ORDER BY source_row_number
"""


def main() -> int:
    database_url = os.environ["SMARTLIB_DATABASE_URL"]
    actor_id = os.environ["SMARTLIB_DEV_ACTOR_ID"]
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('smartlib.actor_id', %s, false)", (actor_id,))
            cursor.execute(QUERY)
            records = cursor.fetchall()
    json.dump(
        {"record_count": len(records), "records": records},
        sys.stdout,
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
