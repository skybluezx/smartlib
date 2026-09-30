"""Read-only author and affiliation candidate helpers. No materialization entry point."""

import re
from collections import defaultdict
from typing import Any
from uuid import UUID, uuid5

from run_fulltext_author_verification import author_pattern, canonical_author_name
from run_fulltext_author_verification import normalized_name as normalized_name

RULE_VERSION = "fulltext-author-affiliation-materialization-v1"


NAMESPACE = UUID("ae53fe31-4873-4bf3-a6e6-e21aa7141dcf")


PUBLICATION_NAMESPACE = UUID("df2fabc9-b9bb-4dcc-8e11-3460ca0871fa")


ORG_WORDS = re.compile(
    r"\b(?:university|hospital|institute|academy|college|school|laborator(?:y|ies)|"
    r"centre|center|clinic|faculty|department|division)\b|"
    r"(?:大学|医院|学院|研究所|科学院|实验室|中心|附属|科室)",
    re.I,
)


ENGLISH_ORGANIZATION = re.compile(
    r"(?<![A-Za-z])(?:University|Institute|Academy|College)\s+of\s+"
    r"(?:[A-Z][A-Za-z&'().-]*\s*){1,4}"
    r"|(?<![A-Za-z])(?:The\s+)?(?:[A-Z][A-Za-z&'().-]*\s+){1,8}?"
    r"(?:University|Hospital|Institute|Academy|College|Centre|Center)"
    r"(?:\s+of\s+(?:[A-Z][A-Za-z&'().-]*\s*){1,4})?",
)


CHINESE_ORGANIZATION = re.compile(
    r"[\u3400-\u9fffA-Za-z0-9·\uff08\uff09()]{2,50}(?:大学|医院|学院|研究所|科学院|实验室|中心)"
)


GENERIC_ORGANIZATIONS = {
    "university",
    "hospital",
    "institute",
    "academy",
    "college",
    "center",
    "centre",
    "clinic",
    "laboratory",
    "laboratories",
    "department",
}


GENERIC_QUALIFIED_ORGANIZATION = re.compile(
    r"^(?:the|first|second|third|cancer|medical|national|research|chinese)\s+"
    r"(?:university|hospital|institute|academy|college|center|centre)$",
    re.I,
)


STOP_LINE = re.compile(r"^\s*(?:abstract|summary|keywords?|introduction|背景|摘要|关键词)\b", re.I)


MARKER_PREFIX = re.compile(r"^\s*([0-9a-z*†‡#+,;\s]{1,14})\s*[.)]?\s+", re.I)


def compact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalized_entity_name(value: object) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", str(value or "").casefold())


def display_author_name(value: object) -> str:
    raw = compact(value)
    without_source_number = re.sub(r"^\(\d+\)\s*", "", raw)
    return canonical_author_name(without_source_number) or without_source_number


def marker_tokens(value: str) -> set[str]:
    value = value.translate(str.maketrans("¹²³⁴⁵⁶⁷⁸⁹⁰", "1234567890"))
    return {token.casefold() for token in re.findall(r"\d+|[a-z]|[*†‡#+]", value, re.I) if token}


def organization_names(raw: str) -> list[str]:
    """Keep recognizable institutional units while discarding postal/address fragments."""
    cleaned = compact(re.sub(r"\S+@\S+", "", raw)).strip(" ,;.*†‡#")
    if not cleaned or re.search(r"https?://|doi\.org|\babstract\b|\bdownloaded\s+from\b", cleaned, re.I):
        return []
    selected = [match.group(0) for match in ENGLISH_ORGANIZATION.finditer(cleaned)]
    selected.extend(match.group(0) for match in CHINESE_ORGANIZATION.finditer(cleaned))
    output: list[str] = []
    for name in sorted(selected, key=len, reverse=True):
        name = re.sub(r"^\s*(?:\d+|[*†‡#+])+\s*[.)]?\s*", "", name)
        name = compact(name).strip(" (),;.")
        normalized = normalized_entity_name(name)
        if (
            5 <= len(name) <= 180
            and name.casefold() not in GENERIC_ORGANIZATIONS
            and not GENERIC_QUALIFIED_ORGANIZATION.fullmatch(name)
            and not name.casefold().startswith(("of ", "from ", "author at"))
            and normalized
            and not any(normalized in normalized_entity_name(item) for item in output)
            and name.casefold() not in {item.casefold() for item in output}
        ):
            output.append(name)
    output.sort(key=lambda item: cleaned.casefold().find(item.casefold()))
    return output[:4]


def extract_affiliations(authors: list[str], text: str) -> dict[int, list[dict[str, object]]]:
    lines = text.splitlines()[:180]
    affiliation_lines: list[tuple[set[str], str, list[str]]] = []
    for line in lines:
        if STOP_LINE.search(line):
            break
        if not ORG_WORDS.search(line):
            continue
        value = compact(line)
        if len(value) < 5 or len(value) > 700:
            continue
        prefix = MARKER_PREFIX.match(value)
        markers = marker_tokens(prefix.group(1)) if prefix else set()
        names = organization_names(value)
        if names:
            affiliation_lines.append((markers, value, names))

    by_author_markers: dict[int, set[str]] = defaultdict(set)
    header = "\n".join(lines[:80])
    for order, name in enumerate(authors, start=1):
        for match in author_pattern(name).finditer(header):
            tail = header[match.end() : match.end() + 22]
            marker_region = re.split(r"[,;\n]", tail, maxsplit=1)[0]
            by_author_markers[order].update(marker_tokens(marker_region))

    distinct = {name.casefold() for _, _, names in affiliation_lines for name in names}
    assignments: dict[int, list[dict[str, object]]] = defaultdict(list)
    for order in range(1, len(authors) + 1):
        for markers, raw, names in affiliation_lines:
            method: str | None = None
            confidence = 0.0
            if markers and markers & by_author_markers.get(order, set()):
                method, confidence = "fulltext_marker", 0.92
            elif len(distinct) == 1:
                method, confidence = "single_fulltext_affiliation", 0.90
            if method:
                for name in names:
                    assignments[order].append(
                        {"organization_name": name, "raw": raw, "method": method, "confidence": confidence}
                    )
    return assignments


def metadata_affiliation_assignments(raw: str) -> list[dict[str, object]]:
    names = organization_names(raw)
    if len(raw) > 350 or len(names) > 3:
        return []
    return [
        {
            "organization_name": name,
            "raw": raw,
            "method": "existing_author_affiliation",
            "confidence": 0.96,
        }
        for name in names
    ]


def fulltext_name_status(name: str, text: str) -> str:
    return "confirmed" if author_pattern(name).search(text[:30000]) else "not_detected"


def roles_for(order: int, role_result: dict[str, Any]) -> list[str]:
    roles = []
    if order in role_result["first_author_orders"]:
        roles.append("first_author")
    if order in role_result["co_first_author_orders"]:
        roles.append("co_first_author")
    if order in role_result["corresponding_author_orders"]:
        roles.append("corresponding_author")
        if role_result["co_corresponding_author"]:
            roles.append("co_corresponding_author")
    if not roles:
        roles.append("author")
    return roles


def author_person_id(
    connection,
    author: dict[str, Any],
    awardees: list[dict[str, Any]],
    affiliation_names: list[str],
) -> tuple[UUID, str]:
    normalized = normalized_name(display_author_name(author["author_name_raw"]))
    if not normalized:
        raise ValueError("Author has no usable name; identity review is required")
    if author["person_object_id"]:
        existing = connection.execute(
            """SELECT canonical_name FROM smartlib.knowledge_object
                 WHERE object_id=%s AND object_type='person'""",
            (author["person_object_id"],),
        ).fetchone()
        if existing and normalized == normalized_name(display_author_name(existing["canonical_name"])):
            return author["person_object_id"], "existing_authorship_link"
        # Do not silently preserve an unrelated identity, or override it using
        # pinyin alone. Different scripts/names require an explicit review.
        raise ValueError(f"Author identity/name conflict at slot {author['publication_authorship_id']}")
    if author["orcid"]:
        row = connection.execute(
            """SELECT object_id FROM smartlib.knowledge_object
                WHERE object_type='person' AND lower(attributes->>'orcid')=lower(%s)
                  AND system_to='infinity'::timestamptz ORDER BY object_id LIMIT 1""",
            (author["orcid"],),
        ).fetchone()
        if row:
            return row["object_id"], "orcid"
    # Names (including identical English names) are not global person IDs.
    identity = (
        f"orcid:{author['orcid']}" if author["orcid"] else f"authorship:{author['publication_authorship_id']}"
    )
    return uuid5(NAMESPACE, f"person:{identity}"), "new_provisional_authorship_identity"
