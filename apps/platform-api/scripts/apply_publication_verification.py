import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlib_platform.publications.verification_state import refresh_effective_verification_state

CROSSREF_SOURCE_ID = UUID("26aaf5cb-9d1e-5ed7-b1c6-5415a63abf09")
NCBI_SOURCE_ID = UUID("eb13a9a8-f769-589d-b51b-1ff433cc6af4")


def load_results(result_path: Path, package_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    results = json.loads(result_path.read_text(encoding="utf-8"))
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if results["manifest"]["dataset_version"] != package["manifest"]["dataset_version"]:
        raise ValueError("verification results and publication package versions differ")
    result_ids = {record["record_id"] for record in results["records"]}
    package_ids = {item["record_id"] for item in package["items"]}
    if result_ids != package_ids or len(results["records"]) != package["manifest"]["expected_item_count"]:
        raise ValueError("verification result records do not reconcile with the publication package")
    allowed = {"auto_verified", "candidate_review", "conflict", "not_found"}
    if any(record["classification"] not in allowed for record in results["records"]):
        raise ValueError("verification results contain an unsupported classification")
    return results, package


def json_checksum(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def field_status(field_name: str, record: dict[str, object]) -> tuple[str, float | None]:
    scores = record["scores"]
    classification = record["classification"]
    if classification == "not_found":
        return "conflict", None
    if field_name == "title":
        score = scores.get("title_score")
        return ("matched" if score is not None and score >= 0.97 else "conflict"), score
    if field_name == "journal_name":
        score = scores.get("journal_score")
        return ("matched" if score is not None and score >= 0.75 else "conflict"), score
    if field_name == "publication_year":
        distance = scores.get("year_distance")
        if distance is None:
            return "pending", None
        return ("matched" if distance <= 1 else "conflict"), max(0.0, 1.0 - min(distance, 10) / 10)
    if field_name == "doi":
        return ("matched", 1.0) if record["method"] == "exact_doi" else ("pending", None)
    if field_name == "pmid":
        ncbi = record.get("ncbi_pubmed") or {}
        source_pmid = record.get("source_pmid")
        return (
            ("matched", 1.0)
            if ncbi and not ncbi.get("not_found") and ncbi.get("pmid") == source_pmid
            else ("conflict", None)
        )
    return "pending", None


def insert_field_verifications(
    connection: psycopg.Connection,
    *,
    record: dict[str, object],
    item: dict[str, object],
    publication_id: UUID | None,
    actor_id: UUID,
    namespace: UUID,
    crossref_source_reference_id: UUID | None,
    ncbi_source_reference_id: UUID | None,
) -> int:
    source = item["normalized_payload"]
    candidate = record.get("crossref") or {}
    proposal_id = candidate.get("doi") or source.get("doi") or f"search-row-{item['source_serial']}"
    fields = {
        "title": (source.get("title"), candidate.get("title")),
        "journal_name": (source.get("journal_or_conference"), candidate.get("journal_name")),
        "publication_year": (source.get("publication_year"), candidate.get("publication_year")),
        "doi": (source.get("doi"), candidate.get("doi")),
    }
    if source.get("pmid"):
        fields["pmid"] = (source.get("pmid"), (record.get("ncbi_pubmed") or {}).get("pmid"))
    record["source_pmid"] = source.get("pmid")
    inserted = 0
    for field_name, (source_value, candidate_value) in fields.items():
        status, score = field_status(field_name, record)
        candidate_external_id = (
            (record.get("ncbi_pubmed") or {}).get("pmid") or source.get("pmid")
            if field_name == "pmid"
            else proposal_id
        )
        field_source_reference_id = (
            ncbi_source_reference_id if field_name == "pmid" else crossref_source_reference_id
        )
        field_id = uuid5(
            namespace,
            f"{record['record_id']}:field:{field_name}:crossref-ncbi-conservative-v1",
        )
        inserted += connection.execute(
            """INSERT INTO smartlib.publication_field_verification
                      (field_verification_id, record_id, publication_id, field_name,
                       source_value, normalized_source_value, candidate_value,
                       candidate_source_code, candidate_external_id, match_score,
                       verification_status, difference_type, decision_reason,
                       source_reference_id, comparison_details, created_by)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                 ON CONFLICT (field_verification_id) DO NOTHING""",
            (
                field_id,
                UUID(record["record_id"]),
                publication_id,
                field_name,
                Jsonb(source_value),
                Jsonb(source_value),
                Jsonb(candidate_value),
                "crossref" if field_name != "pmid" else "ncbi_pubmed",
                str(candidate_external_id),
                score,
                status,
                None if status == "matched" else record["classification"],
                f"Automatic {record['method']} verification: {record['classification']}",
                field_source_reference_id,
                Jsonb({"scores": record["scores"], "rule_version": "crossref-ncbi-conservative-v1"}),
                actor_id,
            ),
        ).rowcount
    return inserted


def ensure_source_systems(connection: psycopg.Connection) -> None:
    connection.execute(
        """INSERT INTO smartlib.source_system
                  (source_system_id, code, name, owner_department, source_type,
                   authorization_state, metadata)
             VALUES
                  (%s, 'crossref_rest', 'Crossref REST API', 'Crossref', 'api', 'approved',
                   '{"scope":"public bibliographic metadata"}'::jsonb),
                  (%s, 'ncbi_pubmed_api', 'NCBI PubMed E-utilities',
                   'U.S. National Library of Medicine', 'api', 'approved',
                   '{"scope":"public PubMed bibliographic metadata"}'::jsonb)
             ON CONFLICT (code) DO NOTHING""",
        (CROSSREF_SOURCE_ID, NCBI_SOURCE_ID),
    )
    rows = connection.execute(
        """SELECT source_system_id, code FROM smartlib.source_system
            WHERE code IN ('crossref_rest', 'ncbi_pubmed_api')"""
    ).fetchall()
    expected = {"crossref_rest": CROSSREF_SOURCE_ID, "ncbi_pubmed_api": NCBI_SOURCE_ID}
    if {row["code"]: row["source_system_id"] for row in rows} != expected:
        raise ValueError("verification source code is bound to an unexpected source identity")


def ensure_publication(
    connection: psycopg.Connection,
    *,
    record: dict[str, object],
    item: dict[str, object],
    actor_id: UUID,
    namespace: UUID,
    run_id: str,
    retrieved_at: str,
) -> tuple[UUID, UUID, UUID | None, int]:
    candidate = record["crossref"]
    doi = candidate["doi"]
    publication_id = uuid5(namespace, f"publication:doi:{doi}")
    source_reference_id = uuid5(namespace, f"crossref-reference:{doi}")
    attributes = {
        "doi": doi,
        "year": candidate.get("publication_year"),
        "publication_type": candidate.get("publication_type"),
        "verification_run_id": run_id,
        "synthetic": False,
    }
    inserted_object = connection.execute(
        """INSERT INTO smartlib.knowledge_object
                  (object_id, object_type, canonical_name, description, visibility,
                   quality_state, review_state, attributes, created_by)
             VALUES (%s, 'publication', %s, %s, 'restricted', 'validated', 'approved', %s, %s)
             ON CONFLICT (object_id) DO NOTHING""",
        (
            publication_id,
            candidate["title"],
            f"Automatically verified publication metadata from Crossref DOI {doi}.",
            Jsonb(attributes),
            actor_id,
        ),
    ).rowcount
    connection.execute(
        """INSERT INTO smartlib.publication_metadata
                  (publication_id, title, journal_name, publication_year, volume, issue,
                   pages, article_number, publication_type, publication_status,
                   attributes, created_by)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'published', %s, %s)
             ON CONFLICT (publication_id) DO NOTHING""",
        (
            publication_id,
            candidate["title"],
            candidate.get("journal_name"),
            candidate.get("publication_year"),
            candidate.get("volume"),
            candidate.get("issue"),
            candidate.get("pages"),
            candidate.get("article_number"),
            candidate.get("publication_type"),
            Jsonb({"publisher": candidate.get("publisher"), "url": candidate.get("url")}),
            actor_id,
        ),
    )
    connection.execute(
        """INSERT INTO smartlib.source_reference
                  (source_reference_id, object_id, source_system_id, external_id,
                   source_version, observed_at, payload_checksum, raw_object_uri, metadata)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
             ON CONFLICT (source_system_id, external_id, version) DO NOTHING""",
        (
            source_reference_id,
            publication_id,
            CROSSREF_SOURCE_ID,
            doi,
            run_id,
            retrieved_at,
            json_checksum(candidate),
            f"https://api.crossref.org/works/{doi}",
            Jsonb({"rule_version": "crossref-ncbi-conservative-v1", "synthetic": False}),
        ),
    )
    identifier_id = uuid5(namespace, f"publication-identifier:doi:{doi}")
    connection.execute(
        """INSERT INTO smartlib.publication_identifier
                  (publication_identifier_id, publication_id, identifier_type,
                   raw_value, normalized_value, is_primary, verification_status,
                   source_reference_id, created_by)
             VALUES (%s, %s, 'doi', %s, %s, true, 'matched', %s, %s)
             ON CONFLICT (publication_identifier_id) DO NOTHING""",
        (identifier_id, publication_id, doi, doi, source_reference_id, actor_id),
    )
    ncbi = record.get("ncbi_pubmed") or {}
    ncbi_source_reference_id = None
    if (
        ncbi
        and not ncbi.get("not_found")
        and ncbi.get("pmid")
        and (not ncbi.get("doi") or ncbi.get("doi") == doi)
    ):
        pmid = str(ncbi["pmid"])
        ncbi_source_reference_id = uuid5(namespace, f"ncbi-pubmed-reference:{pmid}")
        connection.execute(
            """INSERT INTO smartlib.source_reference
                      (source_reference_id, object_id, source_system_id, external_id,
                       source_version, observed_at, payload_checksum, raw_object_uri, metadata)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                 ON CONFLICT (source_system_id, external_id, version) DO NOTHING""",
            (
                ncbi_source_reference_id,
                publication_id,
                NCBI_SOURCE_ID,
                pmid,
                run_id,
                retrieved_at,
                json_checksum(ncbi),
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pmid}",
                Jsonb({"rule_version": "crossref-ncbi-conservative-v1", "synthetic": False}),
            ),
        )
        for identifier_type, identifier_value in (("pmid", pmid), ("pmcid", ncbi.get("pmcid"))):
            if not identifier_value:
                continue
            normalized_identifier = (
                str(identifier_value).upper() if identifier_type == "pmcid" else str(identifier_value)
            )
            ncbi_identifier_id = uuid5(
                namespace,
                f"publication-identifier:{identifier_type}:{normalized_identifier}",
            )
            connection.execute(
                """INSERT INTO smartlib.publication_identifier
                          (publication_identifier_id, publication_id, identifier_type,
                           raw_value, normalized_value, is_primary, verification_status,
                           source_reference_id, created_by)
                     VALUES (%s, %s, %s, %s, %s, true, 'matched', %s, %s)
                     ON CONFLICT (publication_identifier_id) DO NOTHING""",
                (
                    ncbi_identifier_id,
                    publication_id,
                    identifier_type,
                    identifier_value,
                    normalized_identifier,
                    ncbi_source_reference_id,
                    actor_id,
                ),
            )
    for order, author in enumerate(candidate.get("authors", []), start=1):
        name = " ".join(value for value in (author.get("given"), author.get("family")) if value).strip()
        if not name:
            continue
        authorship_id = uuid5(namespace, f"publication-authorship:{doi}:{order}")
        connection.execute(
            """INSERT INTO smartlib.publication_authorship
                      (publication_authorship_id, publication_id, author_order,
                       author_name_raw, author_name_normalized, given_name, family_name,
                       orcid, affiliation_raw, is_first_author, match_status,
                       verification_status, source_reference_id, created_by)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                         'unmatched', 'matched', %s, %s)
                 ON CONFLICT (publication_id, author_order) DO NOTHING""",
            (
                authorship_id,
                publication_id,
                order,
                name,
                name,
                author.get("given"),
                author.get("family"),
                author.get("orcid"),
                "; ".join(value for value in author.get("affiliations", []) if value) or None,
                order == 1,
                source_reference_id,
                actor_id,
            ),
        )
    evidence_id = uuid5(namespace, f"publication-verification-evidence:{record['record_id']}")
    connection.execute(
        """INSERT INTO smartlib.evidence_record
                  (evidence_id, object_id, source_reference_id, evidence_type,
                   citation, excerpt, visibility, license_tags, content_checksum,
                   metadata, created_by)
             VALUES (%s, %s, %s, 'publication', %s, %s, 'restricted', %s, %s, %s, %s)
             ON CONFLICT (evidence_id) DO NOTHING""",
        (
            evidence_id,
            publication_id,
            source_reference_id,
            f"Excel row {item['source_excel_row']} verified against Crossref DOI {doi}",
            candidate["title"],
            ["controlled-file", "crossref-metadata"],
            item["row_checksum"],
            Jsonb(
                {
                    "record_id": item["record_id"],
                    "awardee_person_id": item["awardee_person_id"],
                    "scores": record["scores"],
                    "verification_run_id": run_id,
                }
            ),
            actor_id,
        ),
    )
    ncbi_evidence_id = None
    if ncbi_source_reference_id:
        ncbi_evidence_id = uuid5(namespace, f"publication-ncbi-evidence:{record['record_id']}")
        connection.execute(
            """INSERT INTO smartlib.evidence_record
                      (evidence_id, object_id, source_reference_id, evidence_type,
                       citation, excerpt, visibility, license_tags, content_checksum,
                       metadata, created_by)
                 VALUES (%s, %s, %s, 'publication', %s, %s, 'restricted', %s, %s, %s, %s)
                 ON CONFLICT (evidence_id) DO NOTHING""",
            (
                ncbi_evidence_id,
                publication_id,
                ncbi_source_reference_id,
                f"NCBI PubMed PMID {ncbi['pmid']} corroboration for Excel row {item['source_excel_row']}",
                ncbi.get("title"),
                ["controlled-file", "ncbi-pubmed-metadata"],
                item["row_checksum"],
                Jsonb(
                    {
                        "record_id": item["record_id"],
                        "scores": record["scores"],
                        "verification_run_id": run_id,
                        "ncbi_pubmed_metadata": ncbi,
                    }
                ),
                actor_id,
            ),
        )
    if inserted_object:
        event_id = uuid5(namespace, f"outbox:publication:{publication_id}:{run_id}")
        connection.execute(
            """INSERT INTO smartlib.outbox_event
                      (event_id, aggregate_type, aggregate_id, event_type,
                       event_version, payload, trace_id)
                 VALUES (%s, 'knowledge_object', %s, 'knowledge.publication.verified', 1, %s, %s)
                 ON CONFLICT (event_id) DO NOTHING""",
            (
                event_id,
                publication_id,
                Jsonb({"object_id": str(publication_id), "version": 1, "doi": doi}),
                run_id,
            ),
        )
    # An awardee association from the controlled spreadsheet is not, by itself,
    # authorship evidence. person.authored is materialized only after an explicit
    # publication_authorship row has been matched to the person.
    return publication_id, source_reference_id, ncbi_source_reference_id, inserted_object


def apply_results(
    results: dict[str, object], package: dict[str, object], database_url: str, actor_id: UUID
) -> dict[str, int | str]:
    package_items = {item["record_id"]: item for item in package["items"]}
    manifest = results["manifest"]
    run_id = manifest["verification_run_id"]
    namespace = UUID(package["manifest"]["uuid_namespace"])
    batch_id = uuid5(namespace, f"{package['manifest']['dataset_version']}:batch")
    inserted_publications = 0
    inserted_fields = 0
    auto_items = 0
    manual_items = 0
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            ensure_source_systems(connection)
            for record in results["records"]:
                item = package_items[record["record_id"]]
                publication_id = None
                crossref_source_reference_id = None
                ncbi_source_reference_id = None
                if record["classification"] == "auto_verified":
                    (
                        publication_id,
                        crossref_source_reference_id,
                        ncbi_source_reference_id,
                        inserted,
                    ) = ensure_publication(
                        connection,
                        record=record,
                        item=item,
                        actor_id=actor_id,
                        namespace=namespace,
                        run_id=run_id,
                        retrieved_at=manifest["retrieved_at"],
                    )
                    inserted_publications += inserted
                    auto_items += 1
                else:
                    manual_items += 1
                inserted_fields += insert_field_verifications(
                    connection,
                    record=record,
                    item=item,
                    publication_id=publication_id,
                    actor_id=actor_id,
                    namespace=namespace,
                    crossref_source_reference_id=crossref_source_reference_id,
                    ncbi_source_reference_id=ncbi_source_reference_id,
                )
                target_state = "auto_verified" if publication_id else "manual_review"
                connection.execute(
                    """UPDATE smartlib.publication_intake_record
                          SET verification_state = %s, matched_publication_id = %s
                        WHERE record_id = %s AND record_id IN
                          (SELECT record_id FROM smartlib.ingestion_record WHERE batch_id = %s)""",
                    (target_state, publication_id, UUID(record["record_id"]), batch_id),
                )
                if publication_id:
                    decision_id = uuid5(
                        namespace,
                        f"verification-decision:{record['record_id']}:{run_id}",
                    )
                    connection.execute(
                        """INSERT INTO smartlib.publication_verification_decision
                                  (verification_decision_id, record_id, publication_id,
                                   decision, decision_reason, decision_method, rule_version,
                                   evidence_summary, decided_by, created_by)
                             VALUES (%s, %s, %s, 'auto_verified', %s, 'rule', %s, %s, %s, %s)
                             ON CONFLICT (verification_decision_id) DO NOTHING""",
                        (
                            decision_id,
                            UUID(record["record_id"]),
                            publication_id,
                            "Exact DOI metadata passed strict title, year, and journal checks",
                            manifest["rule_version"],
                            Jsonb(
                                {
                                    "crossref_source_reference_id": str(crossref_source_reference_id),
                                    "ncbi_source_reference_id": (
                                        str(ncbi_source_reference_id) if ncbi_source_reference_id else None
                                    ),
                                    "scores": record["scores"],
                                    "ncbi_pubmed": record.get("ncbi_pubmed"),
                                }
                            ),
                            actor_id,
                            actor_id,
                        ),
                    )
                    refresh_effective_verification_state(
                        connection, record_id=UUID(record["record_id"])
                    )
            connection.execute(
                """UPDATE smartlib.ingestion_batch
                      SET batch_state = 'verifying', processing_rule_version = %s,
                          metadata = metadata || %s
                    WHERE batch_id = %s""",
                (
                    manifest["rule_version"],
                    Jsonb(
                        {
                            "automatic_verification_run_id": run_id,
                            "automatic_verification_retrieved_at": manifest["retrieved_at"],
                            "classification_counts": manifest["classification_counts"],
                        }
                    ),
                    batch_id,
                ),
            )
            if inserted_publications:
                audit_id = uuid5(namespace, f"audit:{run_id}:applied")
                connection.execute(
                    """INSERT INTO audit.audit_event
                              (event_id, actor_id, action, resource_type, resource_id,
                               decision, trace_id, details)
                         VALUES (%s, %s, 'publication.automatic_verification_applied',
                                 'ingestion_batch', %s, 'recorded', %s, %s)""",
                    (
                        audit_id,
                        actor_id,
                        str(batch_id),
                        run_id,
                        Jsonb(
                            {
                                "auto_verified_items": auto_items,
                                "manual_review_items": manual_items,
                                "canonical_publications": inserted_publications,
                                "classification_counts": manifest["classification_counts"],
                            }
                        ),
                    ),
                )
    return {
        "status": "applied",
        "auto_verified_items": auto_items,
        "manual_review_items": manual_items,
        "inserted_publications": inserted_publications,
        "inserted_field_verifications": inserted_fields,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply controlled publication verification results")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    results, package = load_results(args.results, args.package)
    if not args.apply:
        print(json.dumps({"status": "validated", **results["manifest"]}, ensure_ascii=False))
        return
    result = apply_results(
        results,
        package,
        os.environ["SMARTLIB_DATABASE_URL"],
        UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"]),
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
