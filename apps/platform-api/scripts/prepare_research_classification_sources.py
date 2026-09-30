#!/usr/bin/env python3
"""Read-only, evidence-preserving preparation; never writes business database rows."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import time
import unicodedata
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

NSFC_INDEX = "https://www.nsfc.gov.cn/p1/2931/3971/4002/gjzrkxjjsqdm2026.html"
MESH_URL = "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc2026.gz"
POLICY_VERSION = "research-classification-2026-09-v1"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch(url: str, path: Path) -> dict:
    """Keep immutable source bytes, URL and checksum together, including cache reuse."""
    receipt = path.with_suffix(path.suffix + ".source.json")
    if path.exists():
        prior = json.loads(receipt.read_text())
        if prior["url"] != url or prior["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f"Cached source mismatch: {path}")
        return prior
    request = urllib.request.Request(url, headers={"User-Agent": "SmartLib-Research-Classification/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.URLError:
        # macOS system curl can resolve trust chains absent from Homebrew Python.
        # Never disable TLS verification on either path.
        payload = subprocess.run(["/usr/bin/curl", "--fail", "--location", "--silent",
                                  "--show-error", "--max-time", "60", url],
                                 capture_output=True, check=True).stdout
        content_type = "application/octet-stream"
    if not payload:
        raise ValueError(f"Empty response: {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    result = {"url": url, "sha256": hashlib.sha256(payload).hexdigest(),
              "bytes": len(payload), "content_type": content_type,
              "retrieved_at": datetime.now(UTC).isoformat(), "path": str(path)}
    write_json(receipt, result)
    return result


def parse_mesh(path: Path) -> list[dict]:
    records = []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        for _, node in ET.iterparse(stream, events=("end",)):
            if node.tag != "DescriptorRecord":
                continue
            ui = node.findtext("DescriptorUI")
            name = node.findtext("DescriptorName/String")
            if not ui or not name:
                raise ValueError("Incomplete MeSH descriptor")
            records.append({"code": ui, "name": name,
                            "tree_numbers": [n.text for n in node.findall("TreeNumberList/TreeNumber")],
                            "aliases": sorted({n.text for n in node.findall("ConceptList/Concept/TermList/Term/String")
                                               if n.text and n.text != name}),
                            "scheme": "MESH", "version": "2026"})
            node.clear()
    if len({r["code"] for r in records}) != len(records):
        raise ValueError("Duplicate MeSH descriptor identifiers")
    if not records:
        raise ValueError("No MeSH descriptors")
    return records


def snapshot() -> list[dict]:
    query = """SELECT coalesce(jsonb_agg(to_jsonb(p)),'[]') FROM (
      SELECT m.publication_id::text,m.title,m.abstract,m.publication_year,m.attributes
      FROM smartlib.publication_metadata m JOIN smartlib.knowledge_object k
      ON k.object_id=m.publication_id WHERE k.system_to='infinity'
      AND k.review_state NOT IN ('rejected','superseded') ORDER BY m.publication_id) p;"""
    result = subprocess.run(["docker", "exec", "-i", "smartlib-postgres-1", "sh", "-c",
                             'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At'],
                            input=query, text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def pmid_of(paper: dict) -> str | None:
    value = paper["attributes"].get("incites", {}).get("raw_fields", {}).get("Pubmed ID")
    match = re.fullmatch(r"(?:MEDLINE:)?(\d+)", str(value or "").strip())
    return match.group(1) if match else None


def normalize_title(text: str) -> str:
    import html

    text = html.unescape(text)
    text = re.sub(r"<[^>]*>", "", text)
    return "".join(c for c in unicodedata.normalize("NFKD", text).casefold() if c.isalnum())


def parse_pubmed(path: Path) -> dict[str, dict]:
    root = ET.parse(path).getroot()
    if root.tag != "PubmedArticleSet":
        raise ValueError("Not a PubMed article response")
    result = {}
    for node in root.findall("PubmedArticle"):
        citation = node.find("MedlineCitation")
        if citation is None:
            continue
        title = citation.find("Article/ArticleTitle")
        headings = []
        for heading in citation.findall("MeshHeadingList/MeshHeading"):
            descriptor = heading.find("DescriptorName")
            if descriptor is None:
                continue
            headings.append({"code": descriptor.get("UI"), "name": descriptor.text,
                             "major_topic": descriptor.get("MajorTopicYN") == "Y",
                             "qualifiers": [{"code": q.get("UI"), "name": q.text,
                                             "major_topic": q.get("MajorTopicYN") == "Y"}
                                            for q in heading.findall("QualifierName")]})
        result[citation.findtext("PMID")] = {
            "title": "".join(title.itertext()) if title is not None else "",
            "abstract": "\n".join("".join(n.itertext()) for n in citation.findall("Article/Abstract/AbstractText")),
            "mesh": headings, "source_path": str(path)}
    return result


def review_record(paper: dict, pubmed: dict, terms: dict) -> dict:
    pmid = pmid_of(paper)
    record = pubmed.get(pmid)
    matched = bool(record and normalize_title(paper["title"]) == normalize_title(record["title"]))
    incites = paper["attributes"].get("incites", {})
    raw_direction = incites.get("raw_fields", {}).get("研究方向")
    headings = []
    if matched:
        for heading in record["mesh"]:
            term = terms.get(heading["code"])
            headings.append({**heading, "canonical_name_2026": term["name"] if term else None,
                             "vocabulary_match": "matched_ui" if term else "not_in_2026_descriptors",
                             "assignment_source": "PubMed/MEDLINE", "assignment_year": None,
                             "vocabulary_version": "2026", "review_state": "pending"})
    return {"publication_id": paper["publication_id"], "title": paper["title"],
            "publication_year": paper["publication_year"], "pmid": pmid,
            "source_match_state": "exact_normalized_title" if matched else
                ("title_mismatch" if record else "not_retrieved"),
            "pubmed_source": record["source_path"] if record else None,
            "retrieved_title": record["title"] if record else None,
            "retrieved_abstract": record["abstract"] if matched else None,
            "nsfc": {"scheme": "NSFC_APPLICATION_CODE", "version": "2026", "candidates": [],
                     "state": "awaiting_verified_codebook_and_content_classification"},
            "mesh": headings,
            "evaluation": {"raw_research_direction": raw_direction,
                           "classification_scheme": "unresolved_export_column_semantics",
                           "dataset": incites.get("dataset"), "export_date": incites.get("export_date"),
                           "note": "保留来源原值；不擅自认定为WoS类别、ESI学科或Citation Topics。"},
            "review_state": "pending", "database_write_state": "preview_only",
            "policy_version": POLICY_VERSION}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    papers = snapshot()
    write_json(output / "publication_snapshot.json", papers)
    sources = []
    failures = []
    mesh_path = output / "sources/desc2026.gz"
    sources.append(fetch(MESH_URL, mesh_path))
    descriptors = parse_mesh(mesh_path)
    write_json(output / "mesh_descriptors_2026.json", descriptors)
    index_path = output / "sources/nsfc/index.html"
    sources.append(fetch(NSFC_INDEX, index_path))
    # Archive all codebook pages and their content images. OCR output is not a standard term.
    index = index_path.read_text(encoding="utf-8")
    links = re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', index, re.S | re.I)
    pages = []
    for href, label in links:
        label = re.sub(r"<[^>]*>", "", label).strip()
        if re.match(r"^[A-HＴT][.．、\s]", label):
            url = urllib.parse.urljoin(NSFC_INDEX, href)
            if url not in pages:
                pages.append(url)
    for number, url in enumerate(pages, 1):
        page = output / f"sources/nsfc/department_{number}.html"
        try:
            sources.append(fetch(url, page))
            image_urls = re.findall(r'<img\b[^>]*src=["\']([^"\']+)', page.read_text(encoding="utf-8"), re.I)
            for index, image_url in enumerate(dict.fromkeys(image_urls), 1):
                full_url = urllib.parse.urljoin(url, image_url)
                suffix = Path(urllib.parse.urlsplit(full_url).path).suffix or ".bin"
                sources.append(fetch(full_url, output / f"sources/nsfc/d{number}_image{index}{suffix}"))
        except Exception as exc:
            failures.append({"url": url, "error": str(exc)})
    pmids = sorted({p for paper in papers if (p := pmid_of(paper))})
    pubmed = {}
    for start in range(0, len(pmids), 30):
        query = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(pmids[start:start + 30]),
                                      "retmode": "xml", "tool": "smartlib_classification"})
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + query
        path = output / f"sources/pubmed/batch_{start // 30 + 1}.xml"
        try:
            sources.append(fetch(url, path))
            pubmed.update(parse_pubmed(path))
        except Exception as exc:
            failures.append({"url": url, "error": str(exc)})
        time.sleep(0.4)
    terms = {r["code"]: r for r in descriptors}
    reviews = [review_record(p, pubmed, terms) for p in papers]
    write_json(output / "论文分类来源核验初稿.json", reviews)
    summary = {"policy_version": POLICY_VERSION, "generated_at": datetime.now(UTC).isoformat(),
               "database_write_state": "not_modified", "publications": len(papers),
               "incites_publications": sum(bool(p["attributes"].get("incites")) for p in papers),
               "pmids": len(pmids), "pubmed_retrieved": len(pubmed),
               "title_matched": sum(r["source_match_state"] == "exact_normalized_title" for r in reviews),
               "publications_with_mesh": sum(bool(r["mesh"]) for r in reviews),
               "mesh_assignments": sum(len(r["mesh"]) for r in reviews),
               "mesh_descriptors_2026": len(descriptors), "nsfc_pages": len(pages),
               "source_files": len(sources), "failures": failures}
    write_json(output / "source_manifest.json", sources)
    write_json(output / "summary.json", summary)
    lines = ["# 论文分类来源核验初稿", "",
             "本文件是来源准备结果，不是最终学科分类；未修改业务数据库。", "",
             f"论文 {len(papers)} 篇；取得 PubMed 记录 {len(pubmed)} 条；题名核对通过 {summary['title_matched']} 篇；"
             f"取得 MeSH 标引 {summary['mesh_assignments']} 条，覆盖 {summary['publications_with_mesh']} 篇。", "",
             "国自然申请代码尚待对官方图片结构化核验，本轮不猜填代码。MeSH保留PubMed标引原值、主要主题标志和限定词；"
             "词表版本2026不代表论文在2026年被标引。InCites研究方向保留原值，分类体系的确切含义待核对。", "",
             "| 论文 | 来源核对 | MeSH主题词 | InCites原始研究方向 |", "| --- | --- | --- | --- |"]
    for row in reviews:
        def cell(value):
            return str(value or "—").replace("|", "\\|").replace("\n", " ")
        label = cell(row["title"])
        if row["pmid"]:
            label = f"[{label}](https://pubmed.ncbi.nlm.nih.gov/{row['pmid']}/)"
        state = {"exact_normalized_title": "题名核对通过", "title_mismatch": "题名不完全一致，未采纳标引",
                 "not_retrieved": "本轮未取得来源"}[row["source_match_state"]]
        lines.append(f"| {label} | {state} | {cell('; '.join(h['name'] for h in row['mesh']))} | "
                     f"{cell(row['evaluation']['raw_research_direction'])} |")
    (output / "论文分类来源核验初稿.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
