"""OCR the first pages of image-only archive PDFs and match controlled targets."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from discover_archive_fulltexts import (
    DOI_PATTERN,
    load_targets,
    non_fulltext_reason,
    normalize,
    normalize_doi,
)


def ocr_sample(path: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="smartlib-discovery-ocr-") as directory:
        prefix = Path(directory) / "page"
        try:
            subprocess.run(
                ["pdftoppm", "-f", "1", "-l", "3", "-jpeg", "-r", "150", str(path), str(prefix)],
                check=True, capture_output=True, timeout=180,
            )
            texts = []
            for image in sorted(Path(directory).glob("page-*.jpg")):
                result = subprocess.run(
                    ["tesseract", str(image), "stdout", "-l", "eng+chi_sim"],
                    check=True, capture_output=True, timeout=120,
                )
                texts.append(result.stdout.decode("utf-8", errors="replace"))
            text = "\n".join(texts)
            return {"path": str(path), "state": "ocr_sampled", "text": text[:50000],
                    "ocr_page_count": len(texts)}
        except Exception as exc:
            return {"path": str(path), "state": "ocr_failed", "error": str(exc), "text": "",
                    "ocr_page_count": 0}


def match(sample: dict[str, object], targets: list[dict[str, object]]) -> list[dict[str, object]]:
    path = str(sample["path"])
    if non_fulltext_reason(path):
        return []
    text = str(sample["text"])
    compact = normalize(text)
    dois = {normalize_doi(value) for value in DOI_PATTERN.findall(text)}
    results = []
    for target in targets:
        title = str(target["title_normalized"])
        reasons = []
        if target.get("doi") and target["doi"] in dois:
            reasons.append("doi_exact_ocr")
        if len(title) >= 18 and title in compact:
            reasons.append("title_exact_ocr")
        fragments = [title[index:index + 12] for index in range(0, max(1, len(title) - 11), 12)]
        coverage = sum(fragment in compact for fragment in fragments) / max(1, len(fragments))
        author_hits = sum(
            1 for author in target.get("authors_normalized", [])
            if len(str(author)) >= 5 and str(author) in compact
        )
        if coverage >= 0.7 and author_hits:
            reasons.append(f"title_fragment_ocr:{coverage:.3f}")
            reasons.append(f"author_hits:{author_hits}")
        if reasons:
            results.append({
                "source_row_number": target["source_row_number"], "awardee_name": target["awardee_name"],
                "target_title": target["title"], "target_doi": target.get("doi"),
                "archive_path": path, "match_reasons": reasons,
            })
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--paths", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    targets = load_targets(args.targets)
    relative_paths = json.loads(args.paths.read_text(encoding="utf-8"))
    paths = [args.archive / value for value in relative_paths]
    samples = []
    candidates = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(ocr_sample, path) for path in paths]
        for number, future in enumerate(as_completed(futures), start=1):
            sample = future.result()
            candidates.extend(match(sample, targets))
            samples.append({key: value for key, value in sample.items() if key != "text"})
            if number % 20 == 0:
                print(f"ocr sampled {number}/{len(paths)}", flush=True)
    payload = {
        "scanned": len(paths), "succeeded": sum(row["state"] == "ocr_sampled" for row in samples),
        "failed": sum(row["state"] == "ocr_failed" for row in samples),
        "candidate_count": len(candidates), "candidates": candidates, "files": samples,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("scanned", "succeeded", "failed", "candidate_count")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
