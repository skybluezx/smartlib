"""Enrich publication journal identifiers and materialize governed journal relations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlib_platform.journal_metrics.workbook import normalize_issn
from smartlib_platform.journals.normalization import clean_title, journal_key, normalized_title

RULE_VERSION = "publication-journal-authority-v2"
NAMESPACE = UUID("925415ad-c26f-458c-8d1d-f82b56da9c59")
CROSSREF_SOURCE_ID = UUID("26aaf5cb-9d1e-5ed7-b1c6-5415a63abf09")
SUPPLEMENT_SOURCE_ID = uuid5(NAMESPACE, "source:controlled-journal-identifier-supplements")


@dataclass(frozen=True)
class AuthorityRecord:
    doi: str
    canonical_title: str
    aliases: tuple[tuple[str, str], ...]
    issn: str | None
    eissn: str | None
    publication_year: int | None
    source_code: str
    source_label: str
    source_uri: str
    observed_at: str | None
    payload: dict[str, Any]


def normalize_doi(value: object) -> str:
    return str(value or "").strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")


def checksum(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def first_text(value: object) -> str | None:
    if isinstance(value, list):
        return next((clean_title(item) for item in value if clean_title(item)), None)
    text = clean_title(value)
    return text or None


def extract_crossref_identifiers(message: dict[str, Any]) -> tuple[str | None, str | None]:
    print_values: list[str] = []
    electronic_values: list[str] = []
    for item in message.get("issn-type") or []:
        value = normalize_issn(item.get("value"))
        if not value:
            continue
        if item.get("type") == "print":
            print_values.append(value)
        elif item.get("type") == "electronic":
            electronic_values.append(value)
    all_values = [value for value in (normalize_issn(item) for item in message.get("ISSN") or []) if value]
    issn = next(iter(dict.fromkeys(print_values)), None)
    eissn = next(iter(dict.fromkeys(electronic_values)), None)
    if issn is None and eissn is None and all_values:
        issn = all_values[0]
    elif issn is None:
        issn = next((value for value in all_values if value != eissn), None)
    elif eissn is None:
        eissn = next((value for value in all_values if value != issn), None)
    return issn, eissn


def extract_crossref_year(message: dict[str, Any]) -> int | None:
    for key in ("published-online", "published-print", "published", "issued"):
        parts = (message.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            return int(parts[0][0])
    return None


def load_authority_records(crossref_dir: Path, supplement_path: Path) -> dict[str, AuthorityRecord]:
    supplements = {
        normalize_doi(item["doi"]): item
        for item in json.loads(supplement_path.read_text(encoding="utf-8"))["records"]
    }
    records: dict[str, AuthorityRecord] = {}
    for path in sorted(crossref_dir.glob("*.json")):
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        doi = normalize_doi(wrapper.get("doi") or (wrapper.get("message") or {}).get("DOI"))
        if not doi:
            raise ValueError(f"Crossref cache has no DOI: {path}")
        message = wrapper.get("message") if wrapper.get("ok") else None
        supplement = supplements.get(doi)
        if message:
            issn, eissn = extract_crossref_identifiers(message)
            canonical = first_text(message.get("container-title"))
            if not canonical:
                raise ValueError(f"Crossref record has no publication venue: {doi}")
            aliases = [(canonical, "canonical")]
            short_title = first_text(message.get("short-container-title"))
            if short_title and short_title != canonical:
                aliases.append((short_title, "abbreviation"))
            records[doi] = AuthorityRecord(
                doi=doi,
                canonical_title=canonical,
                aliases=tuple(aliases),
                issn=issn,
                eissn=eissn,
                publication_year=extract_crossref_year(message),
                source_code="crossref_rest",
                source_label="Crossref REST API",
                source_uri=str(wrapper.get("url") or f"https://api.crossref.org/works/{doi}"),
                observed_at=wrapper.get("retrieved_at"),
                payload=wrapper,
            )
        elif supplement:
            records[doi] = AuthorityRecord(
                doi=doi,
                canonical_title=str(supplement["journal_name"]),
                aliases=((str(supplement["journal_name"]), "canonical"),),
                issn=normalize_issn(supplement.get("issn")),
                eissn=normalize_issn(supplement.get("eissn")),
                publication_year=None,
                source_code="controlled_journal_supplement",
                source_label=str(supplement["source_label"]),
                source_uri=str(supplement["source_uri"]),
                observed_at=str(supplement["observed_at"]),
                payload=supplement,
            )
        else:
            raise ValueError(f"No usable authority record or controlled supplement for DOI {doi}")
    unused = sorted(set(supplements) - set(records))
    if unused:
        raise ValueError(f"Controlled supplements do not match the Crossref inventory: {unused}")
    return records


def ensure_sources(connection: psycopg.Connection[Any]) -> None:
    connection.execute(
        """INSERT INTO smartlib.source_system
                  (source_system_id,code,name,owner_department,source_type,authorization_state,metadata)
             VALUES (%s,'crossref_rest','Crossref REST API','Crossref','api','approved',%s),
                    (%s,'controlled_journal_supplement','Controlled journal identifier supplement',
                     '图书馆数据治理','manual','approved',%s)
             ON CONFLICT(code) DO NOTHING""",
        (
            CROSSREF_SOURCE_ID,
            Jsonb({"scope": "public bibliographic metadata"}),
            SUPPLEMENT_SOURCE_ID,
            Jsonb({"scope": "public journal identity metadata", "rule_version": RULE_VERSION}),
        ),
    )


def source_reference(
    connection: psycopg.Connection[Any], publication_id: UUID, record: AuthorityRecord
) -> UUID:
    source_id = CROSSREF_SOURCE_ID if record.source_code == "crossref_rest" else SUPPLEMENT_SOURCE_ID
    reference_id = uuid5(NAMESPACE, f"journal-source:{record.source_code}:{record.doi}")
    row = connection.execute(
        """INSERT INTO smartlib.source_reference
                  (source_reference_id,object_id,source_system_id,external_id,source_version,
                   observed_at,payload_checksum,raw_object_uri,metadata)
             VALUES (%s,%s,%s,%s,%s,COALESCE(%s::timestamptz,clock_timestamp()),%s,%s,%s)
             ON CONFLICT(source_system_id,external_id,version) DO UPDATE SET
               object_id=excluded.object_id,source_version=excluded.source_version,
               observed_at=excluded.observed_at,payload_checksum=excluded.payload_checksum,
               raw_object_uri=excluded.raw_object_uri,metadata=excluded.metadata
             WHERE (smartlib.source_reference.object_id,smartlib.source_reference.source_version,
                    smartlib.source_reference.observed_at,smartlib.source_reference.payload_checksum,
                    smartlib.source_reference.raw_object_uri,smartlib.source_reference.metadata)
                IS DISTINCT FROM
                   (excluded.object_id,excluded.source_version,excluded.observed_at,
                    excluded.payload_checksum,excluded.raw_object_uri,excluded.metadata)
             RETURNING source_reference_id""",
        (
            reference_id,
            publication_id,
            source_id,
            record.doi,
            record.observed_at or RULE_VERSION,
            record.observed_at,
            checksum(record.payload),
            record.source_uri,
            Jsonb({"rule_version": RULE_VERSION, "source_label": record.source_label}),
        ),
    ).fetchone()
    if row:
        return row["source_reference_id"]
    existing = connection.execute(
        """SELECT source_reference_id FROM smartlib.source_reference
             WHERE source_system_id=%s AND external_id=%s AND version=1""",
        (source_id, record.doi),
    ).fetchone()
    return existing["source_reference_id"]


def evidence_record(
    connection: psycopg.Connection[Any], publication_id: UUID, source_id: UUID,
    record: AuthorityRecord, actor_id: UUID
) -> UUID:
    evidence_id = uuid5(NAMESPACE, f"journal-identifier-evidence:{record.source_code}:{record.doi}")
    connection.execute(
        """INSERT INTO smartlib.evidence_record
                  (evidence_id,object_id,source_reference_id,evidence_type,citation,excerpt,
                   visibility,license_tags,content_checksum,metadata,evidence_kind,
                   verification_state,created_by)
             VALUES (%s,%s,%s,'publication',%s,%s,'restricted',%s,%s,%s,
                     'journal_identity','confirmed',%s)
             ON CONFLICT(evidence_id) DO NOTHING""",
        (
            evidence_id,
            publication_id,
            source_id,
            f"{record.source_label}: DOI {record.doi}",
            f"{record.canonical_title}; ISSN {record.issn or '-'}; eISSN {record.eissn or '-'}",
            ["crossref-metadata"] if record.source_code == "crossref_rest" else ["public-journal-metadata"],
            checksum(record.payload),
            Jsonb({"doi": record.doi, "issn": record.issn, "eissn": record.eissn,
                   "rule_version": RULE_VERSION}),
            actor_id,
        ),
    )
    return evidence_id


def add_variant(
    connection: psycopg.Connection[Any], journal_id: UUID, name: str, variant_type: str,
    actor_id: UUID, source_id: UUID | None
) -> int:
    clean_name = clean_title(name)
    key = journal_key(clean_name)
    if not key:
        raise ValueError(f"Journal alias normalizes to an empty key: {name!r}")
    variant_id = uuid5(NAMESPACE, f"journal-variant:{journal_id}:{clean_name}")
    row = connection.execute(
        """INSERT INTO smartlib.journal_name_variant
                  (journal_name_variant_id,journal_id,name,normalized_name,variant_type,created_by)
             VALUES (%s,%s,%s,%s,%s,%s)
             ON CONFLICT(journal_id,name) DO NOTHING
             RETURNING journal_name_variant_id,(xmax=0) AS inserted""",
        (variant_id, journal_id, clean_name, key, variant_type, actor_id),
    ).fetchone()
    if row is None:
        row = connection.execute(
            """SELECT journal_name_variant_id,false AS inserted
                 FROM smartlib.journal_name_variant WHERE journal_id=%s AND name=%s""",
            (journal_id, clean_name),
        ).fetchone()
    if source_id:
        connection.execute(
            """INSERT INTO smartlib.journal_name_variant_source
                      (journal_name_variant_id,source_reference_id)
                 VALUES (%s,%s) ON CONFLICT DO NOTHING""",
            (row["journal_name_variant_id"], source_id),
        )
    return int(row["inserted"])


def load_identity_maps(connection: psycopg.Connection[Any]) -> tuple[dict[str, UUID], dict[str, set[UUID]]]:
    identifiers: dict[str, UUID] = {}
    names: dict[str, set[UUID]] = defaultdict(set)
    for row in connection.execute(
        "SELECT journal_id,normalized_title,issn,eissn FROM smartlib.journal_identity"
    ).fetchall():
        for value in (row["issn"], row["eissn"]):
            if value:
                identifiers[value] = row["journal_id"]
        names[journal_key(row["normalized_title"])].add(row["journal_id"])
    for row in connection.execute(
        "SELECT journal_id,normalized_name FROM smartlib.journal_name_variant"
    ).fetchall():
        names[row["normalized_name"]].add(row["journal_id"])
    return identifiers, names


def repair_encoded_variants(connection: psycopg.Connection[Any]) -> int:
    repaired = 0
    rows = connection.execute(
        "SELECT journal_name_variant_id,journal_id,name FROM smartlib.journal_name_variant"
    ).fetchall()
    for row in rows:
        clean_name = clean_title(row["name"])
        if clean_name == row["name"]:
            continue
        target = connection.execute(
            """SELECT journal_name_variant_id FROM smartlib.journal_name_variant
                 WHERE journal_id=%s AND name=%s""",
            (row["journal_id"], clean_name),
        ).fetchone()
        if target:
            connection.execute(
                """INSERT INTO smartlib.journal_name_variant_source
                          (journal_name_variant_id,source_reference_id)
                     SELECT %s,source_reference_id FROM smartlib.journal_name_variant_source
                      WHERE journal_name_variant_id=%s ON CONFLICT DO NOTHING""",
                (target["journal_name_variant_id"], row["journal_name_variant_id"]),
            )
            connection.execute(
                "DELETE FROM smartlib.journal_name_variant WHERE journal_name_variant_id=%s",
                (row["journal_name_variant_id"],),
            )
        else:
            connection.execute(
                """UPDATE smartlib.journal_name_variant SET name=%s,normalized_name=%s
                     WHERE journal_name_variant_id=%s""",
                (clean_name, journal_key(clean_name), row["journal_name_variant_id"]),
            )
        repaired += 1
    return repaired


def select_or_create_identity(
    connection: psycopg.Connection[Any], record: AuthorityRecord, aliases: list[str], actor_id: UUID,
    identifiers: dict[str, UUID], names: dict[str, set[UUID]], apply: bool
) -> tuple[UUID, bool]:
    identifier_candidates = {
        identifiers[value] for value in (record.issn, record.eissn) if value in identifiers
    }
    name_candidates = set().union(*(names.get(journal_key(name), set()) for name in aliases))
    candidates = identifier_candidates or name_candidates
    if len(candidates) > 1:
        raise ValueError(f"Ambiguous journal identity for DOI {record.doi}: {sorted(map(str, candidates))}")
    key = record.issn or record.eissn or journal_key(record.canonical_title)
    journal_id = next(iter(candidates), uuid5(NAMESPACE, f"journal:{key}"))
    created = not candidates
    if apply:
        if created:
            connection.execute(
                """INSERT INTO smartlib.journal_identity
                          (journal_id,canonical_title,normalized_title,issn,eissn,created_by)
                     VALUES (%s,%s,%s,%s,%s,%s)""",
                (journal_id, record.canonical_title, normalized_title(record.canonical_title),
                 record.issn, record.eissn, actor_id),
            )
        else:
            current = connection.execute(
                """SELECT canonical_title,normalized_title,issn,eissn
                     FROM smartlib.journal_identity WHERE journal_id=%s""",
                (journal_id,),
            ).fetchone()
            for field, incoming in (("issn", record.issn), ("eissn", record.eissn)):
                if current[field] and incoming and current[field] != incoming:
                    raise ValueError(
                        f"Conflicting {field} for journal {journal_id}: {current[field]} vs {incoming}"
                    )
            clean_canonical = clean_title(current["canonical_title"])
            clean_normalized = normalized_title(clean_canonical)
            connection.execute(
                """UPDATE smartlib.journal_identity SET
                       canonical_title=%s,normalized_title=%s,
                       issn=COALESCE(issn,%s),eissn=COALESCE(eissn,%s)
                     WHERE journal_id=%s AND
                       (canonical_title IS DISTINCT FROM %s
                        OR normalized_title IS DISTINCT FROM %s
                        OR (issn IS NULL AND %s::text IS NOT NULL)
                        OR (eissn IS NULL AND %s::text IS NOT NULL))""",
                (
                    clean_canonical,
                    clean_normalized,
                    record.issn,
                    record.eissn,
                    journal_id,
                    clean_canonical,
                    clean_normalized,
                    record.issn,
                    record.eissn,
                ),
            )
    for value in (record.issn, record.eissn):
        if value:
            previous = identifiers.get(value)
            if previous and previous != journal_id:
                raise ValueError(f"ISSN {value} resolves to multiple journal identities")
            identifiers[value] = journal_id
    for alias in aliases:
        names[journal_key(alias)].add(journal_id)
    return journal_id, created


def run(
    connection: psycopg.Connection[Any], records: dict[str, AuthorityRecord], actor_id: UUID,
    *, apply: bool
) -> dict[str, Any]:
    publications = connection.execute(
        """SELECT metadata.publication_id,metadata.title,metadata.journal_name,
                  metadata.journal_abbreviation,metadata.issn,metadata.eissn,
                  metadata.publication_year,identifier.normalized_value AS doi
             FROM smartlib.publication_metadata metadata
             JOIN smartlib.knowledge_object object ON object.object_id=metadata.publication_id
             JOIN smartlib.publication_identifier identifier
               ON identifier.publication_id=metadata.publication_id
              AND identifier.identifier_type='doi' AND identifier.verification_status<>'rejected'
            WHERE object.object_type='publication' AND object.system_to='infinity'
            ORDER BY metadata.publication_id"""
    ).fetchall()
    if len(publications) != 269 or len({normalize_doi(row["doi"]) for row in publications}) != 269:
        raise ValueError("Expected exactly 269 active publications with unique DOI identifiers")
    missing = sorted({normalize_doi(row["doi"]) for row in publications} - set(records))
    extra = sorted(set(records) - {normalize_doi(row["doi"]) for row in publications})
    if missing or extra:
        raise ValueError(f"DOI inventory mismatch; missing={missing}, extra={extra}")

    counters: Counter[str] = Counter(publications=len(publications))
    unresolved: list[dict[str, str]] = []
    title_variants: list[dict[str, str]] = []
    if apply:
        ensure_sources(connection)
        counters["alias_display_repairs"] = repair_encoded_variants(connection)
    identifiers, names = load_identity_maps(connection)
    journal_ids: set[UUID] = set()

    for publication in publications:
        doi = normalize_doi(publication["doi"])
        record = records[doi]
        aliases = [str(publication["journal_name"]), record.canonical_title]
        if publication["journal_abbreviation"]:
            aliases.append(str(publication["journal_abbreviation"]))
        aliases.extend(name for name, _ in record.aliases)
        aliases = list(dict.fromkeys(name for name in aliases if name.strip()))
        if journal_key(publication["journal_name"]) != journal_key(record.canonical_title):
            counters["title_variants"] += 1
            title_variants.append(
                {
                    "doi": doi,
                    "publication_journal_name": str(publication["journal_name"]),
                    "authority_journal_name": record.canonical_title,
                }
            )

        journal_id, created = select_or_create_identity(
            connection, record, aliases, actor_id, identifiers, names, apply
        )
        journal_ids.add(journal_id)
        counters["journal_identities_created"] += int(created)
        if record.issn or record.eissn:
            counters["publications_with_identifiers"] += 1
        else:
            unresolved.append({"doi": doi, "journal_name": str(publication["journal_name"])})

        if not apply:
            continue
        source_id = source_reference(connection, publication["publication_id"], record)
        evidence_id = evidence_record(
            connection, publication["publication_id"], source_id, record, actor_id
        )
        updated = connection.execute(
            """UPDATE smartlib.publication_metadata SET
                   issn=%s,eissn=%s,publication_year=COALESCE(publication_year,%s),
                   metadata_version=metadata_version+1,
                   last_enriched_at=clock_timestamp(),
                   attributes=attributes||%s
                 WHERE publication_id=%s AND (issn IS DISTINCT FROM %s OR eissn IS DISTINCT FROM %s
                    OR (publication_year IS NULL AND %s::integer IS NOT NULL))""",
            (record.issn, record.eissn, record.publication_year,
             Jsonb({"journal_identifier_source": record.source_code,
                    "journal_identifier_rule_version": RULE_VERSION}),
             publication["publication_id"], record.issn, record.eissn, record.publication_year),
        ).rowcount
        counters["publication_metadata_updated"] += updated

        object_row = connection.execute(
            """SELECT knowledge_object_id,canonical_title,issn,eissn
                 FROM smartlib.journal_identity WHERE journal_id=%s""",
            (journal_id,),
        ).fetchone()
        object_id = object_row["knowledge_object_id"] or journal_id
        inserted_object = connection.execute(
            """INSERT INTO smartlib.knowledge_object
                      (object_id,object_type,canonical_name,description,visibility,quality_state,
                       review_state,attributes,created_by)
                 VALUES (%s,'journal',%s,%s,'restricted','validated','approved',%s,%s)
                 ON CONFLICT(object_id) DO NOTHING""",
            (object_id, object_row["canonical_title"],
             "论文发表来源。年度影响因子与分区通过独立版本化指标记录关联。",
             Jsonb({"record_kind": "journal", "journal_identity_id": str(journal_id),
                    "issn": object_row["issn"], "eissn": object_row["eissn"],
                    "source": RULE_VERSION}), actor_id),
        ).rowcount
        counters["journal_objects_created"] += inserted_object
        connection.execute(
            """UPDATE smartlib.journal_identity SET knowledge_object_id=%s
                 WHERE journal_id=%s AND knowledge_object_id IS NULL""",
            (object_id, journal_id),
        )

        for alias, variant_type in [(record.canonical_title, "canonical"),
                                    (str(publication["journal_name"]), "source")]:
            counters["name_variants_created"] += add_variant(
                connection, journal_id, alias, variant_type, actor_id, source_id
            )
        if publication["journal_abbreviation"]:
            counters["name_variants_created"] += add_variant(
                connection, journal_id, str(publication["journal_abbreviation"]),
                "abbreviation", actor_id, source_id
            )
        for alias, variant_type in record.aliases:
            counters["name_variants_created"] += add_variant(
                connection, journal_id, alias, variant_type, actor_id, source_id
            )

        relation_id = uuid5(NAMESPACE, f"published-in:{publication['publication_id']}:{object_id}")
        relation = connection.execute(
            """INSERT INTO smartlib.relation_assertion
                      (relation_id,subject_id,predicate,object_id,fact_class,confidence,visibility,
                       license_tags,review_state,model_version,attributes,created_by)
                 VALUES (%s,%s,'publication.published_in',%s,'vendor_record',1,'restricted',
                         %s,'approved',%s,%s,%s)
                 ON CONFLICT(subject_id) WHERE predicate='publication.published_in'
                   AND review_state='approved' AND system_to='infinity'
                 DO UPDATE SET object_id=excluded.object_id,fact_class=excluded.fact_class,
                   confidence=excluded.confidence,license_tags=excluded.license_tags,
                   attributes=excluded.attributes,model_version=excluded.model_version,
                   version=smartlib.relation_assertion.version+1
                 WHERE (smartlib.relation_assertion.object_id,
                        smartlib.relation_assertion.fact_class,
                        smartlib.relation_assertion.confidence,
                        smartlib.relation_assertion.license_tags,
                        smartlib.relation_assertion.attributes,
                        smartlib.relation_assertion.model_version)
                    IS DISTINCT FROM
                       (excluded.object_id,excluded.fact_class,excluded.confidence,
                        excluded.license_tags,excluded.attributes,excluded.model_version)
                 RETURNING relation_id,(xmax=0) AS inserted""",
            (relation_id, publication["publication_id"], object_id,
             ["crossref-metadata"] if record.source_code == "crossref_rest"
             else ["public-journal-metadata"], RULE_VERSION,
             Jsonb({"relation_label": "发表于",
                    "publication_year": publication["publication_year"] or record.publication_year,
                    "journal_name_raw": publication["journal_name"],
                    "match_basis": "issn" if record.issn else "eissn" if record.eissn
                    else "normalized_title"}), actor_id),
        ).fetchone()
        if relation is None:
            relation = connection.execute(
                """SELECT relation_id,false AS inserted FROM smartlib.relation_assertion
                     WHERE subject_id=%s AND predicate='publication.published_in'
                       AND review_state='approved' AND system_to='infinity'""",
                (publication["publication_id"],),
            ).fetchone()
        counters["relations_created"] += int(relation["inserted"])
        connection.execute(
            """INSERT INTO smartlib.relation_evidence(relation_id,evidence_id)
                 VALUES (%s,%s) ON CONFLICT DO NOTHING""",
            (relation["relation_id"], evidence_id),
        )

    counters["distinct_journals"] = len(journal_ids)
    result: dict[str, Any] = dict(counters)
    result["unresolved_identifiers"] = unresolved
    result["title_variant_details"] = title_variants
    if apply:
        connection.commit()
    else:
        connection.rollback()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crossref-dir", type=Path, required=True)
    parser.add_argument("--supplements", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = load_authority_records(args.crossref_dir, args.supplements)
    actor_id = UUID(os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001"))
    with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('smartlib.actor_id',%s,false)", (str(actor_id),))
        result = run(connection, records, actor_id, apply=args.apply)
    result.update({"applied": args.apply, "rule_version": RULE_VERSION,
                   "generated_at": datetime.now().astimezone().isoformat()})
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
