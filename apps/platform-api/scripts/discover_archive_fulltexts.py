"""Read-only discovery of publication full texts in a large archive.

The script indexes the first pages of every PDF, then matches them against a
controlled JSONL target set. It never modifies the source archive or database.
"""

# ruff: noqa: I001, RUF001

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from smartlib_platform.fulltext.extraction import extract_pdf


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
PMID_PATTERN = re.compile(r"\bPMID\s*[:：]?\s*(\d{6,9})\b", re.I)
YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
SPACE_PATTERN = re.compile(r"\s+")
NON_WORD_PATTERN = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


def normalize(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return NON_WORD_PATTERN.sub("", value)


def normalize_doi(value: object) -> str:
    return str(value or "").strip().casefold().removeprefix("https://doi.org/").rstrip(".,;)")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_text(command: list[str], timeout: int) -> str:
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return result.stdout.decode("utf-8", errors="replace")


def inspect_pdf(path: Path, timeout: int) -> dict[str, object]:
    stat = path.stat()
    info = run_text(["pdfinfo", str(path)], timeout)
    text = run_text(["pdftotext", "-f", "1", "-l", "3", "-layout", str(path), "-"], timeout)
    metadata: dict[str, str] = {}
    for line in info.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().casefold()] = value.strip()
    compact_text = SPACE_PATTERN.sub(" ", text).strip()
    dois = sorted({normalize_doi(item) for item in DOI_PATTERN.findall(compact_text)})
    pmids = sorted(set(PMID_PATTERN.findall(compact_text)))
    years = sorted(set(YEAR_PATTERN.findall(compact_text)))
    return {
        "path": str(path),
        "file_name": path.name,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        "pdf_title": metadata.get("title", ""),
        "pdf_author": metadata.get("author", ""),
        "page_count": int(metadata.get("pages", "0")) if metadata.get("pages", "").isdigit() else None,
        "sample_text": compact_text[:16000],
        "sample_text_length": len(compact_text),
        "dois": dois,
        "pmids": pmids,
        "years": years,
        "parse_state": "text" if len(compact_text) >= 80 else "image_or_unreadable",
    }


def open_index(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS archive_pdf (
            path TEXT PRIMARY KEY, file_name TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            modified_at TEXT NOT NULL, pdf_title TEXT, pdf_author TEXT, page_count INTEGER,
            sample_text TEXT, sample_text_length INTEGER NOT NULL, dois TEXT NOT NULL,
            pmids TEXT NOT NULL, years TEXT NOT NULL, parse_state TEXT NOT NULL,
            checksum TEXT
        )"""
    )
    return connection


def index_archive(root: Path, connection: sqlite3.Connection, workers: int, timeout: int) -> dict[str, int]:
    paths = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() == ".pdf")
    existing = {
        row[0]: (row[1], row[2])
        for row in connection.execute("SELECT path,size_bytes,modified_at FROM archive_pdf")
    }
    pending = []
    for path in paths:
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
        if existing.get(str(path)) != (stat.st_size, modified):
            pending.append(path)
    processed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(inspect_pdf, path, timeout): path for path in pending}
        for future in as_completed(futures):
            path = futures[future]
            try:
                item = future.result()
            except Exception as exc:  # keep the scan resumable on individual corrupt files
                stat = path.stat()
                item = {
                    "path": str(path), "file_name": path.name, "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                    "pdf_title": "", "pdf_author": "", "page_count": None, "sample_text": "",
                    "sample_text_length": 0, "dois": [], "pmids": [], "years": [],
                    "parse_state": f"error:{type(exc).__name__}",
                }
            connection.execute(
                """INSERT INTO archive_pdf
                   (path,file_name,size_bytes,modified_at,pdf_title,pdf_author,page_count,sample_text,
                    sample_text_length,dois,pmids,years,parse_state)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET file_name=excluded.file_name,
                    size_bytes=excluded.size_bytes,modified_at=excluded.modified_at,
                    pdf_title=excluded.pdf_title,pdf_author=excluded.pdf_author,
                    page_count=excluded.page_count,sample_text=excluded.sample_text,
                    sample_text_length=excluded.sample_text_length,dois=excluded.dois,
                    pmids=excluded.pmids,years=excluded.years,parse_state=excluded.parse_state,
                    checksum=NULL""",
                (
                    item["path"], item["file_name"], item["size_bytes"], item["modified_at"],
                    item["pdf_title"], item["pdf_author"], item["page_count"], item["sample_text"],
                    item["sample_text_length"], json.dumps(item["dois"]), json.dumps(item["pmids"]),
                    json.dumps(item["years"]), item["parse_state"],
                ),
            )
            processed += 1
            if processed % 100 == 0:
                connection.commit()
                print(f"indexed {processed}/{len(pending)}", flush=True)
    connection.commit()
    return {"discovered": len(paths), "indexed_now": processed, "cached": len(paths) - processed}


def load_targets(path: Path) -> list[dict[str, object]]:
    targets = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            target = json.loads(line)
            target["doi"] = normalize_doi(target.get("doi"))
            target["title_normalized"] = normalize(target.get("title"))
            target["authors_normalized"] = [normalize(value) for value in target.get("authors", [])]
            targets.append(target)
    return targets


def similarity(target: dict[str, object], document: dict[str, object]) -> tuple[float, list[str]]:
    title = str(target["title_normalized"])
    file_name = normalize(Path(str(document["file_name"])).stem)
    pdf_title = normalize(document["pdf_title"])
    sample = normalize(str(document["sample_text"])[:12000])
    dois = set(json.loads(str(document["dois"])))
    pmids = set(json.loads(str(document["pmids"])))
    reasons: list[str] = []
    score = 0.0
    file_stem = Path(str(document["file_name"])).stem.strip()
    if target.get("sci_serial") and file_stem == str(target["sci_serial"]).strip():
        score = 0.96
        reasons.append("sci_serial_exact")
    target_doi = str(target.get("doi") or "")
    target_pmid = str(target.get("pmid") or "")
    if target_doi and dois and target_doi not in dois:
        return 0.0, ["primary_doi_conflict"]
    if target_pmid and pmids and target_pmid not in pmids:
        return 0.0, ["primary_pmid_conflict"]
    if target_doi and target_doi in dois:
        score = 1.0
        reasons.append("doi_exact")
    if target_pmid and target_pmid in pmids:
        score = max(score, 0.99)
        reasons.append("pmid_exact")
    if title and len(title) >= 18 and title in sample:
        score = max(score, 0.97)
        reasons.append("title_exact_in_text")
    fuzzy = max(
        SequenceMatcher(None, title, file_name).ratio() if file_name else 0.0,
        SequenceMatcher(None, title, pdf_title).ratio() if pdf_title else 0.0,
    )
    if fuzzy >= 0.72:
        score = max(score, fuzzy)
        reasons.append(f"title_fuzzy:{fuzzy:.3f}")
    if title and sample:
        chunks = {title[index:index + 12] for index in range(0, max(1, len(title) - 11), 12)}
        coverage = sum(chunk in sample for chunk in chunks) / max(1, len(chunks))
        if coverage >= 0.7:
            score = max(score, 0.84 + min(0.1, coverage / 10))
            reasons.append(f"title_fragment_coverage:{coverage:.3f}")
    year = str(target.get("year") or "")
    if year and year in json.loads(str(document["years"])):
        reasons.append("year_present")
    author_hits = sum(
        1 for author in target.get("authors_normalized", [])
        if len(str(author)) >= 5 and str(author) in sample
    )
    if author_hits:
        reasons.append(f"author_hits:{author_hits}")
    return round(score, 4), reasons


def non_fulltext_reason(path: str) -> str | None:
    name = Path(path).stem.casefold()
    blocked = {
        "检索证明": "bibliographic_report", "收录证明": "bibliographic_report",
        "查新报告": "search_report", "查新合同": "contract", "培训": "training_material",
        "通知": "notice", "使用方法": "instruction", "说明书": "instruction",
    }
    for marker, reason in blocked.items():
        if marker in name:
            return reason
    return None


def match_targets(
    connection: sqlite3.Connection,
    targets: list[dict[str, object]],
) -> list[dict[str, object]]:
    cursor = connection.execute(
        "SELECT path,file_name,size_bytes,modified_at,pdf_title,pdf_author,page_count,sample_text,"
        "sample_text_length,dois,pmids,years,parse_state,checksum FROM archive_pdf"
    )
    columns = [item[0] for item in cursor.description]
    documents = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    candidates: list[dict[str, object]] = []
    doi_targets = {target["doi"]: target for target in targets if target.get("doi")}
    pmid_targets = {str(target["pmid"]): target for target in targets if target.get("pmid")}
    target_terms = {}
    serial_targets = {
        str(target["sci_serial"]).strip(): target for target in targets if target.get("sci_serial")
    }
    for target in targets:
        words = {
            normalize(word)
            for word in re.findall(
                r"[A-Za-z0-9\u4e00-\u9fff]+",
                str(target.get("title") or ""),
            )
            if len(normalize(word)) >= 4
        }
        target_terms[int(target["source_row_number"])] = words
    for number, document in enumerate(documents, start=1):
        if non_fulltext_reason(str(document["path"])):
            continue
        shortlist: dict[int, dict[str, object]] = {}
        stem = Path(str(document["file_name"])).stem.strip()
        if stem in serial_targets:
            target = serial_targets[stem]
            shortlist[int(target["source_row_number"])] = target
        for doi in json.loads(str(document["dois"])):
            if doi in doi_targets:
                shortlist[int(doi_targets[doi]["source_row_number"])] = doi_targets[doi]
        for pmid in json.loads(str(document["pmids"])):
            if pmid in pmid_targets:
                shortlist[int(pmid_targets[pmid]["source_row_number"])] = pmid_targets[pmid]
        sample_norm = normalize(str(document["sample_text"])[:12000])
        name_words = {
            normalize(word) for word in re.findall(
                r"[A-Za-z0-9\u4e00-\u9fff]+",
                f"{Path(str(document['file_name'])).stem} {document['pdf_title']}",
            ) if len(normalize(word)) >= 4
        }
        for target in targets:
            title = str(target["title_normalized"])
            terms = target_terms[int(target["source_row_number"])]
            overlap = len(terms & name_words)
            if title and (title in sample_norm or (len(title) >= 24 and title[:24] in sample_norm)
                          or overlap >= min(3, max(1, len(terms) // 2))):
                shortlist[int(target["source_row_number"])] = target
        for target in shortlist.values():
            score, reasons = similarity(target, document)
            if score < 0.72:
                continue
            candidates.append({
                "source_row_number": target["source_row_number"],
                "publication_id": target.get("publication_id"),
                "verification_state": target.get("verification_state"),
                "awardee_name": target.get("awardee_name"), "target_title": target.get("title"),
                "target_doi": target.get("doi"), "target_pmid": target.get("pmid"),
                "target_year": target.get("year"), "archive_path": document["path"],
                "file_name": document["file_name"], "size_bytes": document["size_bytes"],
                "page_count": document["page_count"], "parse_state": document["parse_state"],
                "pdf_title": document["pdf_title"],
                "first_pages_dois": json.loads(str(document["dois"])),
                "first_pages_pmids": json.loads(str(document["pmids"])),
                "match_score": score, "match_reasons": reasons,
                "existing_checksums": target.get("existing_checksums", []),
            })
        if number % 1000 == 0:
            print(f"matched {number}/{len(documents)}", flush=True)
    candidates.sort(key=lambda item: (int(item["source_row_number"]), -float(item["match_score"])))
    return candidates


def classify(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    by_row: dict[int, list[dict[str, object]]] = {}
    for item in candidates:
        by_row.setdefault(int(item["source_row_number"]), []).append(item)
    final = []
    for items in by_row.values():
        best = items[0]
        competing = [
            item
            for item in items[1:]
            if float(item["match_score"]) >= float(best["match_score"]) - 0.02
        ]
        reasons = set(best["match_reasons"])
        if "doi_exact" in reasons or "pmid_exact" in reasons or "title_exact_in_text" in reasons:
            confidence = "confirmed" if not competing else "confirmed_duplicates"
        elif float(best["match_score"]) >= 0.9:
            confidence = "probable" if not competing else "ambiguous"
        else:
            confidence = "possible"
        checksum = sha256_file(Path(str(best["archive_path"])))
        best = {**best, "confidence": confidence, "sha256": checksum,
                "already_in_system": checksum in set(best.pop("existing_checksums", [])),
                "alternative_count": len(items) - 1,
                "alternative_paths": [item["archive_path"] for item in items[1:6]]}
        final.append(best)
    return sorted(final, key=lambda item: int(item["source_row_number"]))


def full_parse(matches: list[dict[str, object]], workers: int) -> None:
    def parse(item: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
        try:
            result = extract_pdf(Path(str(item["archive_path"])))
            return item, {
                "state": "parsed", "method": result.method, "page_count": result.page_count,
                "text_length": len(result.text), "ocr_page_count": result.ocr_page_count,
                "detected_dois": result.metadata.get("detected_dois", []),
                "detected_pmids": result.metadata.get("detected_pmids", []),
                "detected_pmcids": result.metadata.get("detected_pmcids", []),
                "section_headings": result.metadata.get("section_headings", []),
                "abstract_present": bool(result.metadata.get("abstract")),
                "keywords": result.metadata.get("keywords", []),
                "funding_text_present": bool(result.metadata.get("funding_text")),
            }
        except Exception as exc:
            return item, {"state": "needs_ocr_or_manual_parse", "error": str(exc)}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as executor:
        futures = [executor.submit(parse, item) for item in matches]
        for number, future in enumerate(as_completed(futures), start=1):
            item, parsed = future.result()
            item["fulltext_extraction"] = parsed
            if number % 20 == 0:
                print(f"full parsed {number}/{len(matches)}", flush=True)


def write_outputs(output: Path, scan: dict[str, int], connection: sqlite3.Connection,
                  targets: list[dict[str, object]], candidates: list[dict[str, object]],
                  matches: list[dict[str, object]]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    states = dict(connection.execute("SELECT parse_state,count(*) FROM archive_pdf GROUP BY parse_state"))
    confidence: dict[str, int] = {}
    for item in matches:
        confidence[str(item["confidence"])] = confidence.get(str(item["confidence"]), 0) + 1
    report = {
        "schema_version": "smartlib-archive-fulltext-discovery-v1",
        "generated_at": datetime.now(UTC).isoformat(), "scan": scan,
        "target_count": len(targets), "parse_states": states,
        "candidate_pair_count": len(candidates), "matched_target_count": len(matches),
        "confidence_counts": confidence,
        "ready_for_formal_publication": sum(bool(item.get("publication_id")) for item in matches),
        "identity_not_ready": sum(not item.get("publication_id") for item in matches),
        "new_fulltexts": sum(not item.get("already_in_system") for item in matches),
        "already_in_system": sum(bool(item.get("already_in_system")) for item in matches),
        "fully_parsed": sum(item.get("fulltext_extraction", {}).get("state") == "parsed" for item in matches),
        "needs_ocr_or_manual_parse": sum(
            item.get("fulltext_extraction", {}).get("state") != "parsed" for item in matches
        ),
    }
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "matches.json").write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    if matches:
        with (output / "matches.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            fields = [key for key in matches[0] if key != "alternative_paths"]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for item in matches:
                writer.writerow(
                    {
                        key: json.dumps(value, ensure_ascii=False)
                        if isinstance(value, list)
                        else value
                        for key, value in item.items()
                        if key != "alternative_paths"
                    }
                )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="扫描备份盘并发现当前批次论文全文")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    connection = open_index(args.output / "archive-index.sqlite3")
    scan = index_archive(args.archive, connection, args.workers, args.timeout)
    targets = load_targets(args.targets)
    candidates = match_targets(connection, targets)
    matches = classify(candidates)
    full_parse(matches, args.workers)
    write_outputs(args.output, scan, connection, targets, candidates, matches)


if __name__ == "__main__":
    main()
