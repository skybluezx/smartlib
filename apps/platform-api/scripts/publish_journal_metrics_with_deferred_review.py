#!/usr/bin/env python3
"""Publish all usable journal-metric editions and create post-publication reviews.

The database permits one published release per metric system and edition. For
JCR edition 2025, the 22,249-row release is selected over the 13,539-row
alternate; the alternate remains preserved as superseded evidence.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


ACTOR_ID = UUID(os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001"))
AUDIT_EVENT_ID = UUID("ee1f3fbe-d2a8-5987-957f-c9cbd5e52a6c")
SOURCE_CODES = ("user_journal_partition_workbook", "jcr_workbook_intake")

PUBLISHED_RELEASE_IDS = (
    UUID("bbb3e60f-9fd2-5423-8fac-b2745e0957ed"),
    UUID("ca8aa586-556d-5a04-96fe-00d325066acd"),
    UUID("af0ee566-221f-587f-8f93-26a63e0bd03c"),
    UUID("f29918e9-cadb-5c8f-bd76-06f086b50857"),
    UUID("3d7e44f1-b2b1-5e06-991b-4ca11e62fb43"),
    UUID("dcef0e56-7c9e-5379-a76e-665c434ee451"),
    UUID("253ff8f1-62de-50a8-9028-58510b848535"),
    UUID("50ab1e74-8f18-5e79-af64-9887741ae853"),
    UUID("77ab07be-9d72-55a3-9776-2e3b2ed6bc9e"),
    UUID("66891895-9696-570f-a045-2497b03887c4"),
    UUID("7746ddcc-9194-5731-aaf1-a2e4628a8280"),
    UUID("31d8f3f1-c3c2-56da-a41e-8d255222b044"),
    UUID("6bfb38bc-b4e3-58bd-80e9-03df49ab7d79"),
    UUID("fc79f17f-be57-5af3-9b96-32cd3b2210e8"),
    UUID("102b5d40-d926-574e-81ce-5c9b87afde49"),
    UUID("6d99495b-f278-5c2e-9630-a3dbe2379f29"),
)
SUPERSEDED_RELEASE_ID = UUID("3a338391-7fba-559f-a7a9-0381621aeefb")


def current_inventory(connection: psycopg.Connection) -> list[dict]:
    return connection.execute(
        """SELECT release.release_id, release.metric_system, release.edition_year,
                  release.metric_year, release.release_label, release.release_state,
                  release.authority_status, release.expected_record_count,
                  count(record.record_id)::integer AS actual_record_count,
                  asset.data_asset_id, source.code AS source_code,
                  source.authorization_state AS source_authorization_state,
                  license.authorization_state AS license_authorization_state
             FROM smartlib.journal_metric_release release
             JOIN smartlib.data_asset_version version
               ON version.data_asset_version_id=release.data_asset_version_id
             JOIN smartlib.data_asset asset ON asset.data_asset_id=version.data_asset_id
             JOIN smartlib.source_system source ON source.source_system_id=asset.source_system_id
             JOIN smartlib.license_grant license ON license.data_asset_id=asset.data_asset_id
             LEFT JOIN smartlib.journal_metric_record record ON record.release_id=release.release_id
            WHERE source.code=ANY(%s)
            GROUP BY release.release_id,asset.data_asset_id,source.code,
                     source.authorization_state,license.authorization_state
            ORDER BY release.metric_system,release.edition_year,release.created_at""",
        (list(SOURCE_CODES),),
    ).fetchall()


def validate_inventory(rows: list[dict]) -> None:
    by_id = {row["release_id"]: row for row in rows}
    expected_ids = set(PUBLISHED_RELEASE_IDS) | {SUPERSEDED_RELEASE_ID}
    if set(by_id) != expected_ids:
        missing = sorted(str(item) for item in expected_ids - set(by_id))
        unexpected = sorted(str(item) for item in set(by_id) - expected_ids)
        raise ValueError(f"release inventory changed; missing={missing}, unexpected={unexpected}")
    for row in rows:
        if row["actual_record_count"] != row["expected_record_count"]:
            raise ValueError(
                f"record count mismatch for {row['release_id']}: "
                f"{row['actual_record_count']}/{row['expected_record_count']}"
            )
    active_keys = [
        (by_id[release_id]["metric_system"], by_id[release_id]["edition_year"])
        for release_id in PUBLISHED_RELEASE_IDS
    ]
    if len(active_keys) != len(set(active_keys)):
        raise ValueError("more than one selected release for the same metric system and edition")


def plan(connection: psycopg.Connection) -> dict:
    rows = current_inventory(connection)
    validate_inventory(rows)
    by_id = {row["release_id"]: row for row in rows}
    return {
        "status": "validated",
        "database_write_state": "preview_only_not_applied",
        "selected_release_count": len(PUBLISHED_RELEASE_IDS),
        "selected_record_count": sum(by_id[item]["actual_record_count"] for item in PUBLISHED_RELEASE_IDS),
        "superseded_release_id": str(SUPERSEDED_RELEASE_ID),
        "superseded_record_count": by_id[SUPERSEDED_RELEASE_ID]["actual_record_count"],
        "post_publication_review_task_count": len(rows),
        "policy": "publish_now_review_after_user_direction",
    }


def apply(connection: psycopg.Connection) -> dict:
    rows = current_inventory(connection)
    validate_inventory(rows)
    by_id = {row["release_id"]: row for row in rows}
    connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(ACTOR_ID),))

    approval_metadata = Jsonb(
        {
            "approval_basis": "explicit_user_direction_2026-09-04",
            "approval_mode": "provisional_publish_before_review",
            "post_publication_review_required": True,
        }
    )
    connection.execute(
        """UPDATE smartlib.source_system
              SET authorization_state='approved',
                  metadata=metadata || %s,
                  updated_at=clock_timestamp()
            WHERE code=ANY(%s)""",
        (approval_metadata, list(SOURCE_CODES)),
    )
    connection.execute(
        """UPDATE smartlib.license_grant license
              SET authorization_state='approved',
                  allowed_content=ARRAY['journal_title','impact_factor','quartile',
                                        'cas_partition','category']::text[],
                  allowed_purposes=ARRAY['publication_governance']::text[],
                  prohibited_purposes=ARRAY['external_redistribution']::text[],
                  terms_metadata=terms_metadata || %s,
                  updated_at=clock_timestamp()
             FROM smartlib.data_asset asset
             JOIN smartlib.source_system source ON source.source_system_id=asset.source_system_id
            WHERE license.data_asset_id=asset.data_asset_id
              AND source.code=ANY(%s)""",
        (approval_metadata, list(SOURCE_CODES)),
    )
    connection.execute(
        """UPDATE smartlib.data_asset asset
              SET lifecycle_state='active',
                  metadata=asset.metadata || %s,
                  updated_at=clock_timestamp()
             FROM smartlib.source_system source
            WHERE source.source_system_id=asset.source_system_id
              AND source.code=ANY(%s)""",
        (approval_metadata, list(SOURCE_CODES)),
    )

    superseded_state = connection.execute(
        "SELECT release_state FROM smartlib.journal_metric_release WHERE release_id=%s",
        (SUPERSEDED_RELEASE_ID,),
    ).fetchone()["release_state"]
    if superseded_state != "superseded":
        raise ValueError("the conflicting JCR 2025 alternate must be superseded by an administrator")

    published_now: list[str] = []
    already_published: list[str] = []
    for release_id in PUBLISHED_RELEASE_IDS:
        state = connection.execute(
            "SELECT release_state FROM smartlib.journal_metric_release WHERE release_id=%s",
            (release_id,),
        ).fetchone()["release_state"]
        if state == "published":
            already_published.append(str(release_id))
            continue
        connection.execute("SELECT smartlib.publish_journal_metric_release(%s)", (release_id,))
        published_now.append(str(release_id))

    issue_rows = connection.execute(
        """INSERT INTO smartlib.quality_issue
                  (quality_issue_id,data_asset_id,title,description,severity,issue_state,
                   requires_human_confirmation,created_by)
             SELECT md5('journal-metric-post-publication-review:' || asset.data_asset_id::text)::uuid,
                    asset.data_asset_id,
                    '发布后复核：期刊指标来源与授权',
                    '依据用户明确指令先发布、后审核。需复核原始发布机构、年度口径、影响因子与分区一致性、授权范围；若发现问题，应新建纠正版并替换当前版本。',
                    'high','open',true,%s
               FROM smartlib.data_asset asset
               JOIN smartlib.source_system source ON source.source_system_id=asset.source_system_id
              WHERE source.code=ANY(%s)
                AND NOT EXISTS (
                    SELECT 1 FROM smartlib.quality_issue issue
                     WHERE issue.data_asset_id=asset.data_asset_id
                       AND issue.title='发布后复核：期刊指标来源与授权'
                       AND issue.issue_state IN ('open','acknowledged')
                )
          RETURNING quality_issue_id""",
        (ACTOR_ID, list(SOURCE_CODES)),
    ).fetchall()

    return {
        "status": "published_with_deferred_review",
        "published_release_count": len(PUBLISHED_RELEASE_IDS),
        "published_record_count": sum(by_id[item]["actual_record_count"] for item in PUBLISHED_RELEASE_IDS),
        "published_now_release_ids": published_now,
        "already_published_release_ids": already_published,
        "superseded_release_id": str(SUPERSEDED_RELEASE_ID),
        "superseded_record_count": by_id[SUPERSEDED_RELEASE_ID]["actual_record_count"],
        "created_post_publication_review_tasks": len(issue_rows),
        "audit_event_id": str(AUDIT_EVENT_ID),
        "audit_event_state": "deferred_admin_insert",
        "review_timing": "post_publication",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish journal metrics with deferred review")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(ACTOR_ID),))
        if args.apply:
            with connection.transaction():
                result = apply(connection)
        else:
            result = plan(connection)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
