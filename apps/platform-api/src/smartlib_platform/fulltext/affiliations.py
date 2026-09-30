"""Deterministic affiliation parsing with address removal and hierarchy preservation."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"})
ORG_TERM = re.compile(
    r"\b(?:university|hospital|institute|academy|college|school|faculty|department|"
    r"division|clinic|laborator(?:y|ies)|centre|center)\b|"
    r"(?:大学|医院|学院|研究所|科学院|实验室|中心|附属|科室|学部|系)",
    re.I,
)
ROOT_TERM = re.compile(
    r"\b(?:university|hospital|institute|academy|clinic)\b|"
    r"(?:大学|医院|研究所|科学院)",
    re.I,
)
UNIT_START = re.compile(
    r"^(?:department|school|college|faculty|division|institute|laborator(?:y|ies)|key laboratory|"
    r"state key laboratory|center|centre|research center|research centre|program|"
    r"department of|school of|college of|faculty of|division of|laboratory of|"
    r"科室|学院|实验室|中心|系)\b",
    re.I,
)
REJECT_CONTEXT = re.compile(
    r"downloaded\s+from|published\s+by|on\s+behalf\s+of|creative\s+commons|"
    r"copyright|all\s+rights\s+reserved|ethics\s+committee|institutional\s+review\s+board|"
    r"received:|accepted:|https?://|\bdoi\.org\b|peer\s+review\s+under|"
    r"orcid\s+identification|\bbiosafety\s+committee\b|\bpatients?\s+(?:who|were|with)\b|"
    r"\b(?:mice|cells?)\s+were\b|"
    r"\b(?:the|this)\s+study\b|\bapproval\s+(?:no|number)\b",
    re.I,
)
ADDRESS_TERM = re.compile(
    r"\b(?:road|rd\.?|street|st\.?|avenue|ave\.?|boulevard|district|province|postcode|"
    r"postal|zip|p\.?\s*r\.?\s*china|china|usa|u\.?s\.?a|united states|united kingdom|"
    r"japan|korea|germany|france|italy|australia|canada|singapore|sweden|india|iran|"
    r"pakistan|malaysia|spain|belgium|netherlands|switzerland|turkey|brazil)\b|"
    r"(?:中国|美国|英国|日本|韩国|德国|法国|意大利|澳大利亚|加拿大|新加坡|瑞典|印度|伊朗|"
    r"巴基斯坦|马来西亚|西班牙|比利时|荷兰|瑞士|土耳其|巴西|省|市|区|路|号)",
    re.I,
)
POSTAL_CODE = re.compile(r"(?<!\d)(?:\d{5,6}|[A-Z]\d[A-Z]\s*\d[A-Z]\d)(?!\d)", re.I)
TRUNCATED_END = re.compile(
    r"\b(?:of|at|and|the|medical|integrative|institute of|university of|institutes of)\s*$",
    re.I,
)
NOISY_LEAD = re.compile(
    r"^(?:published\b|address\s+correspondence\b|corresponding\s+author\b|"
    r"to\s+this\s+work\b|from\b|\d+\s+)",
    re.I,
)
NOISY_ANYWHERE = re.compile(r"\b(?:citation|specialty\s+section)\b", re.I)
GENERIC_ROOT = re.compile(
    r"^(?:the\s+)?(?:university|hospital|institute|academy|clinic|affiliated hospital|"
    r"first affiliated hospital|second affiliated hospital|third affiliated hospital|"
    r"first hospital|second hospital|third hospital)$",
    re.I,
)
GENERIC_QUALIFIED_ROOT = re.compile(
    r"^(?:medical|agricultural|pharmaceutical|normal)\s+university$|"
    r"^(?:university|affiliated|cancer|advanced|research|medical)\s+"
    r"(?:hospital|institute|college)$",
    re.I,
)
LIKELY_CITY_END = re.compile(
    r"\b(?:Dalian|Beijing|Shanghai|Wuhan|Shenyang|Hangzhou|Kaifeng|Guangzhou|Suzhou|"
    r"Ningbo|Nanjing|Chengdu|Fuzhou|Ganzhou|Harbin|Qingdao|Shenzhen|Tianjin|Wenzhou)\s*$",
    re.I,
)
ROOT_NAME_END = re.compile(
    r"(?:\bUniversity(?:\s+of\s+[A-Za-z'\u2019.-]+(?:\s+[A-Za-z'\u2019.-]+){0,5})?|"
    r"\bHospital(?:\s+of\s+[A-Za-z'\u2019.-]+(?:\s+[A-Za-z'\u2019.-]+){0,5})?|"
    r"\bInstitute(?:\s+of\s+[A-Za-z'\u2019.-]+(?:\s+[A-Za-z'\u2019.-]+){0,5})?|"
    r"\bAcademy(?:\s+of\s+[A-Za-z'\u2019.-]+(?:\s+[A-Za-z'\u2019.-]+){0,5})?|"
    r"\bClinic|大学|医院|研究所|科学院)$",
    re.I,
)
EMAIL = re.compile(r"\b\S+@\S+\b")
AUTHOR_INITIALS_PAREN = re.compile(
    r"\(\s*(?=[^)]*\.)[A-Z][A-Z.,\-\s]*\)",
    re.I,
)
MARKER_SPLIT = re.compile(
    r"(?:\s*[|;]\s*|(?<=[.;)])\s+(?=\d{1,2}\s*(?:department|school|college|faculty|"
    r"division|laborator|center|centre|institute|hospital|university)\b))",
    re.I,
)
PREFIX = re.compile(
    r"^\s*(?:(?:\*+\s*)?corresponding authors?\s*[:.]?\s*)?"
    r"(?:\d{1,2}|[*†‡#+])+\s*[.)]?\s*",
    re.I,
)
LEADING_CONTEXT = re.compile(
    r"^\s*(?:from\s+the\s+|from\s+|address\s+correspondence\s+to\s*:\s*|"
    r"corresponding\s+authors?\s+(?:at|address)\s*:\s*|"
    r"published\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+|"
    r"to\s+this\s+work(?:\s+and\s+shared\s+the\s+first)?\s+)",
    re.I,
)
COUNTRY_MARKER_BOUNDARY = re.compile(
    r"\s*,\s*(?:P\.?\s*R\.?\s*)?(?:China|USA|U\.?S\.?A|United States|United Kingdom|"
    r"Japan|Korea|Germany|France|Italy|Australia|Canada|Singapore)\s*[,.;]\s*"
    r"(?=\d{1,2}\s*[A-Z])",
    re.I,
)


@dataclass(frozen=True)
class ParsedAffiliation:
    raw: str
    canonical_name: str
    hierarchy: tuple[str, ...]
    address: str | None
    confidence: float
    issues: tuple[str, ...]

    @property
    def root_name(self) -> str:
        return self.hierarchy[0]


def compact(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).translate(LIGATURES)
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def identity_key(value: object) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", compact(value).casefold())


def split_affiliation_values(value: object) -> list[str]:
    cleaned = compact(EMAIL.sub("", str(value or "")))
    if not cleaned:
        return []
    country_chunks = COUNTRY_MARKER_BOUNDARY.split(cleaned)
    return [
        item.strip(" ,;|.")
        for chunk in country_chunks
        for item in MARKER_SPLIT.split(chunk)
        if item.strip(" ,;|.")
    ]


def _address_component(value: str) -> bool:
    text = compact(value).strip(" ,;.")
    if not text:
        return True
    if POSTAL_CODE.search(text) or ADDRESS_TERM.search(text):
        return True
    return bool(re.fullmatch(r"[A-Z]{2,3}", text))


def _clean_organization_span(value: str) -> tuple[str, str | None, list[str]]:
    value = compact(value).strip(" ,;.*†‡#+")
    value = LEADING_CONTEXT.sub("", value)
    value = PREFIX.sub("", value).strip(" ,;.")
    value = AUTHOR_INITIALS_PAREN.sub("", value)
    value = re.sub(
        r"\b(?:e-?mail|tel(?:ephone)?|fax)\s*[:\uff1a].*$", "", value, flags=re.I
    )
    value = re.split(r"\.\s+(?:This|These|The authors?|Correspondence)\b", value, maxsplit=1)[0]
    if not value or REJECT_CONTEXT.search(value):
        return "", None, []

    comma_parts = [compact(item).strip(" ,;.") for item in re.split(r"\s*,\s*", value)]
    comma_parts = [
        PREFIX.sub("", item).strip(" ,;.") if ORG_TERM.search(item) else item
        for item in comma_parts
    ]
    comma_parts = [item for item in comma_parts if item]
    organization_indexes = [index for index, item in enumerate(comma_parts) if ORG_TERM.search(item)]
    if organization_indexes:
        first, last = min(organization_indexes), max(organization_indexes)
        organization_parts = comma_parts[first : last + 1]
        trailing = comma_parts[last + 1 :]
        # A postal/address component inside an apparent hierarchy terminates the
        # institutional span; later text belongs to the address or next column.
        for index, item in enumerate(organization_parts):
            if index > 0 and _address_component(item) and not ORG_TERM.search(item):
                trailing = organization_parts[index:] + trailing
                organization_parts = organization_parts[:index]
                break
        canonical = ", ".join(organization_parts)
        address = ", ".join(trailing) or None
    else:
        canonical = value
        address = None

    postal = POSTAL_CODE.search(canonical)
    if postal:
        address = compact(canonical[postal.start() :] + (f", {address}" if address else ""))
        canonical = canonical[: postal.start()].rstrip(" ,;.")
    canonical = re.sub(
        r"\s+(?:P\.?\s*R\.?\s*China|China|USA|U\.?S\.?A|United States|United Kingdom|"
        r"Japan|Korea|Germany|France|Italy|Australia|Canada|Singapore)\s*$",
        "",
        canonical,
        flags=re.I,
    ).rstrip(" ,;.")
    canonical = re.sub(r"\s+", " ", canonical)
    return canonical, address, comma_parts


def discover_root_hints(values: Iterable[object]) -> tuple[str, ...]:
    candidates: dict[str, str] = {}
    for value in values:
        for item in split_affiliation_values(value):
            canonical, _, comma_parts = _clean_organization_span(item)
            if not canonical:
                continue
            for component in comma_parts or [canonical]:
                component = compact(component).strip(" ,;.")
                if (
                    ROOT_TERM.search(component)
                    and ROOT_NAME_END.search(component)
                    and not UNIT_START.search(component)
                    and not POSTAL_CODE.search(component)
                    and not REJECT_CONTEXT.search(component)
                    and not NOISY_LEAD.search(component)
                    and not TRUNCATED_END.search(component)
                    and not GENERIC_ROOT.fullmatch(component)
                    and not GENERIC_QUALIFIED_ROOT.fullmatch(component)
                    and not LIKELY_CITY_END.search(component)
                    and len(ORG_TERM.findall(component)) <= 2
                    and len(component) <= 140
                ):
                    candidates.setdefault(identity_key(component), component)
    return tuple(sorted(candidates.values(), key=lambda item: (-len(identity_key(item)), item)))


def _root_from_hints(canonical: str, root_hints: Iterable[str]) -> str | None:
    normalized = identity_key(canonical)
    matches = [
        hint
        for hint in root_hints
        if not GENERIC_ROOT.fullmatch(compact(hint))
        and not GENERIC_QUALIFIED_ROOT.fullmatch(compact(hint))
        and len(identity_key(hint)) >= 8
        and identity_key(hint) in normalized
    ]
    if not matches:
        return None
    def score(item: str) -> tuple[int, int, int]:
        lowered = item.casefold()
        rank = (
            3
            if re.search(r"(?:university|academy|大学|科学院)\s*$", lowered, re.I)
            else 2
        )
        key = identity_key(item)
        return rank, normalized.rfind(key) + len(key), -len(key)

    # Prefer a parent university/academy contained inside an affiliated hospital
    # name; otherwise prefer the institution appearing latest in the signature.
    return max(matches, key=score)


def _fallback_root(canonical: str) -> str:
    parts = [item.strip() for item in canonical.split(",") if item.strip()]
    for item in reversed(parts):
        if ROOT_TERM.search(item) and not UNIT_START.search(item):
            return item
    university_of = list(
        re.finditer(
            r"\bUniversity\s+of\s+(?:[A-Z][\w'\u2019.-]*(?:\s+|$)){1,5}", canonical
        )
    )
    if university_of:
        return university_of[-1].group(0).strip()
    academy_of = list(
        re.finditer(
            r"\b(?:[A-Z][\w'\u2019.-]+\s+){1,4}Academy\s+of\s+Sciences\b", canonical
        )
    )
    if academy_of:
        return academy_of[-1].group(0).strip()
    # When no safe parent can be isolated, retain the full institutional name.
    # This avoids inventing a parent and is surfaced for review.
    return canonical


def _hierarchy(canonical: str, root: str) -> tuple[str, ...]:
    if identity_key(canonical) == identity_key(root):
        return (canonical,)
    parts = [item.strip() for item in canonical.split(",") if item.strip()]
    root_index = next(
        (index for index, item in enumerate(parts) if identity_key(root) in identity_key(item)),
        None,
    )
    if root_index is None:
        return (root, canonical)

    hierarchy: list[str] = [root]
    parent = parts[root_index]
    if identity_key(parent) != identity_key(root):
        hierarchy.append(parent)
    for index in range(root_index - 1, -1, -1):
        child = ", ".join(parts[index : root_index + 1])
        if identity_key(child) not in {identity_key(item) for item in hierarchy}:
            hierarchy.append(child)
    if identity_key(hierarchy[-1]) != identity_key(canonical):
        hierarchy.append(canonical)
    return tuple(hierarchy)


def parse_affiliation(
    value: object,
    *,
    root_hints: Iterable[str] = (),
    source_confidence: float = 0.9,
) -> list[ParsedAffiliation]:
    parsed: list[ParsedAffiliation] = []
    for raw in split_affiliation_values(value):
        canonical, address, _ = _clean_organization_span(raw)
        if not canonical or not ORG_TERM.search(canonical):
            continue
        issues: list[str] = []
        root = _root_from_hints(canonical, root_hints) or _fallback_root(canonical)
        repeated_root = re.compile(
            rf"({re.escape(root)})(?:\s*,?\s*)\1",
            re.I,
        )
        canonical = repeated_root.sub(root, canonical)
        parts = [item.strip() for item in canonical.split(",") if item.strip()]
        root_parts = [
            index for index, item in enumerate(parts) if identity_key(root) in identity_key(item)
        ]
        if len(root_parts) > 1:
            start = 0
            segmented: list[ParsedAffiliation] = []
            for index in root_parts:
                segment = ", ".join(parts[start : index + 1])
                if segment:
                    segmented.extend(
                        parse_affiliation(
                            segment,
                            root_hints=root_hints,
                            source_confidence=source_confidence,
                        )
                    )
                start = index + 1
            if segmented:
                parsed.extend(segmented)
                continue
        root_position = canonical.casefold().rfind(root.casefold())
        if root_position >= 0:
            root_end = root_position + len(root)
            trailing_text = canonical[root_end:].strip(" ,;.")
            if trailing_text and not ORG_TERM.search(trailing_text):
                address = compact(
                    trailing_text + (f", {address}" if address else "")
                ) or None
                canonical = canonical[:root_end].rstrip(" ,;.")
        hierarchy = _hierarchy(canonical, root)
        if identity_key(root) == identity_key(canonical) and UNIT_START.search(canonical):
            issues.append("parent_not_resolved")
        if _address_component(canonical) and not ROOT_TERM.search(canonical):
            issues.append("possible_address_contamination")
        if NOISY_LEAD.search(canonical):
            issues.append("context_contamination")
        if TRUNCATED_END.search(canonical):
            issues.append("truncated_institution")
        if (
            GENERIC_ROOT.fullmatch(root)
            or GENERIC_QUALIFIED_ROOT.fullmatch(root)
            or NOISY_ANYWHERE.search(canonical)
        ):
            issues.append("generic_or_contextual_root")
        if LIKELY_CITY_END.search(canonical) or re.search(
            r"\b(?:China|USA|United States|Singapore)\s*$", canonical, re.I
        ):
            issues.append("address_tail_not_resolved")
        parsed.append(
            ParsedAffiliation(
                raw=raw,
                canonical_name=canonical,
                hierarchy=hierarchy,
                address=address,
                confidence=source_confidence if not issues else min(source_confidence, 0.75),
                issues=tuple(issues),
            )
        )
    unique: dict[str, ParsedAffiliation] = {}
    for item in parsed:
        unique.setdefault(identity_key(item.canonical_name), item)
    return list(unique.values())
