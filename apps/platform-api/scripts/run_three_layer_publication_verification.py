"""Collect and apply three-layer publication verification evidence.

Layer 1 blocks on publication identity, identifier consistency, duplicate/version
resolution and retraction state. Layer 2 blocks on author-list agreement and an
explicit scholar-to-author match. Layer 3 is non-blocking enrichment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid5

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from smartlib_platform.publications.incremental import submit_publication_supplement
from smartlib_platform.publications.models import (
    FundingSupplementInput,
    PublicationIdentifiers,
    PublicationSupplementCreate,
)
from smartlib_platform.publications.verification_state import refresh_effective_verification_state

RULE_VERSION = "publication-three-layer-v1"
USER_AGENT = "SmartLibKnowledgePlatform/1.0 (library knowledge hub verification)"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
CROSSREF_WORKS = "https://api.crossref.org/works"


def normalized_text(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip()


def normalized_name(value: object) -> str:
    words = normalized_text(value).split()
    if len(words) % 2 == 0 and words[: len(words) // 2] == words[len(words) // 2 :]:
        words = words[: len(words) // 2]
    return " ".join(words)


def similarity(left: object, right: object) -> float:
    left_value, right_value = normalized_text(left), normalized_text(right)
    if not left_value or not right_value:
        return 0.0
    return round(SequenceMatcher(None, left_value, right_value).ratio(), 4)


def json_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def element_text(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    value = "".join(node.itertext()).strip()
    return value or None


def pubmed_date(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    year = element_text(node.find("Year"))
    month = element_text(node.find("Month"))
    day = element_text(node.find("Day"))
    medline = element_text(node.find("MedlineDate"))
    if not year:
        match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", medline or "")
        return match.group(0) if match else None
    month_map = {
        "jan": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "may": "05",
        "jun": "06",
        "jul": "07",
        "aug": "08",
        "sep": "09",
        "oct": "10",
        "nov": "11",
        "dec": "12",
    }
    month_value = month_map.get(
        (month or "").lower()[:3], month.zfill(2) if month and month.isdigit() else "01"
    )
    return f"{year}-{month_value}-{(day or '01').zfill(2)}"


def parse_pubmed_article(article: ET.Element) -> dict[str, Any]:
    citation = article.find("MedlineCitation")
    pubmed_data = article.find("PubmedData")
    if citation is None:
        return {}
    article_node = citation.find("Article")
    if article_node is None:
        return {}
    identifiers = {
        node.attrib.get("IdType", "").lower(): element_text(node)
        for node in (pubmed_data.findall("ArticleIdList/ArticleId") if pubmed_data is not None else [])
    }
    authors = []
    for position, author in enumerate(article_node.findall("AuthorList/Author"), start=1):
        affiliations = [
            value
            for value in (element_text(node) for node in author.findall("AffiliationInfo/Affiliation"))
            if value
        ]
        identifier_nodes = author.findall("Identifier")
        orcid = next(
            (
                element_text(node)
                for node in identifier_nodes
                if node.attrib.get("Source", "").lower() == "orcid"
            ),
            None,
        )
        family = element_text(author.find("LastName"))
        given = element_text(author.find("ForeName"))
        collective = element_text(author.find("CollectiveName"))
        name = collective or " ".join(value for value in (given, family) if value)
        if name:
            authors.append(
                {
                    "order": position,
                    "name": name,
                    "given": given,
                    "family": family,
                    "orcid": orcid,
                    "affiliations": affiliations,
                }
            )
    abstract_parts = []
    for node in article_node.findall("Abstract/AbstractText"):
        value = element_text(node)
        if value:
            label = node.attrib.get("Label")
            abstract_parts.append(f"{label}: {value}" if label else value)
    comments = []
    for node in citation.findall("CommentsCorrectionsList/CommentsCorrections"):
        comments.append(
            {
                "type": node.attrib.get("RefType"),
                "pmid": element_text(node.find("PMID")),
                "source": element_text(node.find("RefSource")),
            }
        )
    journal = article_node.find("Journal")
    issue = journal.find("JournalIssue") if journal is not None else None
    pub_date = issue.find("PubDate") if issue is not None else None
    issn_node = journal.find("ISSN") if journal is not None else None
    electronic_dates = [
        {
            "type": node.attrib.get("PubStatus"),
            "date": "-".join(
                filter(
                    None,
                    [
                        element_text(node.find("Year")),
                        element_text(node.find("Month")),
                        element_text(node.find("Day")),
                    ],
                )
            ),
        }
        for node in (pubmed_data.findall("History/PubMedPubDate") if pubmed_data is not None else [])
    ]
    return {
        "schema_version": 3,
        "pmid": element_text(citation.find("PMID")),
        "pmcid": identifiers.get("pmc"),
        "doi": (identifiers.get("doi") or "").lower() or None,
        "title": element_text(article_node.find("ArticleTitle")),
        "abstract": "\n".join(abstract_parts) or None,
        "journal_name": element_text(journal.find("Title")) if journal is not None else None,
        "journal_abbreviation": element_text(journal.find("ISOAbbreviation"))
        if journal is not None
        else None,
        "issn": element_text(issn_node),
        "issn_type": issn_node.attrib.get("IssnType") if issn_node is not None else None,
        "publication_date": pubmed_date(pub_date),
        "volume": element_text(issue.find("Volume")) if issue is not None else None,
        "issue": element_text(issue.find("Issue")) if issue is not None else None,
        "pages": element_text(article_node.find("Pagination/MedlinePgn")),
        "article_number": element_text(article_node.find("ELocationID")),
        "languages": [
            value for value in (element_text(node) for node in article_node.findall("Language")) if value
        ],
        "publication_types": [
            value
            for value in (
                element_text(node) for node in article_node.findall("PublicationTypeList/PublicationType")
            )
            if value
        ],
        "authors": authors,
        "mesh_terms": [
            value
            for value in (
                element_text(node) for node in citation.findall("MeshHeadingList/MeshHeading/DescriptorName")
            )
            if value
        ],
        "keywords": [
            value
            for value in (element_text(node) for node in citation.findall("KeywordList/Keyword"))
            if value
        ],
        "comments_corrections": comments,
        "grants": [
            {
                "grant_id": element_text(node.find("GrantID")),
                "agency": element_text(node.find("Agency")),
                "country": element_text(node.find("Country")),
            }
            for node in citation.findall("Article/GrantList/Grant")
        ],
        "history": electronic_dates,
    }


def fetch_pubmed_details(pmids: list[str], cache_path: Path, offline: bool) -> dict[str, dict[str, Any]]:
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    missing = [pmid for pmid in pmids if cache.get(pmid, {}).get("schema_version") != 3]
    if offline:
        return cache
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0) as client:
        for start in range(0, len(missing), 100):
            batch = missing[start : start + 100]
            response = client.get(
                PUBMED_EFETCH,
                params={"db": "pubmed", "id": ",".join(batch), "retmode": "xml", "tool": "smartlib_verifier"},
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)
            found = {}
            for article in root.findall("PubmedArticle"):
                value = parse_pubmed_article(article)
                if value.get("pmid"):
                    found[value["pmid"]] = value
            for pmid in batch:
                cache[pmid] = found.get(pmid, {"schema_version": 3, "not_found": True})
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
            time.sleep(0.4)
    return cache


def crossref_date(candidate: dict[str, Any], key: str) -> str | None:
    values = (candidate.get(key) or {}).get("date-parts") or []
    if not values or not values[0]:
        return None
    parts = [str(value).zfill(2) for value in values[0]]
    return "-".join(parts + ["01"] * (3 - len(parts)))


def compact_crossref_detail(candidate: dict[str, Any]) -> dict[str, Any]:
    authors = []
    for position, author in enumerate(candidate.get("author") or [], start=1):
        given, family = author.get("given"), author.get("family")
        authors.append(
            {
                "order": position,
                "name": " ".join(value for value in (given, family) if value),
                "given": given,
                "family": family,
                "orcid": str(author.get("ORCID") or "").removeprefix("https://orcid.org/") or None,
                "sequence": author.get("sequence"),
                "affiliations": [
                    item.get("name") for item in author.get("affiliation") or [] if item.get("name")
                ],
            }
        )
    issn_types = {item.get("type"): item.get("value") for item in candidate.get("issn-type") or []}
    return {
        "schema_version": 3,
        "doi": str(candidate.get("DOI") or "").lower() or None,
        "title": ((candidate.get("title") or [None])[0]),
        "abstract": candidate.get("abstract"),
        "journal_name": ((candidate.get("container-title") or [None])[0]),
        "publisher": candidate.get("publisher"),
        "publication_type": candidate.get("type"),
        "published_online_at": crossref_date(candidate, "published-online"),
        "published_print_at": crossref_date(candidate, "published-print"),
        "volume": candidate.get("volume"),
        "issue": candidate.get("issue"),
        "pages": candidate.get("page"),
        "article_number": candidate.get("article-number"),
        "issn": issn_types.get("print") or ((candidate.get("ISSN") or [None])[0]),
        "eissn": issn_types.get("electronic"),
        "authors": authors,
        "subjects": candidate.get("subject") or [],
        "licenses": candidate.get("license") or [],
        "links": candidate.get("link") or [],
        "funders": candidate.get("funder") or [],
        "relations": candidate.get("relation") or {},
        "updates": candidate.get("update-to") or [],
        "url": candidate.get("URL"),
    }


def fetch_crossref_details(dois: list[str], cache_path: Path, offline: bool) -> dict[str, dict[str, Any]]:
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    missing = [doi for doi in dois if cache.get(doi, {}).get("schema_version") != 3]
    if offline:
        return cache
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=45.0, follow_redirects=True) as client:
        for position, doi in enumerate(missing, start=1):
            response = client.get(f"{CROSSREF_WORKS}/{quote(doi, safe='')}")
            if response.status_code == 404:
                cache[doi] = {"schema_version": 3, "not_found": True}
            else:
                response.raise_for_status()
                cache[doi] = compact_crossref_detail(response.json()["message"])
            if position % 10 == 0 or position == len(missing):
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
            time.sleep(0.12)
    return cache


def check(
    code: str,
    label: str,
    status: str,
    severity: str,
    source: object = None,
    authoritative: object = None,
    sources: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "check_code": code,
        "check_label": label,
        "check_status": status,
        "severity": severity,
        "source_value": source,
        "authoritative_value": authoritative,
        "evidence_sources": sources or [],
        "details": details or {},
    }


def value_check(
    code: str, label: str, source: object, authoritative: object, severity: str, threshold: float = 1.0
) -> dict[str, Any]:
    if source in (None, "") and authoritative in (None, ""):
        return check(code, label, "not_applicable", severity, source, authoritative)
    if authoritative in (None, ""):
        return check(code, label, "missing", severity, source, authoritative)
    if source in (None, ""):
        return check(code, label, "missing", "warning", source, authoritative)
    score = similarity(source, authoritative)
    return check(
        code,
        label,
        "passed" if score >= threshold else "conflict",
        severity,
        source,
        authoritative,
        details={"similarity": score, "threshold": threshold},
    )


def identifier_association_check(
    source: dict[str, Any], authority: dict[str, Any], ncbi: dict[str, Any]
) -> dict[str, Any]:
    """Verify that available DOI, PMID, and PMCID values identify one publication."""
    comparisons: list[dict[str, Any]] = []

    def compare(code: str, label: str, left: object, right: object, *, optional: bool = False) -> None:
        left_value = str(left or "").strip()
        right_value = str(right or "").strip()
        if not left_value and not right_value:
            status = "not_applicable" if optional else "missing"
        elif not left_value or not right_value:
            status = "not_applicable" if optional and not left_value else "missing"
        else:
            status = "passed" if normalized_text(left_value) == normalized_text(right_value) else "conflict"
        comparisons.append(
            {
                "code": code,
                "label": label,
                "status": status,
                "source_value": left_value or None,
                "authoritative_value": right_value or None,
            }
        )

    compare("source_crossref_doi", "Excel DOI 与 Crossref DOI", source.get("doi"), authority.get("doi"))
    compare("crossref_pubmed_doi", "Crossref DOI 与 PubMed DOI", authority.get("doi"), ncbi.get("doi"))
    compare("source_pubmed_pmid", "Excel PMID 与 PubMed PMID", source.get("pmid"), ncbi.get("pmid"))
    compare(
        "source_pubmed_pmcid",
        "Excel PMCID 与 PubMed PMCID",
        source.get("pmcid"),
        ncbi.get("pmcid"),
        optional=True,
    )
    pubmed_pmid = str(ncbi.get("pmid") or "").strip()
    pubmed_pmcid = str(ncbi.get("pmcid") or "").strip()
    comparisons.append(
        {
            "code": "pubmed_pmid_pmcid",
            "label": "PubMed PMID 与 PMCID 关联",
            "status": (
                "passed"
                if pubmed_pmid and pubmed_pmcid
                else "not_applicable"
                if pubmed_pmid and not pubmed_pmcid
                else "missing"
                if pubmed_pmcid
                else "not_applicable"
            ),
            "source_value": pubmed_pmid or None,
            "authoritative_value": pubmed_pmcid or None,
        }
    )

    conflicts = [item for item in comparisons if item["status"] == "conflict"]
    comparable = [item for item in comparisons if item["status"] in {"passed", "conflict"}]
    missing_required = [
        item
        for item in comparisons
        if item["status"] == "missing" and item["code"] != "source_pubmed_pmcid"
    ]
    status = "conflict" if conflicts else "passed" if comparable and not missing_required else "missing"
    return check(
        "identifier_triangle",
        "标识符关联校验",
        status,
        "blocking",
        {"doi": source.get("doi"), "pmid": source.get("pmid"), "pmcid": source.get("pmcid")},
        {
            "crossref_doi": authority.get("doi"),
            "pubmed_doi": ncbi.get("doi"),
            "pubmed_pmid": ncbi.get("pmid"),
            "pubmed_pmcid": ncbi.get("pmcid"),
            "comparisons": comparisons,
        },
        ["crossref", "ncbi_pubmed"],
        {
            "comparison_count": len(comparable),
            "conflict_count": len(conflicts),
            "pmcid_optional": True,
        },
    )


def layer_status(checks: list[dict[str, Any]], blocking: bool) -> str:
    blocking_checks = [item for item in checks if item["severity"] == "blocking"] if blocking else checks
    if any(item["check_status"] == "conflict" for item in blocking_checks):
        return "conflict"
    if any(item["check_status"] in {"pending", "missing"} for item in blocking_checks):
        return "incomplete"
    if not blocking and any(item["check_status"] == "missing" for item in checks):
        return "incomplete"
    return "passed"


def author_agreement(
    source_authors: list[str], authority_authors: list[dict[str, Any]]
) -> tuple[float, list[dict[str, Any]]]:
    if not source_authors or not authority_authors:
        return 0.0, []
    comparisons = []
    for source_name in source_authors:
        ranked = sorted(
            (
                (similarity(normalized_name(source_name), normalized_name(author.get("name"))), author)
                for author in authority_authors
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        score, author = ranked[0]
        comparisons.append(
            {
                "source_name": source_name,
                "candidate_order": author.get("order"),
                "candidate_name": author.get("name"),
                "score": score,
            }
        )
    return round(sum(item["score"] for item in comparisons) / len(comparisons), 4), comparisons


def build_record(
    item: dict[str, Any],
    automatic: dict[str, Any],
    crossref: dict[str, Any],
    pubmed: dict[str, Any],
    duplicate_dois: dict[str, list[str]],
    duplicate_titles: dict[str, list[str]],
) -> dict[str, Any]:
    source = item["normalized_payload"]
    compact_crossref = automatic.get("crossref") or {}
    authority = crossref if crossref and not crossref.get("not_found") else compact_crossref
    ncbi = pubmed if pubmed and not pubmed.get("not_found") else (automatic.get("ncbi_pubmed") or {})
    identity = [
        value_check("title", "题名一致性", source.get("title"), authority.get("title"), "blocking", 0.97),
        value_check(
            "journal",
            "期刊一致性",
            source.get("journal_or_conference"),
            authority.get("journal_name"),
            "blocking",
            0.75,
        ),
        value_check(
            "publication_year",
            "发表年份一致性",
            source.get("publication_year"),
            (
                authority.get("published_print_at")
                or authority.get("published_online_at")
                or str(authority.get("publication_year") or "")
            )[:4],
            "blocking",
            1.0,
        ),
        value_check("doi", "DOI一致性", source.get("doi"), authority.get("doi"), "blocking", 1.0),
        value_check("pmid", "PMID一致性", source.get("pmid"), ncbi.get("pmid"), "blocking", 1.0),
        value_check("pmcid", "PMCID一致性", source.get("pmcid"), ncbi.get("pmcid"), "blocking", 1.0),
        value_check("wos_ut", "WoS UT登记", source.get("wos_ut"), source.get("wos_ut"), "warning", 1.0),
    ]
    identity.append(identifier_association_check(source, authority, ncbi))
    doi_group = duplicate_dois.get(str(source.get("doi") or "").lower(), []) if source.get("doi") else []
    title_key = f"{normalized_text(source.get('title'))}|{source.get('publication_year') or ''}"
    title_group = duplicate_titles.get(title_key, [])
    duplicate_status = "conflict" if len(title_group) > 1 and not source.get("doi") else "passed"
    identity.append(
        check(
            "duplicate_resolution",
            "重复论文归并",
            duplicate_status,
            "blocking",
            details={"same_doi_items": doi_group, "same_title_year_items": title_group},
        )
    )
    pub_types = [str(value).casefold() for value in ncbi.get("publication_types") or []]
    corrections = ncbi.get("comments_corrections") or []
    updates = authority.get("updates") or []
    lifecycle_evidence_available = authority.get("schema_version") == 3 or ncbi.get("schema_version") == 3
    retracted = (
        "retracted publication" in pub_types
        or any(
            str(value.get("type", "")).casefold() in {"retractionof", "retractionin"} for value in corrections
        )
        or any(str(value.get("type", "")).casefold() == "retraction" for value in updates)
    )
    identity.append(
        check(
            "lifecycle",
            "撤稿、勘误与版本状态",
            "conflict" if retracted else "passed" if lifecycle_evidence_available else "missing",
            "blocking",
            authoritative={
                "publication_types": ncbi.get("publication_types") or [],
                "comments_corrections": corrections,
                "crossref_updates": updates,
                "crossref_relations": authority.get("relations") or {},
            },
            sources=["crossref", "ncbi_pubmed"],
            details={"retracted": retracted},
        )
    )

    authority_authors = authority.get("authors") or ncbi.get("authors") or []
    authority_authors = [
        {
            **author,
            "order": author.get("order") or position,
            "name": author.get("name")
            or " ".join(value for value in (author.get("given"), author.get("family")) if value),
        }
        for position, author in enumerate(authority_authors, start=1)
    ]
    source_authors = source.get("authors_raw_list") or []
    agreement, comparisons = author_agreement(source_authors, authority_authors)
    awardee = source.get("awardee_name")
    exact_awardee = next(
        (
            index
            for index, value in enumerate(source_authors, start=1)
            if normalized_name(value) == normalized_name(awardee)
        ),
        None,
    )
    attribution = [
        check(
            "author_list_available",
            "权威作者列表",
            "passed" if authority_authors else "missing",
            "blocking",
            source_authors,
            authority_authors,
            ["crossref", "ncbi_pubmed"],
        ),
        check(
            "author_list_agreement",
            "作者顺序与名单一致性",
            "passed" if agreement >= 0.85 else "conflict",
            "blocking",
            source_authors,
            authority_authors,
            ["crossref", "ncbi_pubmed"],
            {"agreement": agreement, "comparisons": comparisons},
        ),
        check(
            "awardee_author_match",
            "获批人作者身份",
            "passed" if exact_awardee else "pending",
            "blocking",
            awardee,
            {"selected_author_order": exact_awardee, "candidates": authority_authors},
            ["controlled_excel", "crossref", "ncbi_pubmed"],
            {"requires_human_selection": exact_awardee is None},
        ),
        check(
            "corresponding_author",
            "通讯作者身份",
            "missing",
            "warning",
            item.get("raw_payload", {}).get("SCI通讯作者"),
            None,
            ["controlled_excel", "ncbi_pubmed"],
        ),
        check(
            "author_orcid",
            "作者ORCID覆盖",
            "passed" if any(value.get("orcid") for value in authority_authors) else "missing",
            "warning",
            authoritative=[value.get("orcid") for value in authority_authors if value.get("orcid")],
        ),
        check(
            "author_affiliation",
            "作者单位覆盖",
            "passed" if any(value.get("affiliations") for value in authority_authors) else "missing",
            "warning",
            authoritative=[
                value.get("affiliations") for value in authority_authors if value.get("affiliations")
            ],
        ),
    ]

    abstract = ncbi.get("abstract") or authority.get("abstract")
    mesh = ncbi.get("mesh_terms") or []
    keywords = ncbi.get("keywords") or authority.get("subjects") or []
    fulltext = [
        value.get("URL") or value.get("url")
        for value in authority.get("links") or []
        if value.get("URL") or value.get("url")
    ]
    if ncbi.get("pmcid"):
        fulltext.append(f"https://pmc.ncbi.nlm.nih.gov/articles/{ncbi['pmcid']}/")
    enrichment = [
        check(
            "abstract",
            "摘要",
            "passed" if abstract else "missing",
            "info",
            authoritative=abstract,
            sources=["ncbi_pubmed", "crossref"],
        ),
        check(
            "keywords_mesh",
            "关键词与MeSH主题词",
            "passed" if mesh or keywords else "missing",
            "info",
            authoritative={"mesh_terms": mesh, "keywords": keywords},
        ),
        check(
            "issn",
            "ISSN/EISSN",
            "passed" if authority.get("issn") or authority.get("eissn") or ncbi.get("issn") else "missing",
            "info",
            authoritative={
                "issn": authority.get("issn") or ncbi.get("issn"),
                "eissn": authority.get("eissn"),
            },
        ),
        check(
            "publication_dates",
            "线上及纸质发表日期",
            "passed"
            if authority.get("published_online_at")
            or authority.get("published_print_at")
            or ncbi.get("publication_date")
            else "missing",
            "info",
            authoritative={
                "online": authority.get("published_online_at"),
                "print": authority.get("published_print_at"),
                "pubmed": ncbi.get("publication_date"),
            },
        ),
        check(
            "bibliographic_extent",
            "卷期页码或文章号",
            "passed"
            if (authority.get("volume") or ncbi.get("volume"))
            and (
                authority.get("pages")
                or authority.get("article_number")
                or ncbi.get("pages")
                or ncbi.get("article_number")
            )
            else "missing",
            "info",
            authoritative={
                key: authority.get(key) or ncbi.get(key)
                for key in ("volume", "issue", "pages", "article_number")
            },
        ),
        check(
            "publication_type",
            "论文类型",
            "passed" if authority.get("publication_type") or ncbi.get("publication_types") else "missing",
            "info",
            authoritative={
                "crossref": authority.get("publication_type"),
                "pubmed": ncbi.get("publication_types"),
            },
        ),
        check(
            "open_access_fulltext",
            "开放获取与全文入口",
            "passed" if fulltext or authority.get("licenses") else "missing",
            "info",
            authoritative={
                "pmcid": ncbi.get("pmcid"),
                "licenses": authority.get("licenses") or [],
                "fulltext_urls": fulltext,
            },
        ),
        check(
            "funding",
            "基金资助信息",
            "passed" if authority.get("funders") or ncbi.get("grants") else "missing",
            "info",
            authoritative={"crossref": authority.get("funders") or [], "pubmed": ncbi.get("grants") or []},
        ),
    ]
    layers = {
        "identity": {"is_blocking": True, "checks": identity},
        "attribution": {"is_blocking": True, "checks": attribution},
        "enrichment": {"is_blocking": False, "checks": enrichment},
    }
    for value in layers.values():
        value["layer_status"] = layer_status(value["checks"], value["is_blocking"])
    enriched = {
        "abstract": abstract,
        "journal_abbreviation": ncbi.get("journal_abbreviation"),
        "issn": authority.get("issn") or ncbi.get("issn"),
        "eissn": authority.get("eissn"),
        "published_online_at": authority.get("published_online_at"),
        "published_print_at": authority.get("published_print_at"),
        "volume": authority.get("volume") or ncbi.get("volume"),
        "issue": authority.get("issue") or ncbi.get("issue"),
        "pages": authority.get("pages") or ncbi.get("pages"),
        "article_number": authority.get("article_number") or ncbi.get("article_number"),
        "publication_type": authority.get("publication_type"),
        "language_code": (ncbi.get("languages") or [None])[0],
        "authors": authority_authors,
        "mesh_terms": mesh,
        "keywords": keywords,
        "licenses": authority.get("licenses") or [],
        "fulltext_urls": fulltext,
        "funders": authority.get("funders") or [],
        "grants": ncbi.get("grants") or [],
        "lifecycle": identity[-1]["authoritative_value"],
    }
    return {"record_id": item["record_id"], "layers": layers, "enriched_metadata": enriched}


def collect(
    package_path: Path, automatic_path: Path, cache_dir: Path, output_path: Path, offline: bool
) -> dict[str, Any]:
    package = json.loads(package_path.read_text())
    automatic_payload = json.loads(automatic_path.read_text())
    automatic = {value["record_id"]: value for value in automatic_payload["records"]}
    pmids = sorted(
        {
            value["normalized_payload"].get("pmid")
            for value in package["items"]
            if value["normalized_payload"].get("pmid")
        }
    )
    dois = sorted(
        {
            value["normalized_payload"].get("doi")
            for value in package["items"]
            if value["normalized_payload"].get("doi")
        }
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    pubmed = fetch_pubmed_details(pmids, cache_dir / "pubmed_detail.json", offline)
    crossref = fetch_crossref_details(dois, cache_dir / "crossref_detail.json", offline)
    doi_groups: dict[str, list[str]] = defaultdict(list)
    title_groups: dict[str, list[str]] = defaultdict(list)
    for item in package["items"]:
        source = item["normalized_payload"]
        if source.get("doi"):
            doi_groups[str(source["doi"]).lower()].append(item["record_id"])
        title_groups[f"{normalized_text(source.get('title'))}|{source.get('publication_year') or ''}"].append(
            item["record_id"]
        )
    records = []
    for item in package["items"]:
        source = item["normalized_payload"]
        records.append(
            build_record(
                item,
                automatic[item["record_id"]],
                crossref.get(source.get("doi"), {}),
                pubmed.get(source.get("pmid"), {}),
                doi_groups,
                title_groups,
            )
        )
    layer_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for record in records:
        for code, value in record["layers"].items():
            layer_counts[code][value["layer_status"]] += 1
    result = {
        "manifest": {
            "dataset_version": package["manifest"]["dataset_version"],
            "rule_version": RULE_VERSION,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "record_count": len(records),
            "offline": offline,
            "layer_counts": layer_counts,
        },
        "records": records,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def apply(result: dict[str, Any], database_url: str, actor_id: UUID, namespace: UUID) -> dict[str, Any]:
    applied_layers = applied_checks = enriched = relations_pending = 0
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT set_config('smartlib.actor_id', %s, true)", (str(actor_id),))
            for record in result["records"]:
                record_id = UUID(record["record_id"])
                item = connection.execute(
                    """SELECT matched_publication_id, awardee_person_id
                         FROM (smartlib.publication_intake_record item
                  JOIN smartlib.ingestion_record input_record USING(record_id)
                  LEFT JOIN smartlib.representative_work_submission submission USING(record_id))
                        WHERE record_id=%s""",
                    (record_id,),
                ).fetchone()
                for layer_code, layer in record["layers"].items():
                    layer_id = uuid5(namespace, f"three-layer:{record_id}:{layer_code}")
                    counts = defaultdict(int)
                    for value in layer["checks"]:
                        counts[value["check_status"]] += 1
                    connection.execute(
                        """INSERT INTO smartlib.publication_verification_layer
                                  (layer_id,record_id,layer_code,layer_status,is_blocking,check_count,
                                   passed_count,conflict_count,missing_count,rule_version,evidence_summary,
                                   evaluated_at,created_by)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                             ON CONFLICT (record_id,layer_code) DO UPDATE SET
                               layer_status=excluded.layer_status,is_blocking=excluded.is_blocking,
                               check_count=excluded.check_count,passed_count=excluded.passed_count,
                               conflict_count=excluded.conflict_count,missing_count=excluded.missing_count,
                               rule_version=excluded.rule_version,evidence_summary=excluded.evidence_summary,
                               evaluated_at=excluded.evaluated_at""",
                        (
                            layer_id,
                            record_id,
                            layer_code,
                            layer["layer_status"],
                            layer["is_blocking"],
                            len(layer["checks"]),
                            counts["passed"],
                            counts["conflict"],
                            counts["missing"] + counts["pending"],
                            result["manifest"]["rule_version"],
                            Jsonb({"status_counts": counts}),
                            result["manifest"]["retrieved_at"],
                            actor_id,
                        ),
                    )
                    applied_layers += 1
                    for value in layer["checks"]:
                        check_id = uuid5(
                            namespace,
                            f"three-layer-check:{record_id}:{layer_code}:{value['check_code']}",
                        )
                        connection.execute(
                            """INSERT INTO smartlib.publication_verification_check
                                      (check_id,layer_id,check_code,check_label,check_status,severity,
                                       source_value,authoritative_value,evidence_sources,details,created_by)
                                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                 ON CONFLICT (layer_id,check_code) DO UPDATE SET
                                   check_label=excluded.check_label,check_status=excluded.check_status,
                                   severity=excluded.severity,source_value=excluded.source_value,
                                   authoritative_value=excluded.authoritative_value,
                                   evidence_sources=excluded.evidence_sources,details=excluded.details""",
                            (
                                check_id,
                                layer_id,
                                value["check_code"],
                                value["check_label"],
                                value["check_status"],
                                value["severity"],
                                Jsonb(value["source_value"]),
                                Jsonb(value["authoritative_value"]),
                                Jsonb(value["evidence_sources"]),
                                Jsonb(value["details"]),
                                actor_id,
                            ),
                        )
                        applied_checks += 1
                publication_id = item["matched_publication_id"] if item else None
                metadata = record["enriched_metadata"]
                if publication_id:
                    identity_checks = {
                        value["check_code"]: value.get("authoritative_value")
                        for value in record["layers"]["identity"]["checks"]
                    }
                    supplement_metadata = {
                        key: value
                        for key, value in metadata.items()
                        if key != "authors" and value not in (None, "", [])
                    }
                    funding_inputs: list[FundingSupplementInput] = []
                    seen_funding: set[tuple[str, str]] = set()
                    for value in [*(metadata.get("funders") or []), *(metadata.get("grants") or [])]:
                        if not isinstance(value, dict):
                            continue
                        funder_name = str(value.get("name") or value.get("agency") or "").strip()
                        awards = value.get("award") or value.get("grant_id") or value.get("award-number")
                        award_values = awards if isinstance(awards, list) else [awards]
                        for award in award_values or [None]:
                            key = (funder_name.casefold(), str(award or "").casefold())
                            if not funder_name or key in seen_funding:
                                continue
                            seen_funding.add(key)
                            funding_inputs.append(FundingSupplementInput(
                                funder_name=funder_name,
                                grant_id=str(award).strip() if award else None,
                                country=str(value.get("country") or "").strip() or None,
                                metadata=value,
                            ))
                    command_payload = {
                        "metadata": supplement_metadata,
                        "identifiers": {
                            "doi": identity_checks.get("doi"),
                            "pmid": identity_checks.get("pmid"),
                            "pmcid": identity_checks.get("pmcid"),
                        },
                        "funding": [value.model_dump(mode="json") for value in funding_inputs],
                        "rule_version": result["manifest"]["rule_version"],
                    }
                    submit_publication_supplement(
                        connection,
                        publication_id,
                        PublicationSupplementCreate(
                            source_kind="metadata",
                            source_label="Crossref 与 NCBI 在线补采",
                            content_checksum=json_hash(command_payload),
                            metadata=supplement_metadata,
                            identifiers=PublicationIdentifiers(**command_payload["identifiers"]),
                            funding=funding_inputs,
                            note="自动在线核验产生的增量证据",
                        ),
                        actor_id,
                        result["manifest"]["rule_version"],
                    )
                    enriched += 1
                    for author in metadata.get("authors") or []:
                        if not author.get("order"):
                            continue
                        connection.execute(
                            """UPDATE smartlib.publication_authorship SET
                                   given_name=COALESCE(given_name,%s),family_name=COALESCE(family_name,%s),
                                   orcid=COALESCE(orcid,%s),affiliation_raw=COALESCE(affiliation_raw,%s)
                                 WHERE publication_id=%s AND author_order=%s""",
                            (
                                author.get("given"),
                                author.get("family"),
                                author.get("orcid"),
                                "; ".join(author.get("affiliations") or []) or None,
                                publication_id,
                                author["order"],
                            ),
                        )
                    # Attribution checks remain verification evidence. They no longer
                    # mutate person.authored directly: that graph edge is derived only
                    # from matched publication_authorship authority rows.
                refresh_effective_verification_state(connection, record_id=record_id)
            audit_id = uuid5(namespace, f"audit:{RULE_VERSION}:{result['manifest']['retrieved_at']}")
            connection.execute(
                """INSERT INTO audit.audit_event
                          (event_id,actor_id,action,resource_type,resource_id,
                           decision,trace_id,details)
                     VALUES (%s,%s,'publication.three_layer_verification_applied',
                             'ingestion_batch',%s,'recorded',%s,%s)""",
                (
                    audit_id,
                    actor_id,
                    result["manifest"]["dataset_version"],
                    RULE_VERSION,
                    Jsonb(
                        {
                            "layers": applied_layers,
                            "checks": applied_checks,
                            "enriched_publications": enriched,
                            "relations_moved_to_pending": relations_pending,
                            "layer_counts": result["manifest"]["layer_counts"],
                        }
                    ),
                ),
            )
    return {
        "layers": applied_layers,
        "checks": applied_checks,
        "enriched_publications": enriched,
        "relations_moved_to_pending": relations_pending,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--automatic", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = collect(args.package, args.automatic, args.cache_dir, args.output, args.offline)
    response: dict[str, Any] = {"manifest": result["manifest"]}
    if args.apply:
        package = json.loads(args.package.read_text())
        response["applied"] = apply(
            result,
            os.environ["SMARTLIB_DATABASE_URL"],
            UUID(os.environ["SMARTLIB_DEV_ACTOR_ID"]),
            UUID(package["manifest"]["uuid_namespace"]),
        )
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
