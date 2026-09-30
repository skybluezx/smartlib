import argparse
import json
import re
import time
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote

import httpx

CROSSREF_BASE = "https://api.crossref.org"
NCBI_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
USER_AGENT = "SmartLibKnowledgePlatform/0.1 (controlled local publication verification)"


def normalized_comparison_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


def similarity(left: object, right: object) -> float:
    normalized_left = normalized_comparison_text(left)
    normalized_right = normalized_comparison_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return round(SequenceMatcher(None, normalized_left, normalized_right).ratio(), 4)


def crossref_year(candidate: dict[str, object]) -> int | None:
    for field in ("published-print", "published-online", "published", "issued"):
        date_parts = candidate.get(field, {}).get("date-parts", []) if candidate.get(field) else []
        if date_parts and date_parts[0] and date_parts[0][0] is not None:
            return int(date_parts[0][0])
    return None


def first_value(candidate: dict[str, object], field: str) -> str:
    value = candidate.get(field)
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def compact_crossref(candidate: dict[str, object]) -> dict[str, object]:
    authors = []
    for author in candidate.get("author", []) or []:
        authors.append(
            {
                "given": author.get("given"),
                "family": author.get("family"),
                "orcid": str(author.get("ORCID", "")).removeprefix("https://orcid.org/") or None,
                "sequence": author.get("sequence"),
                "affiliations": [entry.get("name") for entry in author.get("affiliation", [])],
            }
        )
    return {
        "doi": str(candidate.get("DOI", "")).lower() or None,
        "title": first_value(candidate, "title") or None,
        "journal_name": first_value(candidate, "container-title") or None,
        "publication_year": crossref_year(candidate),
        "publication_type": candidate.get("type"),
        "volume": candidate.get("volume"),
        "issue": candidate.get("issue"),
        "pages": candidate.get("page"),
        "article_number": candidate.get("article-number"),
        "authors": authors,
        "publisher": candidate.get("publisher"),
        "url": candidate.get("URL"),
    }


def compact_ncbi(candidate: dict[str, object]) -> dict[str, object]:
    article_ids = {entry.get("idtype"): entry.get("value") for entry in candidate.get("articleids", [])}
    year_match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", str(candidate.get("pubdate", "")))
    return {
        "schema_version": 2,
        "pmid": str(candidate.get("uid", "")) or None,
        "doi": str(article_ids.get("doi", "")).lower() or None,
        "pmcid": article_ids.get("pmc"),
        "title": candidate.get("title"),
        "journal_name": candidate.get("fulljournalname") or candidate.get("source"),
        "publication_year": int(year_match.group(1)) if year_match else None,
        "authors": [entry.get("name") for entry in candidate.get("authors", []) if entry.get("name")],
        "last_author": candidate.get("lastauthor") or None,
    }


def classify(
    source: dict[str, object], candidate: dict[str, object] | None, method: str
) -> dict[str, object]:
    if candidate is None:
        return {
            "classification": "not_found",
            "title_score": None,
            "journal_score": None,
            "year_distance": None,
        }
    title_score = similarity(source.get("title"), candidate.get("title"))
    journal_score = similarity(source.get("journal_or_conference"), candidate.get("journal_name"))
    source_year = source.get("publication_year")
    candidate_year = candidate.get("publication_year")
    year_distance = abs(int(source_year) - int(candidate_year)) if source_year and candidate_year else None
    if method == "exact_doi" and title_score >= 0.97 and year_distance is not None and year_distance <= 1:
        if (
            not source.get("journal_or_conference")
            or not candidate.get("journal_name")
            or journal_score >= 0.75
        ):
            classification = "auto_verified"
        else:
            classification = "candidate_review"
    elif method == "exact_doi" and (title_score < 0.85 or (year_distance is not None and year_distance > 1)):
        classification = "conflict"
    else:
        classification = "candidate_review"
    return {
        "classification": classification,
        "title_score": title_score,
        "journal_score": journal_score,
        "year_distance": year_distance,
    }


def request_json(
    client: httpx.Client, url: str, params: dict[str, object] | None = None
) -> dict[str, object] | None:
    for attempt in range(4):
        response = client.get(url, params=params)
        if response.status_code == 404:
            return None
        if response.status_code in {429, 500, 502, 503, 504}:
            time.sleep(1.5 * (attempt + 1))
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"verification source remained unavailable: {url}")


def load_ncbi(client: httpx.Client, pmids: list[str], cache_path: Path) -> dict[str, dict[str, object]]:
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        cache = {}
    missing = [pmid for pmid in pmids if cache.get(pmid, {}).get("schema_version") != 2]
    for start in range(0, len(missing), 100):
        batch = missing[start : start + 100]
        payload = request_json(
            client,
            NCBI_SUMMARY_URL,
            {"db": "pubmed", "id": ",".join(batch), "retmode": "json", "tool": "smartlib_verifier"},
        )
        result = payload.get("result", {}) if payload else {}
        for pmid in batch:
            cache[pmid] = compact_ncbi(result[pmid]) if pmid in result else {"not_found": True}
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(0.4)
    return cache


def collect(package: dict[str, object], output_path: Path, cache_dir: Path) -> dict[str, object]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    crossref_cache_path = cache_dir / "crossref.json"
    crossref_cache = (
        json.loads(crossref_cache_path.read_text(encoding="utf-8")) if crossref_cache_path.exists() else {}
    )
    pmids = sorted(
        {
            item["normalized_payload"]["pmid"]
            for item in package["items"]
            if item["normalized_payload"].get("pmid")
        }
    )
    records = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True) as client:
        ncbi_cache = load_ncbi(client, pmids, cache_dir / "ncbi_pubmed.json")
        for position, item in enumerate(package["items"], start=1):
            source = item["normalized_payload"]
            doi = source.get("doi")
            method = "exact_doi" if doi else "title_search"
            cache_key = f"doi:{doi}" if doi else f"title:{item['source_serial']}"
            if cache_key not in crossref_cache:
                if doi:
                    payload = request_json(client, f"{CROSSREF_BASE}/works/{quote(doi, safe='')}")
                    candidate = compact_crossref(payload["message"]) if payload else None
                    candidates = [candidate] if candidate else []
                else:
                    payload = request_json(
                        client,
                        f"{CROSSREF_BASE}/works",
                        {
                            "query.title": source["title"],
                            "query.container-title": source.get("journal_or_conference") or "",
                            "rows": 3,
                        },
                    )
                    candidates = [compact_crossref(value) for value in payload["message"]["items"]]
                crossref_cache[cache_key] = candidates
                crossref_cache_path.write_text(
                    json.dumps(crossref_cache, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                time.sleep(0.12)
            candidates = crossref_cache[cache_key]
            ranked = sorted(
                ((classify(source, candidate, method), candidate) for candidate in candidates),
                key=lambda pair: (pair[0]["title_score"] or 0, pair[0]["journal_score"] or 0),
                reverse=True,
            )
            scores, candidate = ranked[0] if ranked else (classify(source, None, method), None)
            pmid = source.get("pmid")
            ncbi = ncbi_cache.get(pmid) if pmid else None
            if (
                ncbi
                and not ncbi.get("not_found")
                and candidate
                and scores["classification"] == "auto_verified"
            ):
                ncbi_title_score = similarity(source["title"], ncbi.get("title"))
                ncbi_doi_matches = not ncbi.get("doi") or ncbi.get("doi") == candidate.get("doi")
                if ncbi_title_score < 0.95 or not ncbi_doi_matches:
                    scores["classification"] = "conflict"
                scores["ncbi_title_score"] = ncbi_title_score
                scores["ncbi_doi_matches"] = ncbi_doi_matches
            records.append(
                {
                    "record_id": item["record_id"],
                    "source_serial": item["source_serial"],
                    "source_excel_row": item["source_excel_row"],
                    "method": method,
                    "classification": scores.pop("classification"),
                    "scores": scores,
                    "crossref": candidate,
                    "ncbi_pubmed": ncbi,
                }
            )
            if position % 25 == 0 or position == len(package["items"]):
                print(f"verified {position}/{len(package['items'])}", flush=True)

    counts = {}
    for record in records:
        counts[record["classification"]] = counts.get(record["classification"], 0) + 1
    result = {
        "manifest": {
            "dataset_version": package["manifest"]["dataset_version"],
            "verification_run_id": "publication-auto-verification-v1",
            "rule_version": "crossref-ncbi-conservative-v1",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "record_count": len(records),
            "classification_counts": counts,
            "crossref_endpoint": CROSSREF_BASE,
            "ncbi_endpoint": NCBI_SUMMARY_URL,
        },
        "records": records,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect Crossref and NCBI publication verification evidence"
    )
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    package = json.loads(args.package.read_text(encoding="utf-8"))
    result = collect(package, args.output, args.cache_dir)
    print(json.dumps(result["manifest"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
