# ruff: noqa: RUF001
#!/usr/bin/env python3
"""Read publication full text and create a review-only funding extraction package.

The script is intentionally read-only with respect to PostgreSQL and S3. It
locates explicit funding/acknowledgement regions first, then extracts funders
and grant identifiers only inside accepted regions. It emits JSON and CSV files
for review and never writes extracted values back to SmartLib.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import psycopg
from psycopg.rows import dict_row

from smartlib_platform.storage.s3 import S3ObjectStore

OUTPUT_ROOT = Path(
    os.environ.get("SMARTLIB_FUNDING_OUTPUT", "/smartlib-outputs/2026_nsf_fulltext_funding_extraction")
)
CSV_ROOT = OUTPUT_ROOT / "csv"

FUNDING_HEADINGS = re.compile(
    r"^(?:funding(?: information| statement| sources?)?|financial support|"
    r"sources? of (?:financial )?support|grants?|grant support|acknowledg(?:e)?ments?|"
    r"资助(?:信息|声明)?|基金(?:项目|资助)?|经费来源|致谢)\s*[:：.]?\s*(.*)$",
    re.I,
)
STOP_HEADINGS = re.compile(
    r"^(?:author contributions?|conflicts? of interest|competing interests?|"
    r"data availability|availability of data|ethics|ethical approval|"
    r"consent|disclosures?|declarations?|references?|bibliography|"
    r"supplementary (?:data|information|materials?)|作者贡献|利益冲突|"
    r"数据可用性|伦理|参考文献)\s*[:：.]?$",
    re.I,
)
MAJOR_SECTION_HEADINGS = re.compile(
    r"^(?:abstract|introduction|background|materials? and methods?|methods?|results?|discussion|"
    r"conclusions?|author contributions?|conflicts? of interest|competing interests?|"
    r"data availability|availability of data|ethics|ethical approval|consent|disclosures?|"
    r"declarations?|references?|bibliography|supplementary (?:data|information|materials?)|"
    r"摘要|引言|背景|材料与方法|方法|结果|讨论|结论|作者贡献|利益冲突|数据可用性|伦理|参考文献)"
    r"\s*[:：.]?\s*$",
    re.I,
)
STRONG_FUNDING = re.compile(
    r"(?:funded by|financially supported by|funding (?:was|is) (?:provided|received)|"
    r"supported (?:in part )?by (?:the )?(?:National|Natural|China|Chinese|Provincial|"
    r"Municipal|Ministry|University|Foundation|Council|Commission|Program|Project|"
    r"Dalian|Liao\s*Ning|Liaoning|Hainan|Guangzhou|State|Key|NIH|NSFC)|"
    r"financial support|received support from|grant(?:s)? (?:from|by)|award(?:ed)? by|"
    r"资助|基金|经费支持|项目支持)",
    re.I,
)
NO_FUNDING = re.compile(
    r"(?:no (?:specific )?(?:funding|financial support)|received no (?:specific )?(?:funding|grant)|"
    r"did not receive any (?:specific )?(?:funding|grant)|not receive (?:any )?(?:specific )?"
    r"(?:funding|grant)|no external funding|without (?:external )?funding|"
    r"funding\s*[:：]\s*(?:none|not applicable|n/?a)|"
    r"未获得.{0,12}(?:基金|资助|经费)|无.{0,8}(?:基金|资助|经费))",
    re.I,
)
LOOSE_FUNDING = re.compile(
    r"(?:\bfunding\b|\bfunded\b|\bfunder\b|\bgrants?\b|\bgrant\s*(?:no\.?|number)|"
    r"\bfinancial support\b|\bsponsor(?:ed|ship)?\b|\bfinanc(?:ed|ial aid)\b|"
    r"\backnowledg(?:e)?ments?\b|\b[A-Z][A-Za-z&'’ -]{2,50}\s+(?:Foundation|Fund|Program|Council)\b|"
    r"资助|基金|经费|项目编号|课题编号|赞助)",
    re.I,
)
REFERENCE_HEADING = re.compile(r"^\s*(?:references?|bibliography|参考文献)\s*$", re.I | re.M)
XML_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

FUNDER_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"China National Natu-?\s*ral Science Foundation|"
            r"National Natural.{0,90}?Sciences? Founda-?\s*tion(?: of China)?|"
            r"\bNSFC\b|国家自然科学基金(?:委员会)?",
            re.I,
        ),
        "国家自然科学基金委员会（NSFC）",
    ),
    (
        re.compile(
            r"National Key Research.{0,60}?Development Program of China|"
            r"National Key R\s*&\s*D Program of China|国家重点研发计划",
            re.I,
        ),
        "国家重点研发计划",
    ),
    (re.compile(r"China Postdoctoral Science Foundation|中国博士后科学基金", re.I), "中国博士后科学基金"),
    (
        re.compile(r"Liaoning Provincial Key R\s*&\s*D Program", re.I),
        "辽宁省重点研发计划",
    ),
    (
        re.compile(r"Liaoning Revitalization Talents Program", re.I),
        "辽宁省兴辽英才计划",
    ),
    (
        re.compile(r"Natural Science Foundation of Jiangsu Province", re.I),
        "江苏省自然科学基金",
    ),
    (
        re.compile(r"Guangdong Key Project(?: in [\"“].{0,120}?[\"”])?", re.I),
        "广东省重点项目",
    ),
    (
        re.compile(
            r"Team Innovation Funding Program of (?:the )?Second Affiliated Hospital of Soochow University",
            re.I,
        ),
        "苏州大学附属第二医院团队创新资助计划",
    ),
    (
        re.compile(
            r"Natural Science Foundation of Liaoning Province|"
            r"Liaoning Provincial Natural Science Foundation|辽宁省自然科学基金",
            re.I,
        ),
        "辽宁省自然科学基金",
    ),
    (
        re.compile(
            r"Natural Science Foundation of Guangdong Province|"
            r"Guangdong (?:Provincial )?Natural Science Foundation|广东省自然科学基金",
            re.I,
        ),
        "广东省自然科学基金",
    ),
    (
        re.compile(
            r"Natural Science Foundation of Shandong Province|"
            r"Shandong (?:Provincial )?Natural Science Foundation|山东省自然科学基金",
            re.I,
        ),
        "山东省自然科学基金",
    ),
    (re.compile(r"National Institutes? of Health|\bNIH\b", re.I), "美国国立卫生研究院（NIH）"),
    (
        re.compile(r"National Science Foundation(?: of the United States| \(NSF\))?|\bUS NSF\b", re.I),
        "美国国家科学基金会（NSF）",
    ),
    (
        re.compile(
            r"National Health Commission of (?:the People'?s Republic of )?China|国家卫生健康委员会", re.I
        ),
        "国家卫生健康委员会",
    ),
    (
        re.compile(
            r"Ministry of Science and Technology of (?:the People'?s Republic of )?China|"
            r"中华人民共和国科学技术部|科技部",
            re.I,
        ),
        "中华人民共和国科学技术部",
    ),
    (
        re.compile(
            r"Dalian (?:Science and Technology|Municipal|Medical University)"
            r".{0,45}(?:Program|Project|Foundation|Fund)|"
            r"大连市.{0,35}(?:计划|项目|基金)|大连医科大学.{0,35}(?:计划|项目|基金)",
            re.I,
        ),
        "大连市或大连医科大学相关项目（待核）",
    ),
]

GENERIC_FUNDER = re.compile(
    r"\b((?:the\s+)?[A-Z][A-Za-z0-9&'’()\-/ ]{2,90}?"
    r"(?:Foundation|Fund|Program(?:me)?|Council|Commission|Ministry|Agency|"
    r"Institutes?|University|Department|Project|Laboratory))\b"
)
GRANT_TOKEN = re.compile(
    r"\b(?=[A-Z0-9][A-Z0-9./_-]{5,29}\b)"
    r"(?=[A-Z0-9./_-]*\d[A-Z0-9./_-]*\d[A-Z0-9./_-]*\d)"
    r"[A-Z0-9][A-Z0-9./_-]{5,29}\b",
    re.I,
)
LABELLED_GRANTS = re.compile(
    r"(?:grant|award|project)(?:\s+(?:num-?\s*ber|number|no\.?)s?)?\s*[:#：]?\s*"
    r"([A-Z0-9][A-Z0-9./_\-,; and]{4,100})",
    re.I,
)
EMBEDDED_REGION_HEADING = re.compile(
    r"(?P<ack>A\s*C\s*K\s*N\s*O\s*W\s*L\s*E\s*D\s*G\s*E?\s*M\s*E\s*N\s*T\s*S?)|"
    r"(?P<fund>F\s*U\s*N\s*D\s*I\s*N\s*G(?:\s+I\s*N\s*F\s*O\s*R\s*M\s*A\s*T\s*I\s*O\s*N)?)"
)
PUBLISHER_PAGE_MARKER = re.compile(r"\b(\d{1,4})\s+of\s+\d{1,4}\b", re.I)


def squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_pdf_text(value: str) -> str:
    return value.translate(
        str.maketrans(
            {
                "ﬁ": "fi",
                "ﬂ": "fl",
                "ﬀ": "ff",
                "ﬃ": "ffi",
                "ﬄ": "ffl",
                "\u00ad": "",
                "–": "-",
                "—": "-",
                "−": "-",
            }
        )
    )


def normalize_region_text(value: str) -> str:
    normalized = squash(value)
    return re.sub(r"(?<=\w)\s*([/_-])\s*(?=\w)", r"\1", normalized)


def uri_key(uri: str, bucket: str) -> str:
    parsed = urlsplit(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"unsupported extracted text URI: {uri}")
    if parsed.netloc != bucket:
        raise ValueError(f"unexpected bucket in URI: {uri}")
    return parsed.path.lstrip("/")


def truncate_reference_tail(page: str) -> str:
    match = REFERENCE_HEADING.search(page)
    return page[: match.start()] if match else page


def sentence_window(text: str, start: int, end: int, radius: int = 420) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right]
    first = re.search(r"(?:^|[.!?。！？]\s+)(.{0,})", snippet, re.S)
    if first and first.start(1) < radius:
        snippet = first.group(1)
    boundaries = list(re.finditer(r"[.!?。！？](?:\s+|$)", snippet))
    if boundaries:
        for boundary in boundaries:
            if boundary.end() >= min(len(snippet), radius + (end - start)):
                snippet = snippet[: boundary.end()]
                break
    return squash(snippet)[:1800]


def heading_kind(raw: str) -> str | None:
    compact = re.sub(r"[^a-z\u4e00-\u9fff]", "", raw.lower())
    if re.match(
        r"^(?:funding(?:\s+(?:information|statement|sources?))?|financial support|"
        r"sources? of (?:financial )?support|grant support)\s*(?:[:：.]|$)",
        raw,
        re.I,
    ) or (
        re.search(r"(?:[A-Za-z]\s+){4,}[A-Za-z]", raw)
        and compact.startswith(("fundinginformation", "fundingstatement", "financialsupport", "grantsupport"))
    ):
        return "funding_section"
    if compact.startswith(
        ("acknowledgment", "acknowledgments", "acknowledgement", "acknowledgements", "致谢")
    ):
        return "acknowledgements_section"
    if compact.startswith(("资助", "基金", "经费来源")):
        return "funding_section"
    return None


def is_embedded_stop_heading(raw: str) -> bool:
    compact = re.sub(r"[^a-z\u4e00-\u9fff]", "", raw.lower())
    return compact.startswith(
        (
            "conflictofinterest",
            "competinginterests",
            "authorcontributions",
            "dataavailability",
            "references",
            "supplementaryinformation",
            "利益冲突",
            "作者贡献",
            "数据可用性",
            "参考文献",
        )
    )


def publisher_page_hint(lines: list[str], line_index: int, fallback: int) -> int:
    for cursor in range(line_index, -1, -1):
        match = PUBLISHER_PAGE_MARKER.search(lines[cursor])
        if match:
            return int(match.group(1))
    for cursor in range(line_index + 1, min(len(lines), line_index + 120)):
        match = PUBLISHER_PAGE_MARKER.search(lines[cursor])
        if match:
            return int(match.group(1))
    return fallback


def right_column_segment(line: str, expected_column: int) -> str:
    gaps = [match for match in re.finditer(r"\s{3,}", line) if abs(match.end() - expected_column) <= 18]
    if gaps:
        boundary = min(gaps, key=lambda match: abs(match.end() - expected_column)).end()
        return line[boundary:]
    return line[max(0, expected_column - 8) :]


def region_score(kind: str, text: str, explicit_no: bool) -> int:
    score = 80 if kind == "funding_section" else 65
    score += 15 if STRONG_FUNDING.search(text) else 0
    score += 15 if explicit_no else 0
    score += min(15, len(grant_ids(text)) * 3)
    score += min(10, len(funders(text)) * 2)
    score -= len(re.findall(r"\b(?:abstract|introduction|methods?|results?|figure|table)\b", text, re.I)) * 8
    score -= 20 if len(text) > 3000 else 0
    return max(0, score)


def section_candidates(page: str, page_number: int) -> list[dict[str, Any]]:
    lines = page.splitlines()
    candidates: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        original_line = lines[index]
        raw = squash(original_line)
        embedded = EMBEDDED_REGION_HEADING.search(original_line)
        # Two-column PDFs often place a section heading in the right column
        # after unrelated left-column text. Preserve the visual column boundary
        # and read only the right-column slice on following lines.
        if embedded and embedded.start() >= 20:
            kind = "acknowledgements_section" if embedded.group("ack") else "funding_section"
            column = embedded.start()
            collected = [original_line[embedded.end() :]]
            cursor = index + 1
            while cursor < len(lines) and len(" ".join(collected)) < 3500:
                segment = right_column_segment(lines[cursor], column)
                segment_text = squash(segment)
                if segment_text and (is_embedded_stop_heading(segment_text) or heading_kind(segment_text)):
                    break
                collected.append(segment)
                cursor += 1
            evidence = normalize_region_text(" ".join(collected))
            explicit_no = bool(NO_FUNDING.search(evidence))
            if evidence and (STRONG_FUNDING.search(evidence) or explicit_no or kind == "funding_section"):
                score = region_score(kind, evidence, explicit_no) + 20
                candidates.append(
                    {
                        "page_number": page_number,
                        "publisher_page_number": publisher_page_hint(lines, index, page_number),
                        "region_start_line": index + 1,
                        "region_end_line": cursor,
                        "section_label": squash(embedded.group(0)),
                        "region_type": kind,
                        "extraction_method": "bounded_two_column_region",
                        "evidence_text": evidence[:3500],
                        "matched_keyword": squash(embedded.group(0)),
                        "region_score": score,
                        "confidence": "high" if score >= 80 else "medium",
                    }
                )
            index = max(cursor, index + 1)
            continue
        kind = heading_kind(raw) if len(raw) <= 180 else None
        heading = FUNDING_HEADINGS.match(raw) if kind else None
        if not kind:
            index += 1
            continue
        heading_name = raw.split(":", 1)[0].split("：", 1)[0][:80]
        remainder = heading.group(1) if heading and heading.lastindex else ""
        collected = [remainder] if remainder else []
        cursor = index + 1
        while cursor < len(lines) and len(" ".join(collected)) < 3500:
            next_line = squash(lines[cursor])
            if next_line and (STOP_HEADINGS.match(next_line) or MAJOR_SECTION_HEADINGS.match(next_line)):
                break
            if next_line and heading_kind(next_line) and cursor > index + 1:
                break
            collected.append(lines[cursor])
            cursor += 1
        evidence = normalize_region_text(" ".join(collected))
        explicit_no = bool(NO_FUNDING.search(evidence))
        has_funding_signal = bool(STRONG_FUNDING.search(evidence))
        if evidence and (kind == "funding_section" or has_funding_signal or explicit_no):
            score = region_score(kind, evidence, explicit_no)
            candidates.append(
                {
                    "page_number": page_number,
                    "publisher_page_number": publisher_page_hint(lines, index, page_number),
                    "region_start_line": index + 1,
                    "region_end_line": cursor,
                    "section_label": heading_name,
                    "region_type": kind,
                    "extraction_method": "bounded_heading_region",
                    "evidence_text": evidence[:3500],
                    "matched_keyword": raw[:160],
                    "region_score": score,
                    "confidence": "high" if score >= 80 else "medium",
                }
            )
        index = max(cursor, index + 1)
    return candidates


def explicit_statement_candidates(page: str, page_number: int) -> list[dict[str, Any]]:
    """Locate a bounded, self-contained funding statement when no heading exists."""
    searchable = truncate_reference_tail(page)
    candidates: list[dict[str, Any]] = []
    combined = re.compile(f"(?:{NO_FUNDING.pattern}|{STRONG_FUNDING.pattern})", re.I)
    for match in combined.finditer(searchable):
        lines = searchable.splitlines()
        line_index = searchable[: match.start()].count("\n")
        region = sentence_window(searchable, match.start(), match.end(), radius=260)
        explicit_no = bool(NO_FUNDING.search(region))
        if not explicit_no and not re.search(
            r"\b(?:this (?:study|work|research)|the (?:study|work|research)|authors?)\b.{0,100}"
            r"(?:funded|supported|funding|grant)|(?:funded|supported|funding|grant).{0,100}"
            r"\b(?:this (?:study|work|research)|the (?:study|work|research)|authors?)\b|"
            r"(?:本研究|本工作|本项目).{0,40}(?:资助|基金|经费)",
            region,
            re.I,
        ):
            continue
        candidates.append(
            {
                "page_number": page_number,
                "publisher_page_number": publisher_page_hint(lines, line_index, page_number),
                "region_start_line": line_index + 1,
                "region_end_line": line_index + 1,
                "section_label": "独立基金声明",
                "region_type": "explicit_statement_region",
                "extraction_method": "bounded_explicit_statement",
                "evidence_text": region,
                "matched_keyword": match.group(0),
                "region_score": 75 if explicit_no else 70,
                "confidence": "medium",
            }
        )
    return candidates


def funding_focus(text: str) -> str:
    """Return the narrowest useful funding clause from a noisy PDF text block."""
    matches = list(STRONG_FUNDING.finditer(text)) + list(NO_FUNDING.finditer(text))
    if not matches:
        return squash(text)[:1200]
    start = max(0, min(match.start() for match in matches) - 80)
    end = min(len(text), max(match.end() for match in matches) + 1100)
    focused = squash(text[start:end])
    stop = re.search(
        r"\b(?:All animal procedures|The authors declare|Conflict of Interest|"
        r"Competing Interests?|Data Availability|Ethics Approval|Correspondence)\b",
        focused,
        re.I,
    )
    return focused[: stop.start()].strip() if stop and stop.start() > 120 else focused


def evidence_key(candidate: dict[str, Any]) -> str:
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", candidate["evidence_text"].lower())
    return text[:800]


def extract_evidence(text: str) -> list[dict[str, Any]]:
    pages = re.split(r"\f+", text)
    headed: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    for page_number, page in enumerate(pages, 1):
        headed.extend(section_candidates(page, page_number))
        fallback.extend(explicit_statement_candidates(page, page_number))

    # Structural regions take precedence. Fallback statements are considered
    # only when no acceptable funding/acknowledgement region exists anywhere.
    candidates = headed if headed else fallback
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    selected_grant_sets: list[set[str]] = []
    for candidate in sorted(candidates, key=lambda item: (-item["region_score"], item["page_number"])):
        key = evidence_key(candidate)
        if len(key) < 12 or key in seen:
            continue
        if any(key[:240] in prior or prior[:240] in key for prior in seen):
            continue
        candidate_grants = set(grant_ids(candidate["evidence_text"]))
        if candidate_grants and any(
            len(candidate_grants & prior) / min(len(candidate_grants), len(prior)) >= 0.5
            for prior in selected_grant_sets
            if prior
        ):
            continue
        seen.add(key)
        selected_grant_sets.append(candidate_grants)
        candidate["explicit_no_funding"] = bool(NO_FUNDING.search(candidate["evidence_text"]))
        candidate["possible_reference"] = False
        found.append(candidate)
    return found


def grant_ids(text: str) -> list[str]:
    text = normalize_region_text(text)
    values: set[str] = set()
    for match in LABELLED_GRANTS.finditer(text):
        for token in GRANT_TOKEN.findall(match.group(1)):
            values.add(token.strip(".,;:/()[]{}"))
    # Funding identifiers are normally parenthesized. Restricting unlabelled
    # tokens to parentheses prevents years, reference pages, SNPs and DOI paths
    # from being misclassified as grants in interleaved two-column PDF text.
    parenthetical = " ".join(re.findall(r"[（(]([^()（）]{1,180})[）)]", text))
    for token in GRANT_TOKEN.findall(parenthetical):
        clean = token.strip(".,;:/()[]{}")
        lowered = clean.lower()
        if re.fullmatch(r"(?:19|20)\d{2}", clean):
            continue
        if lowered.startswith(("doi", "pmid", "pmcid", "issn", "isbn")):
            continue
        if "/" in clean and re.match(r"10\.\d{4,9}/", clean, re.I):
            continue
        values.add(clean)
    return sorted(values, key=lambda value: (len(value), value))


def aggressive_grant_ids(text: str) -> list[str]:
    values = set(grant_ids(text))
    for token in GRANT_TOKEN.findall(text):
        clean = token.strip(".,;:/()[]{}")
        lowered = clean.lower()
        if re.fullmatch(r"(?:19|20)\d{2}", clean):
            continue
        if lowered.startswith(("doi", "pmid", "pmcid", "issn", "isbn", "fig", "table", "rs")):
            continue
        if re.match(r"10\.\d{4,9}/", clean, re.I) or "pubs." in lowered:
            continue
        values.add(clean)
    return sorted(values, key=lambda value: (len(value), value))


def funders(text: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for pattern, canonical in FUNDER_ALIASES:
        match = pattern.search(text)
        if match and canonical not in seen:
            seen.add(canonical)
            result.append({"funder_name_raw": squash(match.group(0)), "funder_name_normalized": canonical})
    for match in GENERIC_FUNDER.finditer(text):
        raw = squash(match.group(1)).strip(" ,.;:")
        raw = re.sub(
            r"^(?:This|The) (?:study|work|research) (?:was |is )?"
            r"(?:financially )?(?:supported|funded)(?: with grants)? (?:by|from) (?:the )?",
            "",
            raw,
            flags=re.I,
        )
        if " and " in raw.casefold():
            tail = re.split(r"\band\b", raw, flags=re.I)[-1].strip()
            if any(tail.casefold() in item["funder_name_raw"].casefold() for item in result):
                raw = tail
        key = raw.casefold()
        word_count = len(raw.split())
        noisy = re.search(r"\b(?:department|laboratory|figure|table|method|results?|authors?)\b", raw, re.I)
        duplicates_alias = any(pattern.search(raw) for pattern, _canonical in FUNDER_ALIASES)
        overlaps_existing = any(
            key in item["funder_name_raw"].casefold() or item["funder_name_raw"].casefold() in key
            for item in result
        )
        if (
            1 < word_count <= 14
            and len(raw) > 3
            and not noisy
            and not duplicates_alias
            and not overlaps_existing
            and key not in {item["funder_name_raw"].casefold() for item in result}
        ):
            result.append({"funder_name_raw": raw, "funder_name_normalized": ""})
    return result


def fetch_rows(connection: psycopg.Connection) -> list[dict[str, Any]]:
    query = """
        SELECT
            item.record_id::text,
            COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer) AS source_row_number,
            submission.representative_work_number,
            submission.awardee_name_raw,
            meta.publication_id::text,
            meta.title,
            meta.journal_name,
            meta.publication_year,
            doi.normalized_value AS doi,
            resource.fulltext_resource_id::text,
            resource.file_name,
            resource.storage_uri,
            resource.extracted_text_uri,
            resource.page_count,
            resource.text_length,
            resource.content_checksum,
            resource.extraction_method
        FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
        LEFT JOIN smartlib.publication_metadata AS meta
          ON meta.publication_id = item.matched_publication_id
        LEFT JOIN LATERAL (
            SELECT identifier.normalized_value
              FROM smartlib.publication_identifier AS identifier
             WHERE identifier.publication_id = meta.publication_id
               AND identifier.identifier_type = 'doi'
             ORDER BY identifier.is_primary DESC, identifier.created_at
             LIMIT 1
        ) AS doi ON true
        LEFT JOIN LATERAL (
            SELECT fulltext.*
              FROM smartlib.publication_fulltext_resource AS fulltext
             WHERE fulltext.publication_id = meta.publication_id
             ORDER BY fulltext.created_at DESC
             LIMIT 1
        ) AS resource ON true
       
                       ORDER BY COALESCE((input_record.source_locator->>'row')::integer,
                            (input_record.source_locator->>'position')::integer)
    """
    return list(connection.execute(query).fetchall())


def write_csv(name: str, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path = CSV_ROOT / name
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(
            {
                key: XML_ILLEGAL.sub(" ", value) if isinstance(value, str) else value
                for key, value in row.items()
            }
            for row in rows
        )


def split_summary_values(value: str | None) -> set[str]:
    return {item.strip() for item in (value or "").split(";") if item.strip()}


def comparison_rows(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_path = Path(
        os.environ.get(
            "SMARTLIB_FUNDING_PREVIOUS_RESULT",
            "/smartlib-outputs/2026_nsf_fulltext_funding_extraction_comprehensive/"
            "论文全文基金信息抽取_待审核.json",
        )
    )
    if not previous_path.exists():
        return []
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    previous_by_id = {row["唯一论文ID"]: row for row in previous.get("publications", [])}
    current_by_id = {row["唯一论文ID"]: row for row in summary_rows}
    result: list[dict[str, Any]] = []
    for publication_id, current in current_by_id.items():
        old = previous_by_id.get(publication_id, {})
        old_grants = split_summary_values(old.get("基金编号汇总"))
        current_grants = split_summary_values(current.get("基金编号汇总"))
        old_funders = split_summary_values(old.get("资助方汇总"))
        current_funders = split_summary_values(current.get("资助方汇总"))
        result.append(
            {
                "唯一论文ID": publication_id,
                "论文题名": current["论文题名"],
                "旧状态": old.get("提取状态", ""),
                "区域优先状态": current["提取状态"],
                "旧证据数": old.get("证据条数", 0),
                "区域证据数": current["证据条数"],
                "删除的基金编号候选": "; ".join(sorted(old_grants - current_grants)),
                "新增的基金编号候选": "; ".join(sorted(current_grants - old_grants)),
                "删除的资助方候选": "; ".join(sorted(old_funders - current_funders)),
                "新增的资助方候选": "; ".join(sorted(current_funders - old_funders)),
            }
        )
    return result


def main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    CSV_ROOT.mkdir(parents=True, exist_ok=True)
    database_url = os.environ["SMARTLIB_DATABASE_URL"]
    actor_id = os.environ["SMARTLIB_DEV_ACTOR_ID"]
    bucket = os.environ["SMARTLIB_S3_BUCKET"]
    client = httpx.Client(timeout=httpx.Timeout(90, connect=10))
    store = S3ObjectStore(
        os.environ["SMARTLIB_S3_ENDPOINT_URL"],
        bucket,
        os.environ["SMARTLIB_S3_ACCESS_KEY"],
        os.environ["SMARTLIB_S3_SECRET_KEY"],
        os.environ.get("SMARTLIB_S3_REGION", "us-east-1"),
        client,
    )

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (actor_id,))
            source_rows = fetch_rows(connection)

    if len(source_rows) != 283:
        raise RuntimeError(f"expected 283 source rows, got {len(source_rows)}")

    rows_by_publication: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        rows_by_publication[row["publication_id"]].append(row)

    unique_results: dict[str, dict[str, Any]] = {}
    all_evidence: list[dict[str, Any]] = []
    all_funds: list[dict[str, Any]] = []
    for number, (publication_id, linked_rows) in enumerate(rows_by_publication.items(), 1):
        first = linked_rows[0]
        text_uri = first.get("extracted_text_uri")
        evidence: list[dict[str, Any]] = []
        read_error = ""
        if text_uri:
            try:
                raw = store.get_bytes(uri_key(text_uri, bucket))
                text = normalize_pdf_text(XML_ILLEGAL.sub(" ", raw.decode("utf-8", errors="replace")))
                evidence = extract_evidence(text)
            except Exception as exc:  # preserve per-paper failures in the review package
                read_error = f"{type(exc).__name__}: {exc}"
        else:
            read_error = "extracted_text_uri is empty"

        explicit_no = [item for item in evidence if item["explicit_no_funding"]]
        positive = [item for item in evidence if not item["explicit_no_funding"]]
        parsed_funders: list[dict[str, str]] = []
        parsed_grants: set[str] = set()
        for item in positive:
            focus = funding_focus(item["evidence_text"])
            item["funding_clause_focus"] = focus
            parsed_funders.extend(funders(focus))
            parsed_grants.update(grant_ids(focus))
        for item in explicit_no:
            item["funding_clause_focus"] = funding_focus(item["evidence_text"])
        dedup_funders: list[dict[str, str]] = []
        seen_funders: set[tuple[str, str]] = set()
        for item in parsed_funders:
            key = (item["funder_name_raw"].casefold(), item["funder_name_normalized"])
            if key not in seen_funders:
                seen_funders.add(key)
                dedup_funders.append(item)

        if read_error:
            status = "全文读取失败"
        elif explicit_no and positive:
            status = "待人工核对（声明冲突）"
        elif positive and (dedup_funders or parsed_grants):
            status = "已提取基金信息"
        elif positive:
            status = "有基金表述但未识别项目"
        elif explicit_no:
            status = "明确声明无专项基金"
        else:
            status = "全文未检出可靠基金表述"

        source_numbers = [row["source_row_number"] for row in linked_rows]
        source_ids = [row["representative_work_number"] for row in linked_rows]
        for evidence_order, item in enumerate(evidence, 1):
            evidence_id = f"E-{publication_id[:8]}-{evidence_order:02d}"
            item.update(
                {
                    "evidence_id": evidence_id,
                    "publication_id": publication_id,
                    "source_row_numbers": ",".join(str(value) for value in source_numbers),
                    "representative_work_numbers": ",".join(value or "" for value in source_ids),
                    "title": first["title"],
                }
            )
            all_evidence.append(item)

        # Each parsed row is deliberately conservative: unknown association is visible.
        for item in evidence:
            if item["explicit_no_funding"]:
                continue
            focus = item.get("funding_clause_focus") or funding_focus(item["evidence_text"])
            item_funders = funders(focus)
            item_grants = grant_ids(focus)
            if not item_funders and not item_grants:
                continue
            all_funds.append(
                {
                    "publication_id": publication_id,
                    "source_row_numbers": item["source_row_numbers"],
                    "representative_work_numbers": item["representative_work_numbers"],
                    "title": first["title"],
                    "funder_name_raw": "; ".join(entry["funder_name_raw"] for entry in item_funders),
                    "funder_name_normalized": "; ".join(
                        entry["funder_name_normalized"]
                        for entry in item_funders
                        if entry["funder_name_normalized"]
                    ),
                    "grant_id_raw": "; ".join(item_grants),
                    "association_confidence": "较高"
                    if len(item_funders) == 1 and len(item_grants) <= 1
                    else "待核（同一区域内资助方与编号尚未逐项拆分）",
                    "candidate_mode": "基金声明区域内抽取",
                    "possible_reference": item.get("possible_reference", False),
                    "evidence_id": item["evidence_id"],
                    "page_number": item["page_number"],
                    "publisher_page_number": item["publisher_page_number"],
                }
            )

        unique_results[publication_id] = {
            "publication_id": publication_id,
            "title": first["title"],
            "source_row_numbers": source_numbers,
            "representative_work_numbers": source_ids,
            "status": status,
            "read_error": read_error,
            "evidence_count": len(evidence),
            "funder_count": len(dedup_funders),
            "grant_count": len(parsed_grants),
            "funders": dedup_funders,
            "grant_ids": sorted(parsed_grants),
            "evidence_ids": [item["evidence_id"] for item in evidence],
        }
        if number % 25 == 0 or number == len(rows_by_publication):
            print(f"processed {number}/{len(rows_by_publication)} unique publications", flush=True)

    summary_rows: list[dict[str, Any]] = []
    for serial, row in enumerate(source_rows, 1):
        result = unique_results[row["publication_id"]]
        source_group = rows_by_publication[row["publication_id"]]
        summary_rows.append(
            {
                "原始序号": serial,
                "源表行号": row["source_row_number"],
                "代表性论著编号": row["representative_work_number"],
                "获批人": row["awardee_name_raw"],
                "论文题名": row["title"],
                "期刊": row["journal_name"],
                "发表年份": row["publication_year"],
                "DOI": row["doi"],
                "唯一论文ID": row["publication_id"],
                "是否重复登记": "是" if len(source_group) > 1 else "否",
                "同一论文源表行": ",".join(str(item["source_row_number"]) for item in source_group),
                "全文页数": row["page_count"],
                "全文字符数": row["text_length"],
                "提取状态": result["status"],
                "资助方数量": result["funder_count"],
                "基金编号数量": result["grant_count"],
                "资助方汇总": "; ".join(
                    item["funder_name_normalized"] or item["funder_name_raw"] for item in result["funders"]
                ),
                "基金编号汇总": "; ".join(result["grant_ids"]),
                "证据条数": result["evidence_count"],
                "证据ID": "; ".join(result["evidence_ids"]),
                "全文校验和": row["content_checksum"],
                "全文文本URI": row["extracted_text_uri"],
                "读取异常": result["read_error"],
            }
        )

    status_counts = Counter(row["提取状态"] for row in summary_rows)
    unique_status_counts = Counter(result["status"] for result in unique_results.values())
    generated_at = datetime.now(UTC).isoformat()
    package = {
        "metadata": {
            "generated_at": generated_at,
            "purpose": "283篇论文全文基金信息区域优先检查，供人工复核；未回写数据库",
            "scope_original_records": len(source_rows),
            "scope_unique_publications": len(unique_results),
            "duplicate_source_records": len(source_rows) - len(unique_results),
            "unique_fulltexts_read": sum(not result["read_error"] for result in unique_results.values()),
            "status_counts_original_records": dict(status_counts),
            "status_counts_unique_publications": dict(unique_status_counts),
            "method_version": "funding-review-zone-first-v3",
            "important_interpretation": (
                "先定位基金声明、Funding或致谢区域，再仅在已接受区域内抽取；"
                "正文、单位、方法与参考文献不作为基金实体来源。"
            ),
        },
        "publications": summary_rows,
        "unique_publication_results": list(unique_results.values()),
        "funding_records": all_funds,
        "evidence": all_evidence,
    }
    (OUTPUT_ROOT / "论文全文基金信息抽取_待审核.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary_columns = list(summary_rows[0])
    fund_columns = [
        "publication_id",
        "source_row_numbers",
        "representative_work_numbers",
        "title",
        "funder_name_raw",
        "funder_name_normalized",
        "grant_id_raw",
        "association_confidence",
        "candidate_mode",
        "possible_reference",
        "evidence_id",
        "page_number",
        "publisher_page_number",
    ]
    evidence_columns = [
        "evidence_id",
        "publication_id",
        "source_row_numbers",
        "representative_work_numbers",
        "title",
        "page_number",
        "publisher_page_number",
        "region_start_line",
        "region_end_line",
        "section_label",
        "region_type",
        "extraction_method",
        "region_score",
        "confidence",
        "explicit_no_funding",
        "possible_reference",
        "matched_keyword",
        "funding_clause_focus",
        "evidence_text",
    ]
    review_rows = [row for row in summary_rows if row["提取状态"] != "已提取基金信息"]
    write_csv("01_论文汇总_283条.csv", summary_rows, summary_columns)
    write_csv("02_基金明细.csv", all_funds, fund_columns)
    write_csv("03_原文证据.csv", all_evidence, evidence_columns)
    write_csv("04_未提取与待核.csv", review_rows, summary_columns)
    differences = comparison_rows(summary_rows)
    if differences:
        write_csv("05_与宽松扫描版差异.csv", differences, list(differences[0]))

    overview_rows = [
        {"项目": "生成时间（UTC）", "值": generated_at, "说明": "本次只读抽取快照"},
        {"项目": "原始论文记录", "值": len(source_rows), "说明": "保留原始283条逐条结果"},
        {
            "项目": "唯一论文/全文",
            "值": len(unique_results),
            "说明": "12条为重复登记，全文按校验后唯一论文读取",
        },
        {
            "项目": "成功读取全文",
            "值": sum(not result["read_error"] for result in unique_results.values()),
            "说明": "对象存储中的全文解析文本",
        },
        {
            "项目": "基金明细候选",
            "值": len(all_funds),
            "说明": "仅从已定位的基金声明区域中抽取，仍需审核对应关系",
        },
        {"项目": "基金区域证据", "值": len(all_evidence), "说明": "保留页码、栏目、区域类型、区域评分和原文"},
        {
            "项目": "重要口径",
            "值": "区域优先",
            "说明": "不再扫描全文后跨正文、单位、方法或参考文献拼接基金信息",
        },
        {"项目": "治理动作", "值": "未回写数据库", "说明": "用户审核并决定后再讨论入库"},
    ]
    for label, count in unique_status_counts.most_common():
        overview_rows.append({"项目": f"唯一论文状态：{label}", "值": count, "说明": "规则抽取统计"})
    write_csv("00_汇总说明.csv", overview_rows, ["项目", "值", "说明"])

    previous_candidate_count = 0
    previous_evidence_count = 0
    previous_path = Path(
        os.environ.get(
            "SMARTLIB_FUNDING_PREVIOUS_RESULT",
            "/smartlib-outputs/2026_nsf_fulltext_funding_extraction_comprehensive/"
            "论文全文基金信息抽取_待审核.json",
        )
    )
    if previous_path.exists():
        previous_package = json.loads(previous_path.read_text(encoding="utf-8"))
        previous_candidate_count = len(previous_package.get("funding_records", []))
        previous_evidence_count = len(previous_package.get("evidence", []))
    report = f"""# 283篇论文全文基金信息区域优先检查报告

生成时间：{generated_at}

## 检查范围

- 原始登记：{len(source_rows)} 条
- 唯一论文全文：{len(unique_results)} 篇
- 成功读取：{sum(not result["read_error"] for result in unique_results.values())} 篇
- 本轮数据库写入：0 条

## 方法

1. 先识别 Funding、Financial support、Grant support、Acknowledgements、致谢等栏目边界。
2. 双栏文本按栏目所在列截取，避免把另一列的正文、单位或方法混入。
3. 仅在已接受的区域中提取资助方和基金编号。
4. 无栏目时，只接受完整、独立的基金声明作为兜底。
5. 参考文献、作者单位、方法、正文中的零散基金词不参与实体抽取。

## 结果

- 已提取基金信息：{unique_status_counts.get("已提取基金信息", 0)} 篇
- 有基金表述但未识别项目：{unique_status_counts.get("有基金表述但未识别项目", 0)} 篇
- 明确声明无专项基金：{unique_status_counts.get("明确声明无专项基金", 0)} 篇
- 未检出可靠基金区域：{unique_status_counts.get("全文未检出可靠基金表述", 0)} 篇
- 基金候选记录：{len(all_funds)} 条（旧宽松版 {previous_candidate_count} 条）
- 区域证据：{len(all_evidence)} 条（旧宽松版 {previous_evidence_count} 条）

## 使用边界

这是一轮只读检查结果。候选尚未覆盖数据库关系；“未检出可靠基金区域”不等于论文没有基金，需检查版式、扫描质量、补充材料或外部元数据。
"""
    (OUTPUT_ROOT / "检查报告.md").write_text(report, encoding="utf-8")
    print(json.dumps(package["metadata"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
