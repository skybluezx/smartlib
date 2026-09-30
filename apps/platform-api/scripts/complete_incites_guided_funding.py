#!/usr/bin/env python3
"""Use InCites funder hints to rescan publication PDF text for grant details.

This is a review-only workflow. It reads publication identities from the
InCites/full-text comparison, reads the PDF-derived text from object storage,
and writes an auditable completion package. It never mutates PostgreSQL, S3,
search indexes, or the graph.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from smartlib_platform.storage.s3 import S3ObjectStore


FUNDER_PATTERNS: dict[str, re.Pattern[str]] = {
    "国家自然科学基金委员会（NSFC）": re.compile(
        r"National\s+Natural\s+Sciences?\s+(?:Foundation|Fund)(?:\s+of\s+China)?|"
        r"China\s+National\s+Natural\s+Science\s+Foundation|\bNSFC\b|"
        r"国家自然科学基金(?:委员会)?",
        re.I,
    ),
    "国家重点研发计划": re.compile(
        r"National\s+Key\s+Research\s*(?:and|&)\s*Development\s+Program(?:me)?(?:\s+of\s+China)?|"
        r"National\s+Key\s+R\s*&\s*D\s+Program(?:me)?(?:\s+of\s+China)?|国家重点研发计划",
        re.I,
    ),
    "辽宁省自然科学基金": re.compile(
        r"Natural\s+Science\s+Foundation\s+of\s+Liaoning(?:\s+Province)?|"
        r"Liaoning\s+(?:Provincial\s+)?Natural\s+Science\s+Foundation|"
        r"State\s+Natural\s+Science\s+Foundation\s+of\s+Liaoning|辽宁省自然科学基金",
        re.I,
    ),
    "辽宁省兴辽英才计划": re.compile(
        r"Liaoning\s+Revitalization\s+Talents?\s+Program(?:me)?|"
        r"Xingliao\s+Talents?\s+Program(?:me)?|兴辽英才计划",
        re.I,
    ),
    "中国博士后科学基金": re.compile(
        r"China\s+Postdoctoral\s+Science\s+Foundation|中国博士后科学基金", re.I
    ),
    "中央高校基本科研业务费": re.compile(
        r"Fundamental\s+Research\s+Funds?\s+for\s+the\s+Central\s+Universit(?:y|ies)|"
        r"中央高校基本科研业务费", re.I
    ),
    "长江学者和创新团队发展计划（PCSIRT）": re.compile(
        r"Program(?:me)?\s+for\s+Changjiang\s+Scholars?\s*(?:and|&)\s*Innovative\s+Research\s+Team"
        r"(?:\s+in\s+University)?|\bPCSIRT\b|长江学者.{0,30}创新团队", re.I
    ),
    "浙江省自然科学基金": re.compile(
        r"Natural\s+Science\s+Foundation\s+of\s+Zhejiang(?:\s+Province)?|"
        r"Zhejiang\s+(?:Provincial\s+)?Natural\s+Science\s+Foundation|浙江省自然科学基金", re.I
    ),
    "韩国国家研究基金会": re.compile(
        r"National\s+Research\s+Foundation\s+of\s+Korea|\bNRF(?:-?Korea)?\b|韩国国家研究基金", re.I
    ),
    "英国医学研究委员会（MRC）": re.compile(
        r"(?:UK\s+)?Medical\s+Research\s+Council(?:\s*\(MRC\))?|\bMRC\b", re.I
    ),
    "英国研究与创新署（UKRI）": re.compile(
        r"UK\s+Research\s*(?:and|&)\s*Innovation|\bUKRI\b|英国研究与创新", re.I
    ),
    "英国癌症研究基金会": re.compile(r"Cancer\s+Research\s+UK|英国癌症研究", re.I),
}

FUZZY_FUNDER_PATTERNS: dict[str, re.Pattern[str]] = {
    "国家自然科学基金委员会（NSFC）": re.compile(
        r"National\s+Natural\s+Sciences?\s+Founda.{0,180}?tion\s+of\s+China", re.I | re.S
    ),
    "国家重点研发计划": re.compile(
        r"National\s+Key\s+(?:Research|R\s*&\s*D).{0,160}?(?:Development\s+)?Program", re.I | re.S
    ),
    "辽宁省自然科学基金": re.compile(
        r"Natural\s+Science\s+Founda.{0,160}?tion\s+of\s+Liaoning|"
        r"Liaoning.{0,120}?Natural\s+Science\s+Foundation", re.I | re.S
    ),
    "辽宁省兴辽英才计划": re.compile(r"Liaoning.{0,100}?Revitalization.{0,100}?Talents?\s+Program", re.I | re.S),
    "中国博士后科学基金": re.compile(r"China.{0,80}?Postdoctoral.{0,80}?Science\s+Foundation", re.I | re.S),
    "中央高校基本科研业务费": re.compile(r"Fundamental.{0,100}?Research\s+Funds?.{0,100}?Central\s+Universit", re.I | re.S),
    "长江学者和创新团队发展计划（PCSIRT）": re.compile(r"Changjiang.{0,120}?Innovative\s+Research\s+Team|PCSIRT", re.I | re.S),
    "浙江省自然科学基金": re.compile(r"Zhejiang.{0,100}?Natural\s+Science\s+Foundation", re.I | re.S),
    "韩国国家研究基金会": re.compile(r"National.{0,80}?Research\s+Foundation.{0,80}?Korea|\bNRF\b", re.I | re.S),
    "英国医学研究委员会（MRC）": re.compile(r"Medical.{0,60}?Research\s+Council|\bMRC\b", re.I | re.S),
    "英国研究与创新署（UKRI）": re.compile(r"UK.{0,60}?Research.{0,60}?Innovation|\bUKRI\b", re.I | re.S),
    "英国癌症研究基金会": re.compile(r"Cancer.{0,60}?Research\s+UK|\bCRUK\b", re.I | re.S),
}

SUPPORT_SIGNAL = re.compile(
    r"funded\s+by|supported\s+by|financial(?:ly)?\s+support|funding\s+(?:was|is|from)|"
    r"funding\s+information|(?:authors?\s+)?thank(?:s|ed)?|"
    r"grant(?:s)?\s+(?:from|by|number|no\.?|support)|grant\s*/\s*award\s+numbers?|"
    r"award(?:ed)?\s+by|award\s+numbers?|"
    r"acknowledg(?:e)?ments?|资助|基金|经费支持|项目支持",
    re.I,
)
STOP_SECTION = re.compile(
    r"\b(?:conflicts?\s+of\s+interest|competing\s+interests?|author\s+contributions?|"
    r"data\s+availability|ethics|references?|bibliography|supplementary\s+information)\b",
    re.I,
)
REFERENCE_HEADING = re.compile(r"(?im)^\s*(?:references?|bibliography|参考文献)\s*$")
GRANT_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?=[A-Za-z0-9][A-Za-z0-9./_-]{4,39}(?![A-Za-z0-9./_-]))"
    r"(?=[A-Za-z0-9./_-]*\d[A-Za-z0-9./_-]*\d[A-Za-z0-9./_-]*\d)"
    r"[A-Za-z0-9][A-Za-z0-9./_-]{4,39}",
    re.I,
)
DOI = re.compile(r"^10\.\d{4,9}/", re.I)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def compact(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def normalize_pdf_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(
        str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "\u00ad": ""})
    )
    # Repair line-wrap hyphenation while preserving identifiers such as XLYC-2020.
    value = re.sub(r"(?<=[A-Za-z]{2})-\s*\n\s*(?=[a-z]{2})", "", value)
    return value.replace("\x00", "")


def uri_key(uri: str, bucket: str) -> str:
    parsed = urlsplit(uri)
    if parsed.scheme != "s3" or parsed.netloc != bucket:
        raise ValueError(f"unexpected object URI: {uri}")
    return parsed.path.lstrip("/")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def package_resources(path: Path) -> dict[str, dict[str, Any]]:
    package = json.loads(path.read_text(encoding="utf-8"))
    resources: dict[str, dict[str, Any]] = {}
    for row in package["publications"]:
        publication_id = row["唯一论文ID"]
        resources.setdefault(
            publication_id,
            {
                "publication_id": publication_id,
                "title": row["论文题名"],
                "doi": row.get("DOI") or "",
                "storage_uri": "",
                "extracted_text_uri": row.get("全文文本URI") or "",
                "file_name": "",
                "page_count": row.get("全文页数") or "",
                "extraction_method": "PDF已解析文本",
                "content_checksum": row.get("全文校验和") or "",
            },
        )
    return resources


def broad_package_index(path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    package = json.loads(path.read_text(encoding="utf-8"))
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in package.get("funding_records", []):
        records[row["publication_id"]].append(row)
    evidence = {row["evidence_id"]: row for row in package.get("evidence", [])}
    return records, evidence


def broad_fallback(
    publication_id: str,
    funder: str,
    records_by_publication: dict[str, list[dict[str, Any]]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    fuzzy = FUZZY_FUNDER_PATTERNS[funder]
    for record in records_by_publication.get(publication_id, []):
        evidence = evidence_by_id.get(record.get("evidence_id", ""), {})
        text = compact(evidence.get("evidence_text") or evidence.get("funding_clause_focus") or "")
        normalized_names = {item.strip() for item in str(record.get("funder_name_normalized") or "").split(";")}
        target_supported = funder in normalized_names or bool(fuzzy.search(text))
        if not target_supported:
            continue
        grants = [
            canonicalize_grant(item, funder) for item in clean_grant_tokens(
                f"{record.get('grant_id_raw') or ''}; {text}"
            )
            if valid_grant_for_funder(item, funder)
        ]
        for grant in grants:
            key = (grant.casefold(), record.get("evidence_id", ""))
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "grant": grant,
                "raw_funder": funder,
                "page_number": evidence.get("page_number") or record.get("page_number") or "",
                "source_evidence_id": record.get("evidence_id") or "",
                "text": text,
            })
    return result


def reference_risk(page: str, hit_start: int) -> bool:
    return bool(list(REFERENCE_HEADING.finditer(page[:hit_start])))


def evidence_window(page: str, start: int, end: int) -> tuple[str, int]:
    left = max(0, start - 700)
    right = min(len(page), end + 1800)
    value = page[left:right]
    local = start - left
    before_break = max(value.rfind("\n\n", 0, local), value.rfind(". ", 0, local))
    if before_break >= 0:
        value = value[before_break + (2 if value[before_break:before_break + 2] == ". " else 2):]
        local -= before_break + 2
    stop = STOP_SECTION.search(value, max(local + (end - start), 0))
    if stop:
        value = value[:stop.start()]
    if len(value) > 2600:
        value = value[:2600]
    return compact(value), max(local, 0)


def clean_grant_tokens(value: str) -> list[str]:
    value = re.sub(
        r"\b(20\d{2}-MS)-?\s*lular.{0,160}?\b(\d{2,4})\)",
        r"\1-\2)",
        value,
        flags=re.I | re.S,
    )
    value = re.sub(r"\b(\d{2})\s+(\d{3})\s+(\d{3})\b", r"\1\2\3", value)
    found: list[str] = []
    for token in GRANT_TOKEN.findall(value):
        clean = token.strip(".,;:/()[]{}")
        lower = clean.casefold()
        if YEAR.fullmatch(clean) or DOI.match(clean):
            continue
        if lower.startswith(("pmid", "pmcid", "issn", "isbn", "figure", "table", "supp", "http")):
            continue
        if re.fullmatch(r"\d{1,4}[-–]\d{1,4}", clean):
            continue
        if re.fullmatch(r"\d+\.\d+", clean):
            continue
        if clean not in found:
            found.append(clean)
    return found


def valid_grant_for_funder(grant: str, funder: str) -> bool:
    value = grant.strip(".,;:/()[]{}")
    patterns = {
        "国家自然科学基金委员会（NSFC）": r"(?:\d{8}|U\d{2}A\d{5})",
        "国家重点研发计划": r"20\d{2}YF[A-Z][A-Z0-9/_-]{6,24}",
        "辽宁省自然科学基金": r"20\d{2}(?:-[A-Z]{2,8}-?\d{2,10}|[A-Z]?\d{5,12})",
        "辽宁省兴辽英才计划": r"XLYC[A-Z0-9/_-]{5,30}",
        "中国博士后科学基金": r"20\d{2}M[A-Z0-9/_-]{4,30}",
        "中央高校基本科研业务费": r"DUT[A-Z0-9/_-]{5,30}",
        "长江学者和创新团队发展计划（PCSIRT）": r"IRT[A-Z0-9/_-]{3,30}",
        "浙江省自然科学基金": r"(?=.*[A-Z])(?=.*\d)[A-Z0-9/_-]{7,30}",
        "韩国国家研究基金会": r"(?:NRF-?)?20\d{2}[A-Z0-9/_-]{8,35}",
        "英国医学研究委员会（MRC）": r"MR/[A-Z0-9/_-]{5,30}",
        "英国研究与创新署（UKRI）": r"(?:MR|EP|BB|NE|ES|ST|AH)/[A-Z0-9/_-]{5,30}",
        "英国癌症研究基金会": r"C\d{2,6}/[A-Z0-9/_-]{3,30}",
    }
    return bool(re.fullmatch(patterns[funder], value, re.I))


def canonicalize_grant(grant: str, funder: str) -> str:
    value = grant.strip(".,;:/()[]{}")
    if funder == "韩国国家研究基金会":
        value = re.sub(r"^NRF-", "", value, flags=re.I)
    return value


def target_slice(context: str, funder: str) -> tuple[str, str]:
    pattern = FUNDER_PATTERNS[funder]
    target = pattern.search(context)
    if not target:
        return "", ""
    end = min(len(context), target.end() + 900)
    competing: list[int] = []
    for other, other_pattern in FUNDER_PATTERNS.items():
        if other == funder:
            continue
        match = other_pattern.search(context, target.end())
        if match:
            competing.append(match.start())
    generic = re.search(
        r"[,;]\s*(?:and\s+)?(?:the\s+)?[A-Z][A-Za-z&'() /-]{3,90}"
        r"(?:Foundation|Fund|Program(?:me)?|Council|Commission|Ministry|University)",
        context[target.end():end],
    )
    if generic:
        competing.append(target.end() + generic.start())
    if competing:
        end = min(end, min(competing))
    sentence_stop = re.search(r"\.\s+(?=[A-Z])", context[target.end():end])
    if sentence_stop:
        end = min(end, target.end() + sentence_stop.start() + 1)
    return compact(target.group(0)), context[target.end():end]


def associated_grants(context: str, funder: str) -> tuple[list[str], str]:
    raw_funder, after = target_slice(context, funder)
    if not raw_funder:
        return [], ""
    grants: list[str] = []
    method = ""
    target = FUNDER_PATTERNS[funder].search(context)
    after_wide = context[target.end():target.end() + 1000] if target else after
    # Highest precision: the first nearby parenthetical block containing a
    # funder-shaped identifier. This survives interleaved two-column text.
    for parenthetical in re.finditer(r"(?:\([^)]{1,420}\)|（[^）]{1,420}）)", after_wide):
        candidates = [
            item for item in clean_grant_tokens(parenthetical.group(0))
            if valid_grant_for_funder(item, funder)
        ]
        if candidates:
            grants = [canonicalize_grant(item, funder) for item in candidates]
            method = "资助方后邻近括号"
            break
    if not grants:
        labelled = re.search(
            r"(?:grant|award|project)(?:\s+(?:numbers?|nos?\.?))?\s*[:#-]?\s*"
            r"(.{1,420})",
            after,
            re.I,
        )
        if labelled:
            grants = [
                canonicalize_grant(item, funder) for item in clean_grant_tokens(labelled.group(1))
                if valid_grant_for_funder(item, funder)
            ]
            method = "资助方后编号标签"
    if not grants:
        grants = [
            canonicalize_grant(item, funder) for item in clean_grant_tokens(after_wide[:700])
            if valid_grant_for_funder(item, funder)
        ]
        if grants:
            method = "资助方后限定片段"
    # Some journals use 'grant X from FUNDER'.
    if not grants:
        before = context[max(0, target.start() - 450):target.start()] if target else ""
        if re.search(r"\b(?:grant|award|project)\b", before, re.I):
            grants = [
                canonicalize_grant(item, funder) for item in clean_grant_tokens(before)
                if valid_grant_for_funder(item, funder)
            ]
            if grants:
                method = "资助方前编号标签"
    return grants, method


def project_qualifier(context: str) -> str:
    match = re.search(
        r"\b(?:Youth Fund|Young Scientists? Fund|Key Project|Major Program(?:me)?|"
        r"General Program(?:me)?|Joint Fund|Excellent Young Scientists? Fund|"
        r"Distinguished Young Scholars? Fund|National Science Fund for Distinguished Young Scholars)\b",
        context,
        re.I,
    )
    return compact(match.group(0)) if match else ""


def years_for(grant: str, context: str) -> tuple[str, str]:
    prefix = re.match(r"((?:19|20)\d{2})", grant)
    if prefix:
        return prefix.group(1), "项目编号四位年份前缀"
    if re.fullmatch(r"\d{8}", grant):
        return f"20{grant[1:3]}", "NSFC编号年份线索（待核）"
    match = re.match(r"U(\d{2})A", grant, re.I)
    if match:
        return f"20{match.group(1)}", "NSFC联合基金编号年份线索（待核）"
    match = re.match(r"XLYC(\d{2})", grant, re.I)
    if match:
        return f"20{match.group(1)}", "兴辽英才编号年份线索（待核）"
    match = re.match(r"DUT(\d{2})", grant, re.I)
    if match:
        return f"20{match.group(1)}", "项目编号年份线索（待核）"
    match = re.match(r"(?:LR|LQ|LY|YXD)(\d{2})", grant, re.I)
    if match:
        return f"20{match.group(1)}", "项目编号年份线索（待核）"
    return "", ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--fulltext-package", type=Path, required=True)
    parser.add_argument("--broad-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--selection",
        choices=("incites-only", "all"),
        default="incites-only",
        help="Select only comparison rows marked as InCites-only, or process every input row.",
    )
    parser.add_argument("--expected-relations", type=int, default=180)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    raw_comparison = read_csv(args.comparison)
    if args.selection == "incites-only":
        comparison = [
            row for row in raw_comparison
            if row["对照结果"].startswith("仅InCites")
        ]
    else:
        comparison = raw_comparison
    if len(comparison) != args.expected_relations:
        raise ValueError(
            f"expected {args.expected_relations} selected relations, got {len(comparison)}"
        )
    publication_ids = sorted({row["唯一论文ID"] for row in comparison})

    resources = package_resources(args.fulltext_package)
    broad_records, broad_evidence = broad_package_index(args.broad_package)
    missing = sorted(set(publication_ids) - set(resources))
    if missing:
        raise ValueError(f"missing publication metadata: {missing}")
    resources = {publication_id: resources[publication_id] for publication_id in publication_ids}

    bucket = os.environ["SMARTLIB_S3_BUCKET"]
    client = httpx.Client(timeout=httpx.Timeout(90, connect=10))
    store = S3ObjectStore(
        os.environ["SMARTLIB_S3_ENDPOINT_URL"], bucket,
        os.environ["SMARTLIB_S3_ACCESS_KEY"], os.environ["SMARTLIB_S3_SECRET_KEY"],
        os.environ.get("SMARTLIB_S3_REGION", "us-east-1"), client,
    )

    summaries: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    evidences: list[dict[str, Any]] = []
    text_cache: dict[str, str] = {}
    for index, relation in enumerate(comparison, 1):
        publication_id = relation["唯一论文ID"]
        funder = relation["InCites资助机构"]
        resource = resources[publication_id]
        error = ""
        if publication_id not in text_cache:
            try:
                uri = resource.get("extracted_text_uri")
                if not uri:
                    raise ValueError("extracted_text_uri is empty")
                text_cache[publication_id] = normalize_pdf_text(
                    store.get_bytes(uri_key(uri, bucket)).decode("utf-8", errors="replace")
                )
            except Exception as exc:
                text_cache[publication_id] = ""
                error = f"{type(exc).__name__}: {exc}"
        text = text_cache[publication_id]
        pattern = FUNDER_PATTERNS[funder]
        direct_hits = 0
        confirmed_evidence = 0
        relation_details: list[dict[str, Any]] = []
        seen_evidence: set[str] = set()
        seen_grants: set[str] = set()
        for page_number, page in enumerate(re.split(r"\f+", text), 1):
            for match in pattern.finditer(page):
                direct_hits += 1
                context, _local = evidence_window(page, match.start(), match.end())
                key = re.sub(r"\W+", "", context.casefold())[:900]
                if not context or key in seen_evidence:
                    continue
                seen_evidence.add(key)
                ref_risk = reference_risk(page, match.start())
                raw_funder, _ = target_slice(context, funder)
                grants, association_method = associated_grants(context, funder)
                support = bool(SUPPORT_SIGNAL.search(context)) or bool(grants)
                if support:
                    confirmed_evidence += 1
                evidence_id = f"IG-{publication_id[:8]}-{len(evidences)+1:04d}"
                evidences.append({
                    "证据ID": evidence_id,
                    "唯一论文ID": publication_id,
                    "DOI": relation["DOI"],
                    "论文题名": relation["论文题名"],
                    "InCites资助机构": funder,
                    "PDF页码": page_number,
                    "资助语义明确": "是" if support else "否",
                    "参考文献区域风险": "是" if ref_risk else "否",
                    "资助机构原文": raw_funder or compact(match.group(0)),
                    "项目编号候选": "; ".join(grants),
                    "编号关联方法": association_method,
                    "原文证据": context,
                })
                if not support:
                    continue
                fresh_grants = [grant for grant in grants if grant not in seen_grants]
                for grant in fresh_grants:
                    seen_grants.add(grant)
                    year, year_basis = years_for(grant, context)
                    qualifier = project_qualifier(context)
                    relation_details.append({
                        "唯一论文ID": publication_id,
                        "DOI": relation["DOI"],
                        "WoS入藏号": relation["WoS入藏号"],
                        "论文题名": relation["论文题名"],
                        "出版年": relation["出版年"],
                        "资助机构规范名": funder,
                        "资助机构原文": raw_funder or compact(match.group(0)),
                        "项目名称": f"{funder}{qualifier or '项目'}（{grant}）",
                        "项目名称原文线索": qualifier,
                        "项目编号": grant,
                        "项目年份线索": year,
                        "年份依据": year_basis,
                        "是否形成编号项目对象": "是",
                        "关联置信度": "高" if association_method in {
                            "资助方后相邻括号", "资助方后邻近括号", "资助方后编号标签"
                        } else "中",
                        "PDF页码": page_number,
                        "证据ID": evidence_id,
                        "原文证据": context,
                        "数据来源": "InCites线索+论文PDF原文",
                    })
        if not relation_details:
            for fallback in broad_fallback(
                publication_id, funder, broad_records, broad_evidence
            ):
                grant = fallback["grant"]
                if grant in seen_grants:
                    continue
                seen_grants.add(grant)
                evidence_id = f"IGB-{publication_id[:8]}-{len(evidences)+1:04d}"
                evidences.append({
                    "证据ID": evidence_id,
                    "唯一论文ID": publication_id,
                    "DOI": relation["DOI"],
                    "论文题名": relation["论文题名"],
                    "InCites资助机构": funder,
                    "PDF页码": fallback["page_number"],
                    "资助语义明确": "是",
                    "参考文献区域风险": "否",
                    "资助机构原文": fallback["raw_funder"],
                    "项目编号候选": grant,
                    "编号关联方法": "InCites定向+宽松PDF证据复核",
                    "原文证据": fallback["text"],
                })
                year, year_basis = years_for(grant, fallback["text"])
                qualifier = project_qualifier(fallback["text"])
                relation_details.append({
                    "唯一论文ID": publication_id,
                    "DOI": relation["DOI"],
                    "WoS入藏号": relation["WoS入藏号"],
                    "论文题名": relation["论文题名"],
                    "出版年": relation["出版年"],
                    "资助机构规范名": funder,
                    "资助机构原文": fallback["raw_funder"],
                    "项目名称": f"{funder}{qualifier or '项目'}（{grant}）",
                    "项目名称原文线索": qualifier,
                    "项目编号": grant,
                    "项目年份线索": year,
                    "年份依据": year_basis,
                    "是否形成编号项目对象": "是",
                    "关联置信度": "中（InCites定向+宽松PDF证据）",
                    "PDF页码": fallback["page_number"],
                    "证据ID": evidence_id,
                    "原文证据": fallback["text"],
                    "数据来源": "InCites线索+论文PDF宽松证据",
                })
        if confirmed_evidence and not relation_details:
            first = next(
                item for item in reversed(evidences)
                if item["唯一论文ID"] == publication_id
                and item["InCites资助机构"] == funder
                and item["资助语义明确"] == "是"
            )
            relation_details.append({
                "唯一论文ID": publication_id,
                "DOI": relation["DOI"],
                "WoS入藏号": relation["WoS入藏号"],
                "论文题名": relation["论文题名"],
                "出版年": relation["出版年"],
                "资助机构规范名": funder,
                "资助机构原文": first["资助机构原文"],
                "项目名称": "",
                "项目名称原文线索": "",
                "项目编号": "",
                "项目年份线索": "",
                "年份依据": "",
                "是否形成编号项目对象": "否",
                "关联置信度": "中",
                "PDF页码": first["PDF页码"],
                "证据ID": first["证据ID"],
                "原文证据": first["原文证据"],
                "数据来源": "InCites线索+论文PDF原文",
            })
        details.extend(relation_details)
        numbered = sum(bool(item["项目编号"]) for item in relation_details)
        if error:
            status = "全文读取失败"
        elif numbered:
            status = "已补全编号项目"
        elif confirmed_evidence:
            status = "仅确认资助方，未定位项目编号"
        elif direct_hits:
            status = "仅发现名称提及，资助语义待核"
        else:
            status = "PDF全文未定位该InCites资助方"
        summaries.append({
            "唯一论文ID": publication_id,
            "DOI": relation["DOI"],
            "WoS入藏号": relation["WoS入藏号"],
            "论文题名": relation["论文题名"],
            "出版年": relation["出版年"],
            "InCites资助机构": funder,
            "原比对结果": relation["对照结果"],
            "PDF全文命中次数": direct_hits,
            "明确资助证据条数": confirmed_evidence,
            "补全项目明细条数": len(relation_details),
            "补全编号项目数": numbered,
            "处理状态": status,
            "全文文件名": resource.get("file_name") or "",
            "全文页数": resource.get("page_count") or "",
            "全文提取方式": resource.get("extraction_method") or "",
            "读取异常": error,
        })
        if index % 25 == 0 or index == len(comparison):
            print(f"processed {index}/{len(comparison)} InCites-only relations", flush=True)

    unresolved = [row for row in summaries if row["处理状态"] != "已补全编号项目"]
    generated_at = datetime.now(UTC).isoformat()
    status_counts = Counter(row["处理状态"] for row in summaries)
    metadata = {
        "generated_at": generated_at,
        "method_version": "incites-guided-pdf-funding-completion-v1",
        "scope_incites_only_relations": len(comparison),
        "scope_unique_publications": len(publication_ids),
        "pdf_texts_read": len([value for value in text_cache.values() if value]),
        "completed_numbered_relations": status_counts["已补全编号项目"],
        "numbered_project_rows": sum(bool(row["项目编号"]) for row in details),
        "unique_project_identifiers": len({row["项目编号"].casefold() for row in details if row["项目编号"]}),
        "direct_pdf_project_relations": sum(
            row["数据来源"] == "InCites线索+论文PDF原文" for row in details
        ),
        "recovered_from_interleaved_pdf_evidence": sum(
            row["数据来源"] == "InCites线索+论文PDF宽松证据" for row in details
        ),
        "unnumbered_supported_relations": status_counts["仅确认资助方，未定位项目编号"],
        "unresolved_relations": len(unresolved),
        "status_counts": dict(status_counts),
        "database_writes": 0,
        "interpretation": "InCites only supplies funder hints; project identifiers are retained only when supported by PDF text.",
    }
    package = {"metadata": metadata, "relation_summary": summaries, "project_details": details, "evidence": evidences}
    (args.output / "InCites线索补全项目明细_待审核.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary_columns = list(summaries[0])
    detail_columns = list(details[0]) if details else ["唯一论文ID"]
    evidence_columns = list(evidences[0]) if evidences else ["证据ID"]
    write_csv(args.output / "csv/01_关系处理汇总.csv", summaries, summary_columns)
    write_csv(args.output / "csv/02_项目明细.csv", details, detail_columns)
    write_csv(args.output / "csv/03_原文证据.csv", evidences, evidence_columns)
    write_csv(args.output / "csv/04_仍待核关系.csv", unresolved, summary_columns)

    report = f"""# InCites线索引导的论文PDF项目补全报告

生成时间：{generated_at}

## 范围

- 仅处理 InCites 有、现有全文区域抽取未确认的关系：{len(comparison)} 条。
- 涉及唯一论文：{len(publication_ids)} 篇。
- 本轮忽略“全文有、12份InCites没有”的28条关系。
- 数据库、对象存储、搜索和图谱写入：0 条。

## 结果

- 已补全至少一个编号项目的关系：{status_counts['已补全编号项目']} 条。
- 补出的“论文-资助方-项目编号”明细：{sum(bool(row['项目编号']) for row in details)} 条。
- 唯一项目编号：{len({row['项目编号'].casefold() for row in details if row['项目编号']})} 个。
- 直接从PDF资助语句定位：{sum(row['数据来源'] == 'InCites线索+论文PDF原文' for row in details)} 条明细。
- 从跨栏、断词PDF证据中恢复：{sum(row['数据来源'] == 'InCites线索+论文PDF宽松证据' for row in details)} 条明细。
- 仅确认资助方但未定位项目编号：{status_counts['仅确认资助方，未定位项目编号']} 条。
- 仅名称提及、资助语义仍待核：{status_counts['仅发现名称提及，资助语义待核']} 条。
- PDF全文仍未定位该资助方：{status_counts['PDF全文未定位该InCites资助方']} 条。

## 数据边界

InCites只作为资助方线索。项目名称、编号、年份线索、页码与证据均来自论文PDF文本；没有原文编号时不创建虚构项目。一个资助方后出现多个项目编号时逐号拆分，一篇论文可以保留多个项目。
"""
    (args.output / "检查报告.md").write_text(report, encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
