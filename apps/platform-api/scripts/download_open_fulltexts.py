#!/usr/bin/env python3
"""Download legally public PDF candidates for controlled publication rows.

The downloader uses public metadata from Europe PMC, OpenAlex, Crossref and
Semantic Scholar.  Every accepted file must be a readable PDF and must match
the expected DOI or title in its first pages.  HTML/login/error responses are
kept only as attempt evidence and are never treated as full text.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


USER_AGENT = "SmartLib-Knowledge-Platform/1.0 (open-access fulltext verification)"
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
NON_WORD_PATTERN = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
SPACE_PATTERN = re.compile(r"\s+")


def normalize(value: object) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(str(value or ""))).casefold()
    return NON_WORD_PATTERN.sub("", value)


def normalize_doi(value: object) -> str:
    value = str(value or "").strip().casefold()
    value = value.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    return value.rstrip(".,;)")


def request(url: str, *, accept: str, timeout: int) -> tuple[bytes, str, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(367001601)
        return data, response.headers.get_content_type(), response.geturl()


def get_json(url: str, timeout: int) -> dict[str, Any]:
    data, _, _ = request(url, accept="application/json", timeout=timeout)
    value = json.loads(data.decode("utf-8"))
    return value if isinstance(value, dict) else {}


def candidate_key(value: dict[str, Any]) -> str:
    return str(value.get("url") or "").strip()


def add_candidate(
    candidates: list[dict[str, Any]],
    seen: set[str],
    url: object,
    provider: str,
    priority: int,
) -> None:
    normalized = str(url or "").strip()
    if not normalized or normalized in seen:
        return
    if not normalized.startswith(("https://", "http://", "ftp://")):
        return
    if normalized.casefold().endswith((".xml", ".tar.gz", ".zip")):
        return
    seen.add(normalized)
    candidates.append({"url": normalized, "provider": provider, "priority": priority})


def europe_pmc_candidates(target: dict[str, Any], timeout: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result: dict[str, Any] = {}
    pmcid = str(target.get("pmcid") or "").strip().upper()
    query = ""
    if target.get("pmid"):
        query = f"EXT_ID:{target['pmid']} AND SRC:MED"
    elif target.get("doi"):
        query = f'DOI:"{target["doi"]}"'
    if query:
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(
            {"query": query, "format": "json", "pageSize": 5, "resultType": "core"}
        )
        payload = get_json(url, timeout)
        rows = payload.get("resultList", {}).get("result", [])
        expected_doi = normalize_doi(target.get("doi"))
        for row in rows:
            row_doi = normalize_doi(row.get("doi"))
            row_pmid = str(row.get("pmid") or row.get("id") or "")
            if expected_doi and row_doi and row_doi != expected_doi:
                continue
            if target.get("pmid") and row_pmid and row_pmid != str(target["pmid"]):
                continue
            result = row
            pmcid = pmcid or str(row.get("pmcid") or "").strip().upper()
            break
    candidates: list[dict[str, Any]] = []
    if pmcid:
        candidates.append(
            {
                "url": f"https://europepmc.org/articles/{pmcid}?pdf=render",
                "provider": "Europe PMC Open PDF",
                "priority": 1,
            }
        )
        try:
            oa_url = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?" + urllib.parse.urlencode(
                {"id": pmcid}
            )
            xml_data, _, _ = request(oa_url, accept="application/xml", timeout=timeout)
            root = ET.fromstring(xml_data)
            for link in root.findall(".//link"):
                if link.attrib.get("format") == "pdf":
                    candidates.insert(
                        0,
                        {
                            "url": link.attrib.get("href", ""),
                            "provider": "NCBI PMC OA package",
                            "priority": 0,
                        },
                    )
        except Exception:
            pass
    return candidates, result


def openalex_candidates(doi: str, timeout: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not doi:
        return [], {}
    url = "https://api.openalex.org/works/https://doi.org/" + urllib.parse.quote(doi, safe="/()")
    payload = get_json(url, timeout)
    candidates: list[dict[str, Any]] = []
    locations = [payload.get("best_oa_location") or {}, *(payload.get("locations") or [])]
    seen: set[str] = set()
    for location in locations:
        if not isinstance(location, dict):
            continue
        pdf_url = location.get("pdf_url")
        if pdf_url and (location.get("is_oa") is not False):
            add_candidate(candidates, seen, pdf_url, "OpenAlex OA location", 10)
    return candidates, payload


def crossref_candidates(doi: str, timeout: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not doi:
        return [], {}
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    payload = get_json(url, timeout).get("message", {})
    candidates: list[dict[str, Any]] = []
    for link in payload.get("link") or []:
        content_type = str(link.get("content-type") or "").casefold()
        if "pdf" in content_type:
            candidates.append(
                {
                    "url": link.get("URL", ""),
                    "provider": "Crossref publisher PDF",
                    "priority": 30,
                }
            )
    return candidates, payload


def semantic_scholar_candidates(doi: str, timeout: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not doi:
        return [], {}
    paper_id = urllib.parse.quote(f"DOI:{doi}", safe=":")
    url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}?fields=title,year,openAccessPdf,externalIds"
    payload = get_json(url, timeout)
    pdf = payload.get("openAccessPdf") or {}
    if isinstance(pdf, dict) and pdf.get("url"):
        return [{"url": pdf["url"], "provider": "Semantic Scholar OA link", "priority": 20}], payload
    return [], payload


def inspect_pdf(path: Path, expected_doi: str, expected_title: str, timeout: int) -> dict[str, Any]:
    info = subprocess.run(
        ["pdfinfo", str(path)], capture_output=True, text=True, timeout=timeout, check=False
    )
    if info.returncode != 0:
        return {"valid": False, "reason": "pdfinfo_failed"}
    pages = None
    pdf_title = ""
    for line in info.stdout.splitlines():
        if line.startswith("Pages:"):
            value = line.split(":", 1)[1].strip()
            pages = int(value) if value.isdigit() else None
        elif line.startswith("Title:"):
            pdf_title = line.split(":", 1)[1].strip()
    extracted = subprocess.run(
        ["pdftotext", "-f", "1", "-l", "3", "-layout", str(path), "-"],
        capture_output=True,
        timeout=timeout,
        check=False,
    ).stdout.decode("utf-8", errors="replace")
    text = SPACE_PATTERN.sub(" ", extracted).strip()
    found_dois = sorted({normalize_doi(x) for x in DOI_PATTERN.findall(text)})
    expected_norm = normalize(expected_title)
    document_norm = normalize(pdf_title + " " + text[:20000])
    exact_title = bool(expected_norm and expected_norm in document_norm)
    title_ratio = SequenceMatcher(None, expected_norm, normalize(pdf_title)).ratio() if pdf_title else 0.0
    words = [normalize(x) for x in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", expected_title)]
    words = [x for x in words if len(x) >= 4]
    token_coverage = sum(x in document_norm for x in set(words)) / max(1, len(set(words)))
    doi_match = bool(expected_doi and expected_doi in found_dois)
    title_match = exact_title or title_ratio >= 0.82 or token_coverage >= 0.72
    valid = bool(pages and pages > 0 and (doi_match or title_match))
    return {
        "valid": valid,
        "reason": "identity_verified" if valid else "identity_not_verified",
        "page_count": pages,
        "text_length_first_three_pages": len(text),
        "detected_dois_first_three_pages": found_dois,
        "doi_match": doi_match,
        "title_exact": exact_title,
        "title_ratio": round(title_ratio, 4),
        "title_token_coverage": round(token_coverage, 4),
    }


def safe_name(value: str, maximum: int = 92) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", value).strip("_")
    return value[:maximum] or "publication"


def write_report(path: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="下载并核验公开可访问的论文 PDF")
    parser.add_argument("--missing-records", type=Path, required=True)
    parser.add_argument("--prior-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--delay", type=float, default=0.35)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    pdf_dir = args.output / "PDF"
    pdf_dir.mkdir(exist_ok=True)
    report_path = args.output / "download-report.json"
    missing = json.loads(args.missing_records.read_text(encoding="utf-8"))["records"]
    prior = json.loads(args.prior_manifest.read_text(encoding="utf-8"))["records"]
    prior_by_row = {int(row["representative_row"]): row for row in prior}
    report: dict[str, Any] = {
        "schema_version": "smartlib-open-fulltext-download-v1",
        "started_at": datetime.now(UTC).isoformat(),
        "input_count": len(missing),
        "records": [],
    }
    successful_identity: dict[str, dict[str, Any]] = {}

    for position, record in enumerate(missing, start=1):
        row_number = int(record["source_row_number"])
        normalized = record.get("normalized_payload") or {}
        previous = prior_by_row.get(row_number, {})
        target = {
            "source_row_number": row_number,
            "awardee_name": record.get("awardee_name_raw") or "",
            "title": normalized.get("title") or previous.get("title") or "",
            "year": normalized.get("year") or previous.get("year"),
            "doi": normalize_doi(normalized.get("doi") or previous.get("doi")),
            "pmid": str(normalized.get("pmid") or previous.get("pmid") or ""),
            "pmcid": str(normalized.get("pmcid") or previous.get("pmcid") or ""),
        }
        identity_key = target["doi"] or f"title:{normalize(target['title'])}"
        result: dict[str, Any] = {**target, "status": "not_found", "attempts": [], "metadata": {}}
        if identity_key in successful_identity:
            source = successful_identity[identity_key]
            result.update(
                {
                    "status": "downloaded_reused",
                    "pdf_path": source["pdf_path"],
                    "pdf_sha256": source["pdf_sha256"],
                    "validation": source["validation"],
                    "source_url": source["source_url"],
                    "source_provider": source["source_provider"],
                }
            )
            report["records"].append(result)
            write_report(report_path, report)
            print(f"[{position}/{len(missing)}] row {row_number}: downloaded_reused", flush=True)
            continue

        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in previous.get("oa_candidates") or []:
            add_candidate(
                candidates,
                seen,
                candidate.get("url"),
                str(candidate.get("platform") or "prior OA candidate"),
                int(candidate.get("priority") or 15),
            )
        providers = (
            ("europe_pmc", lambda: europe_pmc_candidates(target, args.timeout)),
            ("openalex", lambda: openalex_candidates(target["doi"], args.timeout)),
            ("crossref", lambda: crossref_candidates(target["doi"], args.timeout)),
            ("semantic_scholar", lambda: semantic_scholar_candidates(target["doi"], args.timeout)),
        )
        for provider, loader in providers:
            try:
                values, metadata = loader()
                result["metadata"][provider] = metadata
                for value in values:
                    add_candidate(
                        candidates,
                        seen,
                        value.get("url"),
                        str(value.get("provider") or provider),
                        int(value.get("priority") or 50),
                    )
            except Exception as exc:
                result["attempts"].append(
                    {"stage": "metadata", "provider": provider, "status": "failed", "error": str(exc)[:500]}
                )
            time.sleep(args.delay)
        candidates.sort(key=lambda value: (int(value["priority"]), candidate_key(value)))
        result["candidate_count"] = len(candidates)

        for attempt_number, candidate in enumerate(candidates, start=1):
            url = candidate["url"]
            attempt = {
                "stage": "download",
                "provider": candidate["provider"],
                "url": url,
                "status": "failed",
            }
            part = args.output / f".row-{row_number}-{attempt_number}.part"
            try:
                data, content_type, final_url = request(
                    url, accept="application/pdf,application/octet-stream;q=0.9,*/*;q=0.1", timeout=args.timeout
                )
                attempt.update(
                    {"http_content_type": content_type, "final_url": final_url, "bytes": len(data)}
                )
                if len(data) > 367001600:
                    raise ValueError("file_exceeds_350_mib")
                if not data.startswith(b"%PDF-"):
                    raise ValueError("response_is_not_pdf")
                part.write_bytes(data)
                validation = inspect_pdf(part, target["doi"], target["title"], args.timeout)
                attempt["validation"] = validation
                if not validation["valid"]:
                    raise ValueError(str(validation["reason"]))
                digest = hashlib.sha256(data).hexdigest()
                filename = (
                    f"row-{row_number:03d}_{safe_name(target['awardee_name'], 20)}_"
                    f"{safe_name(target['title'])}_{digest[:12]}.pdf"
                )
                destination = pdf_dir / filename
                if destination.exists():
                    part.unlink(missing_ok=True)
                else:
                    shutil.move(part, destination)
                attempt["status"] = "success"
                result.update(
                    {
                        "status": "downloaded",
                        "pdf_path": str(destination),
                        "pdf_sha256": digest,
                        "validation": validation,
                        "source_url": final_url,
                        "source_provider": candidate["provider"],
                    }
                )
                successful_identity[identity_key] = result
                result["attempts"].append(attempt)
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError, subprocess.SubprocessError) as exc:
                attempt["error"] = str(exc)[:500]
                result["attempts"].append(attempt)
                part.unlink(missing_ok=True)
            time.sleep(args.delay)

        report["records"].append(result)
        write_report(report_path, report)
        print(
            f"[{position}/{len(missing)}] row {row_number}: {result['status']} "
            f"({result.get('candidate_count', 0)} candidates)",
            flush=True,
        )

    counts: dict[str, int] = {}
    for row in report["records"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    report["counts"] = counts
    report["unique_pdf_count"] = len(
        {row.get("pdf_sha256") for row in report["records"] if row.get("pdf_sha256")}
    )
    write_report(report_path, report)
    print(json.dumps({"counts": counts, "unique_pdf_count": report["unique_pdf_count"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
