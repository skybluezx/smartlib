"""Verify awardee authorship, author roles, and DOI from preverified PDFs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pypinyin import Style, lazy_pinyin

RULE_VERSION = "publication-fulltext-author-verification-v1"
NAMESPACE = UUID("5ced2028-d556-48ee-b995-98b03b71bf35")
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
CHINESE_PATTERN = re.compile(r"[\u3400-\u9fff]")
COMPOUND_SURNAMES = {
    "欧阳",
    "司马",
    "上官",
    "诸葛",
    "东方",
    "皇甫",
    "尉迟",
    "公孙",
    "慕容",
    "令狐",
    "宇文",
    "长孙",
    "司徒",
    "司空",
    "夏侯",
    "南宫",
    "西门",
    "独孤",
    "太史",
    "端木",
}
EQUAL_PATTERN = re.compile(
    r"(?:contribut(?:ed|e)?\s+equally|equal\s+contribution|co[- ]?first\s+author)", re.I
)
STRONG_CORRESPONDING_PATTERN = re.compile(
    r"(?:^\s*[*†‡#+]*\s*(?:corresponding\s+authors?|correspondence)\s*:?\s*$"
    r"|^\s*[*†‡#+]*\s*corresponding\s+authors?\s*:\s*\S"
    r"|\bcorrespondence\s+(?:to|should\s+be\s+addressed\s+to)\b"
    r"|\bto\s+whom\s+correspondence\s+should\s+be\s+addressed\b)",
    re.I,
)
ROLE_MARKERS = ("†", "‡", "#", "+", "*")
PREPRINT_DOI_PREFIXES = ("10.21203/", "10.22541/")


def normalized_name(value: object) -> str:
    # Preserve non-Latin names: stripping Chinese characters collapses every
    # Chinese author to the same empty identity key.
    import unicodedata

    return "".join(char for char in unicodedata.normalize("NFKC", str(value or "")).casefold()
                   if char.isalnum())


def canonical_author_name(value: object) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    # The spreadsheet occasionally appends a duplicated name and Chinese field label in brackets.
    name = re.split(r"\s*[\uFF08(]", name, maxsplit=1)[0].strip()
    words = name.split()
    if len(words) >= 2 and len(words) % 2 == 0:
        middle = len(words) // 2
        if [word.casefold() for word in words[:middle]] == [word.casefold() for word in words[middle:]]:
            return " ".join(words[:middle])
    return name


def pinyin_forms(chinese_name: str) -> set[str]:
    clean = "".join(CHINESE_PATTERN.findall(chinese_name))
    if not clean:
        return set()
    tokens = lazy_pinyin(clean, style=Style.NORMAL, errors="ignore")
    surname_length = 2 if clean[:2] in COMPOUND_SURNAMES else 1
    surname = "".join(tokens[:surname_length])
    given = "".join(tokens[surname_length:])
    return {normalized_name(surname + given), normalized_name(given + surname)} - {""}


def author_word_orders(name: str) -> list[list[str]]:
    words = re.findall(r"[A-Za-z]+", canonical_author_name(name))
    if len(words) < 2:
        return [words]
    variants = [words, list(reversed(words)), words[1:] + words[:1], words[-1:] + words[:-1]]
    unique: list[list[str]] = []
    for variant in variants:
        if variant not in unique:
            unique.append(variant)
    return unique


def author_initials(name: str) -> set[str]:
    return {"".join(word[0] for word in words).upper() for words in author_word_orders(name) if words}


def author_pattern(name: str) -> re.Pattern[str]:
    orders = author_word_orders(name)
    if not orders or not orders[0]:
        return re.compile(r"(?!x)x")
    variants = [
        r"(?<![A-Za-z])" + r"[^A-Za-z0-9]{0,5}".join(map(re.escape, words)) + r"(?![A-Za-z])"
        for words in orders
    ]
    return re.compile("(?:" + "|".join(variants) + ")", re.I)


def clean_doi(value: str) -> str:
    return value.strip().rstrip(".,;:)]}").lower()


def normalize_detected_dois(values: list[str]) -> list[str]:
    cleaned = {clean_doi(value) for value in values}
    cleaned = {value for value in cleaned if not value.endswith("-")}
    # Publisher links can append an article-number path; supplementary files often append ds1.
    for value in list(cleaned):
        for base in list(cleaned):
            if value != base and (
                re.fullmatch(re.escape(base) + r"/\d+", value)
                or re.fullmatch(re.escape(base) + r"ds\d+", value)
            ):
                cleaned.discard(value)
                break
    return sorted(cleaned)


def extract_pdf_text(path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-f", "1", "-l", "3", "-layout", str(path), "-"],
        check=True,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=90,
    )
    return result.stdout.replace("\u00ad", "")


def resolve_path(reported: str, reported_root: Path, archive_root: Path) -> Path:
    return archive_root / Path(reported).relative_to(reported_root)


def match_awardee(awardee: str, authors: list[str], text: str) -> dict[str, Any]:
    forms = pinyin_forms(awardee)
    candidates = []
    text_normalized = normalized_name(text)
    for order, raw_name in enumerate(authors, start=1):
        name = canonical_author_name(raw_name)
        normalized = normalized_name(name)
        if normalized in forms:
            appears_in_fulltext = normalized in text_normalized or any(
                form in text_normalized for form in forms
            )
            candidates.append(
                {
                    "order": order,
                    "name": name,
                    "raw_name": raw_name,
                    "appears_in_fulltext": appears_in_fulltext,
                }
            )
    confirmed = len(candidates) == 1 and candidates[0]["appears_in_fulltext"]
    return {
        "status": "confirmed" if confirmed else "review_required",
        "awardee": awardee,
        "pinyin_forms": sorted(forms),
        "candidates": candidates,
        "selected_author_order": candidates[0]["order"] if confirmed else None,
        "selected_author_name": candidates[0]["name"] if confirmed else None,
    }


def _names_in_context(authors: list[str], context: str) -> set[int]:
    return {order for order, name in enumerate(authors, start=1) if author_pattern(name).search(context)}


def _initials_in_context(authors: list[str], context: str) -> set[int]:
    tokens = set(re.findall(r"(?<![A-Za-z])[A-Z](?:\.?[A-Z]){1,3}\.?(?![A-Za-z])", context))
    compact = {re.sub(r"[^A-Z]", "", token) for token in tokens}
    initials_by_order = [author_initials(name) for name in authors]
    counts = Counter(initial for values in initials_by_order for initial in values)
    return {
        order
        for order, values in enumerate(initials_by_order, start=1)
        if any(initial in compact and counts[initial] == 1 for initial in values)
    }


def _ordered_initials_in_statement(authors: list[str], line: str) -> set[int]:
    declaration = line.split(":", 1)[-1]
    declaration = re.split(r"contribut(?:ed|e)?\s+equally", declaration, flags=re.I)[0]
    tokens = [
        re.sub(r"[^A-Z]", "", token)
        for token in re.findall(r"(?<![A-Za-z])[A-Z](?:\.?[A-Z]){1,3}\.?(?![A-Za-z])", declaration)
    ]
    if len(tokens) < 2:
        return set()
    initials_by_order = [author_initials(name) for name in authors]
    selected: set[int] = set()
    previous = 0
    for token in tokens:
        candidates = [
            order
            for order, values in enumerate(initials_by_order, start=1)
            if order > previous and token in values
        ]
        if not candidates:
            return set()
        previous = candidates[0]
        selected.add(previous)
    return selected


def _abbreviated_names_in_context(authors: list[str], context: str) -> set[int]:
    matches: set[int] = set()
    for order, name in enumerate(authors, start=1):
        words = re.findall(r"[A-Za-z]+", canonical_author_name(name))
        if len(words) < 2:
            continue
        variants = (
            (words[0][0], words[-1]),
            (words[-1][0], words[0]),
        )
        if any(
            re.search(rf"(?<![A-Za-z]){re.escape(initial)}\.?\s+{re.escape(surname)}\b", context, re.I)
            for initial, surname in variants
        ):
            matches.add(order)
    return matches


def _marker_after_name(line: str, name: str, marker: str) -> bool:
    match = author_pattern(name).search(line)
    if not match:
        return False
    before = line[: match.start()].strip()
    tail = line[match.end() : match.end() + 14]
    if marker == "1":
        return bool(re.search(r"(?:^|[^0-9])1(?:[^0-9]|$)", tail))
    return bool(re.fullmatch(re.escape(marker), before)) or marker in tail


def extract_author_roles(authors: list[str], text: str) -> dict[str, Any]:
    lines = text.splitlines()[:180]
    equal_groups: list[set[int]] = []
    corresponding: set[int] = set()
    equal_evidence: list[str] = []
    corresponding_evidence: list[str] = []

    for index, line in enumerate(lines):
        equal_match = EQUAL_PATTERN.search(line)
        if equal_match:
            window_start = max(0, equal_match.start() - 240)
            window_end = min(len(line), equal_match.end() + 160)
            statement = line[window_start:window_end]
            equal_evidence.append(" ".join(statement.split())[:800])
            named = _names_in_context(authors, statement)
            initialed = _ordered_initials_in_statement(authors, statement) or _initials_in_context(
                authors, statement
            )
            equal_group = set(named or initialed)
            prefix = statement[: equal_match.start() - window_start].strip()
            markers = {marker for marker in ROLE_MARKERS if marker in prefix}
            previous = lines[index - 1].strip() if index else ""
            if not markers and re.fullmatch(r"(?:[*†‡#+]|\d+)", previous):
                markers.add(previous)
            for marker in markers:
                equal_group.update(
                    order
                    for order, name in enumerate(authors, start=1)
                    if any(_marker_after_name(author_line, name, marker) for author_line in lines[:80])
                )
            if 2 <= len(equal_group) <= 4:
                equal_groups.append(equal_group)

        corresponding_match = STRONG_CORRESPONDING_PATTERN.search(line)
        if corresponding_match:
            normalized_line = re.sub(r"\s+", " ", line).strip()
            has_inline_details = bool(
                re.search(r"(?:correspondence|corresponding\s+authors?)\s*:\s*\S", line, re.I)
            )
            is_header = bool(re.fullmatch(r"[*†‡#+]*\s*correspondence\s*:?", normalized_line, re.I))
            context_lines = [line]
            if has_inline_details or is_header:
                for following in lines[index + 1 : index + (6 if is_header else 3)]:
                    if EQUAL_PATTERN.search(following) or STRONG_CORRESPONDING_PATTERN.search(following):
                        break
                    context_lines.append(following)
            context = "\n".join(context_lines)
            corresponding_evidence.append(" ".join(context.split())[:800])
            corresponding.update(_names_in_context(authors, context))
            corresponding.update(_initials_in_context(authors, context))
            corresponding.update(_abbreviated_names_in_context(authors, context))
            declaration_prefix = (
                line[: corresponding_match.start()]
                + line[corresponding_match.start() : corresponding_match.end()]
            )
            equal_uses_star = any(evidence.lstrip().startswith("*") for evidence in equal_evidence)
            if "*" in declaration_prefix and not equal_uses_star:
                corresponding.update(
                    order
                    for order, name in enumerate(authors, start=1)
                    if any(_marker_after_name(author_line, name, "*") for author_line in lines[:80])
                )

    equal_uses_star = any(evidence.lstrip().startswith("*") for evidence in equal_evidence)
    if not equal_uses_star:
        for index, line in enumerate(lines[:80]):
            if not re.match(r"^\s*\*\s+", line):
                continue
            nearby = "\n".join(lines[index : index + 2])
            if "@" in nearby:
                corresponding.update(_names_in_context(authors, line))

    equal_contribution = set().union(*equal_groups) if equal_groups else set()
    first_groups = [group for group in equal_groups if 1 in group]
    co_first = min(first_groups, key=len) if first_groups else set()
    return {
        "first_author_orders": [1] if authors else [],
        "co_first_author_orders": sorted(co_first),
        "equal_contribution_orders": sorted(equal_contribution),
        "equal_contribution_groups": [sorted(group) for group in equal_groups],
        "corresponding_author_orders": sorted(corresponding),
        "co_corresponding_author": len(corresponding) > 1,
        "authors": [
            {
                "order": order,
                "name": canonical_author_name(name),
                "is_first_author": order == 1,
                "is_co_first_author": order in co_first,
                "is_corresponding_author": order in corresponding,
            }
            for order, name in enumerate(authors, start=1)
        ],
        "evidence": {
            "equal_contribution": equal_evidence,
            "corresponding_author": corresponding_evidence,
        },
    }


def verify_doi(source_doi: object, proposed_doi: object, text: str) -> dict[str, Any]:
    detected = normalize_detected_dois(DOI_PATTERN.findall(text))
    source = clean_doi(str(source_doi)) if source_doi else None
    proposed = clean_doi(str(proposed_doi)) if proposed_doi else None
    expected = source or proposed
    if expected and expected in detected:
        status = "confirmed"
        selected = expected
    elif not expected and len(detected) == 1:
        status = "confirmed"
        selected = detected[0]
    elif not expected and detected:
        article_dois = [value for value in detected if not value.startswith(PREPRINT_DOI_PREFIXES)]
        status = "confirmed" if len(article_dois) == 1 else "review_required"
        selected = article_dois[0] if len(article_dois) == 1 else None
    elif expected and detected:
        status = "conflict"
        selected = None
    else:
        status = "not_available"
        selected = None
    return {
        "status": status,
        "source_doi": source,
        "preverification_doi": proposed,
        "fulltext_dois": detected,
        "selected_doi": selected,
    }


def evaluate_record(match: dict[str, Any], item: dict[str, Any], text: str) -> dict[str, Any]:
    source = item["normalized_payload"]
    authors = [canonical_author_name(value) for value in source.get("authors_raw_list") or []]
    awardee = match_awardee(str(item["awardee_name_raw"] or ""), authors, text)
    roles = extract_author_roles(authors, text)
    proposed = item.get("proposed_identifiers") or {}
    doi = verify_doi(source.get("doi"), proposed.get("doi"), text)
    order = awardee.get("selected_author_order")
    awardee_roles = None
    if order:
        awardee_roles = next(value for value in roles["authors"] if value["order"] == order)
    return {
        "source_row_number": item["source_row_number"],
        "record_id": str(item["record_id"]),
        "file_name": match["file_name"],
        "content_checksum": match["sha256"],
        "awardee_match": awardee,
        "author_roles": roles,
        "awardee_roles": awardee_roles,
        "doi_verification": doi,
        "status": (
            "confirmed"
            if awardee["status"] == "confirmed" and doi["status"] in {"confirmed", "not_available"}
            else "review_required"
        ),
    }


def _merge_evidence(existing: object, value: str) -> list[str]:
    values = list(existing) if isinstance(existing, list) else []
    if value not in values:
        values.append(value)
    return values


def apply_result(connection, actor_id: UUID, item: dict[str, Any], result: dict[str, Any]) -> None:
    record_id = item["record_id"]
    attribution = connection.execute(
        """SELECT layer_id FROM smartlib.publication_verification_layer
            WHERE record_id=%s AND layer_code='attribution'""",
        (record_id,),
    ).fetchone()
    identity = connection.execute(
        """SELECT layer_id FROM smartlib.publication_verification_layer
            WHERE record_id=%s AND layer_code='identity'""",
        (record_id,),
    ).fetchone()
    if not attribution or not identity:
        raise ValueError("缺少论文身份或作者归属核验层")

    awardee = result["awardee_match"]
    roles = result["author_roles"]
    source_authors = item["normalized_payload"].get("authors_raw_list") or []
    candidates = roles["authors"]
    current = connection.execute(
        """SELECT evidence_sources,details FROM smartlib.publication_verification_check
            WHERE layer_id=%s AND check_code='awardee_author_match'""",
        (attribution["layer_id"],),
    ).fetchone()
    if not current:
        raise ValueError("缺少获批人作者身份核验项")
    connection.execute(
        """UPDATE smartlib.publication_verification_check SET
               check_status=%s,source_value=%s,authoritative_value=%s,
               evidence_sources=%s,details=%s,decision_reason=%s,
               decided_by=%s,decided_at=clock_timestamp()
             WHERE layer_id=%s AND check_code='awardee_author_match'""",
        (
            "passed" if awardee["status"] == "confirmed" else "pending",
            Jsonb(item["awardee_name_raw"]),
            Jsonb({"selected_author_order": awardee["selected_author_order"], "candidates": candidates}),
            Jsonb(_merge_evidence(current["evidence_sources"], "local_fulltext_preverification")),
            Jsonb(
                {
                    **(current["details"] or {}),
                    "automatic_pinyin_confirmation": awardee["status"] == "confirmed",
                    "pinyin_forms": awardee["pinyin_forms"],
                    "fulltext_author_name": awardee["selected_author_name"],
                    "rule_version": RULE_VERSION,
                }
            ),
            "获批人拼音与全文作者姓名唯一对应" if awardee["status"] == "confirmed" else None,
            actor_id if awardee["status"] == "confirmed" else None,
            attribution["layer_id"],
        ),
    )

    corresponding_status = "passed" if roles["corresponding_author_orders"] else "missing"
    connection.execute(
        """UPDATE smartlib.publication_verification_check SET
               check_status=%s,source_value=%s,authoritative_value=%s,
               evidence_sources=%s,details=%s,decision_reason=%s,
               decided_by=%s,decided_at=clock_timestamp()
             WHERE layer_id=%s AND check_code='corresponding_author'""",
        (
            corresponding_status,
            Jsonb(item["raw_payload"].get("SCI通讯作者")),
            Jsonb(
                {
                    "author_orders": roles["corresponding_author_orders"],
                    "authors": [value for value in candidates if value["is_corresponding_author"]],
                    "co_corresponding_author": roles["co_corresponding_author"],
                }
            ),
            Jsonb(["controlled_excel", "local_fulltext_preverification"]),
            Jsonb({"evidence": roles["evidence"]["corresponding_author"], "rule_version": RULE_VERSION}),
            "根据全文通讯作者声明和作者标记自动提取" if corresponding_status == "passed" else None,
            actor_id if corresponding_status == "passed" else None,
            attribution["layer_id"],
        ),
    )

    role_status = "passed" if candidates else "missing"
    check_id = uuid5(NAMESPACE, f"author-roles:{record_id}")
    connection.execute(
        """INSERT INTO smartlib.publication_verification_check
                  (check_id,layer_id,check_code,check_label,check_status,severity,source_value,
                   authoritative_value,evidence_sources,details,decision_reason,decided_by,
                   decided_at,created_by)
             VALUES (%s,%s,'fulltext_author_roles','全文作者角色',%s,'warning',%s,%s,%s,%s,%s,%s,
                     CASE WHEN %s='passed' THEN clock_timestamp() ELSE NULL END,%s)
             ON CONFLICT (layer_id,check_code) DO UPDATE SET
               check_status=excluded.check_status,source_value=excluded.source_value,
               authoritative_value=excluded.authoritative_value,
               evidence_sources=excluded.evidence_sources,details=excluded.details,
               decision_reason=excluded.decision_reason,decided_by=excluded.decided_by,
               decided_at=excluded.decided_at""",
        (
            check_id,
            attribution["layer_id"],
            role_status,
            Jsonb(source_authors),
            Jsonb(roles),
            Jsonb(["local_fulltext_preverification"]),
            Jsonb({"rule_version": RULE_VERSION}),
            "根据全文作者顺序和角色声明提取",
            actor_id if role_status == "passed" else None,
            role_status,
            actor_id,
        ),
    )

    doi = result["doi_verification"]
    doi_status = {"confirmed": "passed", "conflict": "conflict"}.get(doi["status"], "missing")
    check_id = uuid5(NAMESPACE, f"doi:{record_id}")
    connection.execute(
        """INSERT INTO smartlib.publication_verification_check
                  (check_id,layer_id,check_code,check_label,check_status,severity,source_value,
                   authoritative_value,evidence_sources,details,decision_reason,decided_by,
                   decided_at,created_by)
             VALUES (%s,%s,'fulltext_doi_identity','全文DOI核对',%s,'blocking',%s,%s,%s,%s,%s,%s,
                     CASE WHEN %s='passed' THEN clock_timestamp() ELSE NULL END,%s)
             ON CONFLICT (layer_id,check_code) DO UPDATE SET
               check_status=excluded.check_status,source_value=excluded.source_value,
               authoritative_value=excluded.authoritative_value,
               evidence_sources=excluded.evidence_sources,details=excluded.details,
               decision_reason=excluded.decision_reason,decided_by=excluded.decided_by,
               decided_at=excluded.decided_at""",
        (
            check_id,
            identity["layer_id"],
            doi_status,
            Jsonb(doi["source_doi"]),
            Jsonb({"selected_doi": doi["selected_doi"], "detected_dois": doi["fulltext_dois"]}),
            Jsonb(["local_fulltext_preverification"]),
            Jsonb({"preverification_doi": doi["preverification_doi"], "rule_version": RULE_VERSION}),
            "全文首页DOI与预核验候选一致" if doi_status == "passed" else None,
            actor_id if doi_status == "passed" else None,
            doi_status,
            actor_id,
        ),
    )

    pre = connection.execute(
        """SELECT checks FROM smartlib.publication_fulltext_preverification
            WHERE record_id=%s AND content_checksum=%s""",
        (record_id, result["content_checksum"]),
    ).fetchone()
    if pre:
        retained = [
            value
            for value in pre["checks"]
            if value.get("code")
            not in {"awardee_pinyin_identity", "fulltext_author_roles", "fulltext_doi_identity"}
        ]
        retained.extend(
            [
                {
                    "code": "awardee_pinyin_identity",
                    "label": "获批人拼音对应",
                    "status": "passed" if awardee["status"] == "confirmed" else "review_required",
                    "source_value": item["awardee_name_raw"],
                    "fulltext_value": {
                        "author_order": awardee["selected_author_order"],
                        "author_name": awardee["selected_author_name"],
                    },
                    "reason": "中文姓名拼音与全文作者姓名唯一对应"
                    if awardee["status"] == "confirmed"
                    else "未形成唯一且可在全文中定位的拼音对应",
                },
                {
                    "code": "fulltext_author_roles",
                    "label": "全文作者角色",
                    "status": role_status,
                    "source_value": source_authors,
                    "fulltext_value": roles,
                    "reason": "从作者顺序、共同贡献和通讯作者声明提取",
                },
                {
                    "code": "fulltext_doi_identity",
                    "label": "全文DOI核对",
                    "status": doi_status,
                    "source_value": doi["source_doi"],
                    "fulltext_value": doi,
                    "reason": "全文首页DOI与来源或预核验候选一致"
                    if doi_status == "passed"
                    else "全文DOI仍需人工处理",
                },
            ]
        )
        connection.execute(
            """UPDATE smartlib.publication_fulltext_preverification SET checks=%s
                WHERE record_id=%s AND content_checksum=%s""",
            (Jsonb(retained), record_id, result["content_checksum"]),
        )

    connection.execute(
        """UPDATE smartlib.publication_verification_layer AS layer SET
               check_count=s.total,passed_count=s.passed,conflict_count=s.conflicts,
               missing_count=s.missing,layer_status=CASE
                 WHEN s.blocking_conflicts>0 THEN 'conflict'
                 WHEN s.blocking_open>0 THEN 'incomplete'
                 WHEN layer.layer_code='enrichment' AND s.missing>0 THEN 'incomplete'
                 ELSE 'passed' END,evaluated_at=clock_timestamp()
             FROM (SELECT layer_id,count(*) total,
                          count(*) FILTER (WHERE check_status='passed') passed,
                          count(*) FILTER (WHERE check_status='conflict') conflicts,
                          count(*) FILTER (WHERE check_status IN ('missing','pending')) missing,
                          count(*) FILTER (
                            WHERE severity='blocking' AND check_status='conflict'
                          ) blocking_conflicts,
                          count(*) FILTER (
                            WHERE severity='blocking' AND check_status IN ('missing','pending')
                          ) blocking_open
                     FROM smartlib.publication_verification_check GROUP BY layer_id) s
            WHERE layer.layer_id=s.layer_id AND layer.record_id=%s""",
        (record_id,),
    )
    connection.execute(
        """INSERT INTO audit.audit_event
                  (actor_id,action,resource_type,resource_id,decision,trace_id,details)
             VALUES (%s,'publication.fulltext.author_roles.verified',
                     'publication_intake_record',%s,'allowed',%s,%s)
             """,
        (
            actor_id,
            str(record_id),
            RULE_VERSION,
            Jsonb(
                {
                    "checksum": result["content_checksum"],
                    "awardee_status": awardee["status"],
                    "doi_status": doi["status"],
                }
            ),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="从论文全文核验获批人作者身份、角色与DOI")
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--reported-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    matches = json.loads(args.matches.read_text(encoding="utf-8"))
    actor_id = UUID(os.environ.get("SMARTLIB_DEV_ACTOR_ID", "00000000-0000-4000-8000-000000000001"))
    outcomes: list[dict[str, Any]] = []
    with psycopg.connect(os.environ["SMARTLIB_DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('smartlib.actor_id', %s, false)", (str(actor_id),))
        connection.commit()
        for match in matches:
            item = connection.execute(
                """SELECT item.record_id,COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer) AS source_row_number,
                          submission.awardee_name_raw,
                          input_record.normalized_payload,input_record.raw_payload,pre.proposed_identifiers
                     FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
                     JOIN smartlib.publication_fulltext_preverification pre USING(record_id)
                    WHERE COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer)=%s
                          AND pre.content_checksum=%s
                      AND pre.preverification_status='ready'""",
                (match["source_row_number"], match["sha256"]),
            ).fetchone()
            if not item:
                continue
            try:
                path = resolve_path(match["archive_path"], args.reported_root, args.archive_root)
                result = evaluate_record(match, item, extract_pdf_text(path))
                if args.apply:
                    with connection.transaction():
                        connection.execute(
                            "SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),)
                        )
                        apply_result(connection, actor_id, item, result)
                    result["applied"] = True
                outcomes.append(result)
                print(
                    f"[{len(outcomes)}] row {item['source_row_number']}: {result['status']}",
                    flush=True,
                )
            except Exception as exc:
                connection.rollback()
                outcomes.append(
                    {
                        "source_row_number": item["source_row_number"],
                        "record_id": str(item["record_id"]),
                        "file_name": match["file_name"],
                        "status": "failed",
                        "error": str(exc),
                    }
                )
    counts: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        counts[outcome["status"]] += 1
    role_counts = {
        "awardee_first_author": sum(
            bool((value.get("awardee_roles") or {}).get("is_first_author")) for value in outcomes
        ),
        "awardee_co_first_author": sum(
            bool((value.get("awardee_roles") or {}).get("is_co_first_author")) for value in outcomes
        ),
        "awardee_corresponding_author": sum(
            bool((value.get("awardee_roles") or {}).get("is_corresponding_author")) for value in outcomes
        ),
        "papers_with_co_first_authors": sum(
            bool(value.get("author_roles", {}).get("co_first_author_orders")) for value in outcomes
        ),
        "papers_with_corresponding_authors": sum(
            bool(value.get("author_roles", {}).get("corresponding_author_orders")) for value in outcomes
        ),
        "papers_with_co_corresponding_authors": sum(
            bool(value.get("author_roles", {}).get("co_corresponding_author")) for value in outcomes
        ),
    }
    report = {
        "schema_version": RULE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "fulltext_preverification_ready",
        "applied": args.apply,
        "counts": counts,
        "role_counts": role_counts,
        "records": outcomes,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"counts": counts, "role_counts": role_counts}, ensure_ascii=False))
    if counts["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
