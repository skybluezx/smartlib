from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
PMID_PATTERN = re.compile(r"\bPMID\s*[:\uFF1A]?\s*(\d{6,9})\b", re.I)
PMCID_PATTERN = re.compile(r"\bPMC\s*(\d{5,10})\b", re.I)
SECTION_NAMES = {
    "abstract", "introduction", "background", "methods", "materials and methods",
    "results", "discussion", "conclusion", "conclusions", "references",
    "acknowledgements", "acknowledgments", "funding", "data availability",
}


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    metadata: dict[str, object]
    method: str
    page_count: int
    ocr_page_count: int


def _run(command: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"全文处理命令失败: {command[0]}") from exc


def _page_count(path: Path) -> int:
    output = _run(["pdfinfo", str(path)]).stdout
    match = re.search(r"^Pages:\s+(\d+)$", output, re.M)
    if not match:
        raise RuntimeError("无法读取 PDF 页数")
    return int(match.group(1))


def _extract_embedded_text(path: Path) -> str:
    with tempfile.NamedTemporaryFile(suffix=".txt") as output:
        _run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), output.name])
        return Path(output.name).read_text(encoding="utf-8", errors="replace")


def _ocr(path: Path, page_count: int) -> str:
    if shutil.which("tesseract") is None or shutil.which("pdftoppm") is None:
        raise RuntimeError("PDF 没有可用文本层; 当前运行环境未安装 OCR 组件")
    languages = _run(["tesseract", "--list-langs"]).stdout.splitlines()
    language = "eng+chi_sim" if "chi_sim" in languages else "eng"
    with tempfile.TemporaryDirectory(prefix="smartlib-ocr-") as directory:
        prefix = Path(directory) / "page"
        _run(["pdftoppm", "-jpeg", "-r", "200", str(path), str(prefix)], timeout=1800)
        texts: list[str] = []
        images = sorted(Path(directory).glob("page-*.jpg"))
        if len(images) != page_count:
            raise RuntimeError("OCR 渲染页数与 PDF 页数不一致")
        for image in images:
            result = _run(["tesseract", str(image), "stdout", "-l", language], timeout=300)
            texts.append(result.stdout)
        return "\n\f\n".join(texts)


def _section(text: str, start: str, stops: set[str], max_chars: int) -> str | None:
    lines = text.splitlines()
    start_index: int | None = None
    collected: list[str] = []
    for index, line in enumerate(lines):
        normalized = re.sub(r"[^a-z ]", "", line.strip().lower())
        if start_index is None and normalized == start:
            start_index = index + 1
            continue
        if start_index is not None:
            if normalized in stops:
                break
            collected.append(line.strip())
            if sum(len(item) for item in collected) >= max_chars:
                break
    value = re.sub(r"\s+", " ", " ".join(collected)).strip()
    return value[:max_chars] or None


def _block(text: str, start: str, stop: str, max_chars: int) -> str | None:
    match = re.search(start + r"\s*(.*?)\s*(?=" + stop + r")", text, re.I | re.S)
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" :-|\n\t")
    return value[:max_chars] or None


def structure_text(text: str, page_count: int, method: str, ocr_page_count: int) -> dict[str, object]:
    clean = text.replace("\x00", "")
    dois = sorted({match.group(0).rstrip(".,;)") for match in DOI_PATTERN.finditer(clean)})
    pmids = sorted({match.group(1) for match in PMID_PATTERN.finditer(clean)})
    pmcids = sorted({"PMC" + match.group(1) for match in PMCID_PATTERN.finditer(clean)})
    headings: list[str] = []
    for line in clean.splitlines():
        candidate = re.sub(r"^\s*\d+(?:\.\d+)*\s*[.)|]?\s*", "", line).strip().lower()
        for heading in SECTION_NAMES:
            if (candidate == heading or candidate.startswith(heading + " ")) and heading not in headings:
                headings.append(heading)
    abstract = _block(
        clean, r"\babstract\b", r"\bkey\s*words?\b|(?:\b1\s*[|.]?\s*)?\bintroduction\b", 8000
    ) or _section(clean, "abstract", SECTION_NAMES - {"abstract"}, 8000)
    keywords_match = re.search(
        r"(?is)\bkey\s*words?\b\s*[:\uFF1A]?\s*(.{3,1000}?)(?=(?:\b1\s*[|.]?\s*)?\bintroduction\b)",
        clean,
    )
    keywords = []
    if keywords_match:
        keyword_line = re.sub(r"\s+", " ", keywords_match.group(1))
        keywords = [item.strip(" .") for item in re.split(r"[;,·•]", keyword_line) if item.strip()]
    funding = _block(
        clean, r"\bfunding(?: information)?\b",
        r"\bconflict(?:s)? of interest\b|\bdata availability\b|\breferences\b", 5000,
    ) or _section(clean, "funding", SECTION_NAMES - {"funding"}, 5000)
    acknowledgements = _section(clean, "acknowledgements", SECTION_NAMES - {"acknowledgements"}, 5000)
    if acknowledgements is None:
        acknowledgements = _section(clean, "acknowledgments", SECTION_NAMES - {"acknowledgments"}, 5000)
    reference_count = len(re.findall(r"(?m)^\s*(?:\[\d+\]|\d+[.)])\s+", clean))
    return {
        "schema_version": "publication-fulltext-extraction-v1",
        "method": method,
        "page_count": page_count,
        "ocr_page_count": ocr_page_count,
        "text_length": len(clean),
        "detected_dois": dois[:100],
        "detected_pmids": pmids[:100],
        "detected_pmcids": pmcids[:100],
        "section_headings": headings,
        "abstract": abstract,
        "keywords": keywords[:100],
        "funding_text": funding,
        "acknowledgements": acknowledgements,
        "reference_marker_count": reference_count,
        "text_preview": re.sub(r"\s+", " ", clean).strip()[:4000],
    }


def extract_pdf(path: Path, minimum_chars_per_page: int = 80) -> ExtractionResult:
    page_count = _page_count(path)
    text = _extract_embedded_text(path)
    method = "embedded_text"
    ocr_page_count = 0
    visible_chars = len(re.sub(r"\s+", "", text))
    if visible_chars < page_count * minimum_chars_per_page:
        text = _ocr(path, page_count)
        method = "ocr"
        ocr_page_count = page_count
    metadata = structure_text(text, page_count, method, ocr_page_count)
    return ExtractionResult(text=text, metadata=metadata, method=method,
                            page_count=page_count, ocr_page_count=ocr_page_count)
