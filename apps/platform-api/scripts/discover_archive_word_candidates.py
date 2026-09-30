"""Find Word manuscript candidates for a controlled publication target set."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from discover_archive_fulltexts import (
    DOI_PATTERN,
    PMID_PATTERN,
    load_targets,
    non_fulltext_reason,
    normalize,
    normalize_doi,
)


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        parts = []
        for name in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
            if name in archive.namelist():
                xml = archive.read(name).decode("utf-8", errors="replace")
                xml = re.sub(r"</w:(?:p|tr)>", "\n", xml)
                parts.append(re.sub(r"<[^>]+>", "", xml))
        return "\n".join(parts)


def doc_text(path: Path, timeout: int) -> str:
    try:
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True, check=False, timeout=timeout,
        )
        return result.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def extract(path: Path, timeout: int) -> dict[str, object]:
    try:
        text = docx_text(path) if path.suffix.casefold() == ".docx" else doc_text(path, timeout)
        state = "text" if len(re.sub(r"\s+", "", text)) >= 80 else "unreadable"
    except Exception as exc:
        text, state = "", f"error:{type(exc).__name__}"
    compact = re.sub(r"\s+", " ", text).strip()
    return {
        "path": str(path), "file_name": path.name, "size_bytes": path.stat().st_size,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        "sample_text": compact[:50000], "text_length": len(compact), "parse_state": state,
    }


def open_index(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS archive_word (
            path TEXT PRIMARY KEY,file_name TEXT NOT NULL,size_bytes INTEGER NOT NULL,
            modified_at TEXT NOT NULL,sample_text TEXT,text_length INTEGER NOT NULL,
            parse_state TEXT NOT NULL
        )"""
    )
    return connection


def index(root: Path, connection: sqlite3.Connection, workers: int, timeout: int) -> dict[str, int]:
    paths = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".doc", ".docx"}
    )
    existing = {row[0]: (row[1], row[2]) for row in connection.execute(
        "SELECT path,size_bytes,modified_at FROM archive_word"
    )}
    pending = []
    for path in paths:
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
        if existing.get(str(path)) != (stat.st_size, modified):
            pending.append(path)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(extract, path, timeout): path for path in pending}
        for number, future in enumerate(as_completed(futures), start=1):
            item = future.result()
            connection.execute(
                """INSERT INTO archive_word VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET file_name=excluded.file_name,
                   size_bytes=excluded.size_bytes,modified_at=excluded.modified_at,
                   sample_text=excluded.sample_text,text_length=excluded.text_length,
                   parse_state=excluded.parse_state""",
                tuple(item[key] for key in (
                    "path", "file_name", "size_bytes", "modified_at", "sample_text",
                    "text_length", "parse_state",
                )),
            )
            if number % 100 == 0:
                connection.commit()
                print(f"word indexed {number}/{len(pending)}", flush=True)
    connection.commit()
    return {"discovered": len(paths), "indexed_now": len(pending), "cached": len(paths) - len(pending)}


def match(connection: sqlite3.Connection, targets: list[dict[str, object]]) -> list[dict[str, object]]:
    results = []
    for document in connection.execute(
        "SELECT path,file_name,size_bytes,sample_text,text_length,parse_state FROM archive_word"
    ):
        path, file_name, size_bytes, text, text_length, parse_state = document
        if non_fulltext_reason(path) or parse_state != "text":
            continue
        normalized_text = normalize(text)
        normalized_name = normalize(Path(file_name).stem)
        dois = {normalize_doi(value) for value in DOI_PATTERN.findall(text)}
        pmids = set(PMID_PATTERN.findall(text))
        for target in targets:
            title = str(target["title_normalized"])
            reasons = []
            if target.get("doi") and target["doi"] in dois:
                reasons.append("doi_exact")
            if target.get("pmid") and str(target["pmid"]) in pmids:
                reasons.append("pmid_exact")
            if len(title) >= 18 and title in normalized_text:
                reasons.append("title_exact_in_text")
            if len(title) >= 24 and title[:24] in normalized_text:
                reasons.append("title_prefix_in_text")
            if (
                len(title) >= 18
                and (title in normalized_name or normalized_name in title)
                and len(normalized_name) >= 18
            ):
                reasons.append("title_in_file_name")
            if not reasons:
                continue
            results.append({
                "source_row_number": target["source_row_number"],
                "publication_id": target.get("publication_id"),
                "verification_state": target.get("verification_state"),
                "awardee_name": target.get("awardee_name"), "target_title": target.get("title"),
                "target_doi": target.get("doi"), "target_pmid": target.get("pmid"),
                "file_name": file_name, "archive_path": path, "size_bytes": size_bytes,
                "text_length": text_length, "match_reasons": reasons,
                "candidate_kind": "word_manuscript_or_supporting_material",
            })
    results.sort(key=lambda item: (int(item["source_row_number"]), str(item["archive_path"])))
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    connection = open_index(args.output / "archive-index.sqlite3")
    scan = index(args.archive, connection, args.workers, args.timeout)
    rows = match(connection, load_targets(args.targets))
    (args.output / "word-candidates.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if rows:
        with (args.output / "word-candidates.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        key: json.dumps(value, ensure_ascii=False)
                        if isinstance(value, list)
                        else value
                        for key, value in row.items()
                    }
                )
    print(json.dumps({"scan": scan, "candidate_count": len(rows),
                      "target_count": len({row['source_row_number'] for row in rows})},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
