"""Export the authoritative extracted full-text corpus for affiliation re-audit."""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from smartlib_platform.storage.s3 import S3ObjectStore


def object_key(storage_uri: str, bucket: str) -> str:
    prefix = f"s3://{bucket}/"
    if not storage_uri.startswith(prefix):
        raise ValueError(f"unexpected object-store URI: {storage_uri}")
    return storage_uri[len(prefix) :]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-text-chars", type=int, default=0)
    args = parser.parse_args()

    store = S3ObjectStore(
        os.environ["SMARTLIB_S3_ENDPOINT_URL"],
        os.environ["SMARTLIB_S3_BUCKET"],
        os.environ["SMARTLIB_S3_ACCESS_KEY"],
        os.environ["SMARTLIB_S3_SECRET_KEY"],
        os.environ.get("SMARTLIB_S3_REGION", "us-east-1"),
    )
    with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], row_factory=dict_row) as connection:
        actor_id = UUID(
            os.environ.get(
                "SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001"
            )
        )
        connection.execute("SELECT set_config('smartlib.actor_id', %s, false)", (str(actor_id),))
        connection.commit()
        resources = connection.execute(
            """SELECT DISTINCT ON (resource.publication_id)
                         resource.publication_id, resource.fulltext_resource_id,
                         resource.file_name, resource.content_checksum,
                         resource.extracted_text_uri, resource.page_count,
                         resource.text_length, resource.extraction_method,
                         publication.canonical_name AS publication_title
                    FROM smartlib.publication_fulltext_resource resource
                    JOIN smartlib.knowledge_object publication
                      ON publication.object_id = resource.publication_id
                   WHERE resource.extraction_state = 'extracted'
                     AND resource.extracted_text_uri IS NOT NULL
                     AND publication.system_to = 'infinity'::timestamptz
                ORDER BY resource.publication_id, resource.updated_at DESC"""
        ).fetchall()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(args.output, "wt", encoding="utf-8") as output:
            for resource in resources:
                text = store.get_bytes(
                    object_key(resource["extracted_text_uri"], store.bucket)
                ).decode("utf-8", errors="replace")
                authors = connection.execute(
                    """SELECT publication_authorship_id, author_order, author_name_raw,
                              author_name_normalized, orcid, affiliation_raw,
                              affiliation_source, affiliation_evidence,
                              person_object_id
                         FROM smartlib.publication_authorship
                        WHERE publication_id = %s
                          AND verification_status <> 'rejected'
                     ORDER BY author_order""",
                    (resource["publication_id"],),
                ).fetchall()
                if args.max_text_chars:
                    text = text[: args.max_text_chars]
                output.write(
                    json.dumps(
                        {
                            **dict(resource),
                            "publication_id": str(resource["publication_id"]),
                            "fulltext_resource_id": str(resource["fulltext_resource_id"]),
                            "authors": [
                                {
                                    **dict(author),
                                    "publication_authorship_id": str(
                                        author["publication_authorship_id"]
                                    ),
                                    "person_object_id": (
                                        str(author["person_object_id"])
                                        if author["person_object_id"]
                                        else None
                                    ),
                                }
                                for author in authors
                            ],
                            "text": text,
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\n"
                )
    print(json.dumps({"records": len(resources), "output": str(args.output)}))


if __name__ == "__main__":
    main()
