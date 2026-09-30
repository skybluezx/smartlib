#!/usr/bin/env python3
"""Build a review-only list of explicit project/funding statements.

The input must be produced by ``extract_publication_funding_review.py``.  This
script does not write to PostgreSQL or a graph projection.  It keeps every
project/grant candidate tied to the original funding paragraph and avoids
inventing pairings when one paragraph names several funders and identifiers.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
HTML_TAG = re.compile(r"<[^>]+>")
PROJECT_PHRASE = re.compile(
    r"(?:\b(?:the\s+)?[A-Z][A-Za-z0-9&'’()\-/ ]{2,100}?"
    r"(?:Program(?:me)?|Project|Fund(?:ing)?|Foundation|Grant|Award|Scheme|Initiative)\b|"
    r"[\u4e00-\u9fffA-Za-z0-9“”'’()（）·&\-/ ]{2,60}?"
    r"(?:计划|项目|基金|专项|课题|工程))",
    re.I,
)
NOISE = re.compile(
    r"(?:\breferences?\b|\bbibliography\b|doi\.org|\bvol\.?\s*\d|"
    r"\bjournal\b|\bfigure\b|\btable\b|参考文献)",
    re.I,
)


def clean(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = HTML_TAG.sub("", text)
    text = text.replace("\u00ad", "").replace("‐", "-").replace("–", "-").replace("—", "-")
    # Repair line-wrap hyphenation in PDF text without altering grant IDs.
    text = re.sub(r"(?<=[A-Za-z])\-\s+(?=[a-z])", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_semicolon(value: object) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in re.split(r"[;；]", clean(value)) if part.strip()))


def project_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    for match in PROJECT_PHRASE.finditer(text):
        phrase = clean(match.group(0)).strip(" ,.;:：[]")
        phrase = re.sub(
            r"^(?:This|The) (?:study|work|research) (?:was |is )?"
            r"(?:financially )?(?:supported|funded)(?: with grants)? (?:by|from) (?:the )?",
            "",
            phrase,
            flags=re.I,
        )
        phrase = re.sub(r"^(?:supported|funded) by (?:the )?", "", phrase, flags=re.I)
        if 4 <= len(phrase) <= 130 and not re.search(r"\b(?:article|method|author contribution)\b", phrase, re.I):
            phrases.append(phrase)
    return list(dict.fromkeys(phrases))


def nearest_named_source(evidence: str, grant_id: str) -> str:
    """Return the closest explicitly named source/program before an identifier."""
    if not grant_id:
        return ""
    position = evidence.find(grant_id)
    if position < 0:
        return ""
    prefix = evidence[:position]
    open_paren = max(prefix.rfind("("), prefix.rfind("["))
    close_paren = max(prefix.rfind(")"), prefix.rfind("]"))
    boundary_end = open_paren if open_paren > close_paren else position
    before = evidence[:boundary_end]
    boundaries = [match.end() for match in re.finditer(r"[,;；。]|\band\b|\bby\b|\bfrom\b", before, re.I)]
    start = boundaries[-1] if boundaries else max(0, len(before) - 180)
    fragment = clean(before[start:]).strip(" ,.;:：[]()")
    fragment = re.sub(
        r"^(?:the\s+)?(?:grant|award|project)(?:\s+(?:num-?ber|number|no\.?|nos\.?))?\s*$",
        "",
        fragment,
        flags=re.I,
    )
    fragment = re.sub(r"^(?:the\s+)", "", fragment, flags=re.I)
    if not (4 <= len(fragment) <= 150):
        return ""
    if re.fullmatch(r"[A-Z0-9._/\- ]+", fragment, re.I) and not re.search(
        r"(?:foundation|fund|program|project|council|commission|ministry|department|university|laboratory|计划|项目|基金|专项|课题)",
        fragment,
        re.I,
    ):
        return ""
    return fragment


def related_years(evidence: str, grant_id: str) -> str:
    result: list[str] = []
    if grant_id:
        for year in YEAR.findall(grant_id):
            result.append(f"{year}（编号内）")
        position = evidence.find(grant_id)
        if position >= 0:
            for year in YEAR.findall(evidence[max(0, position - 50) : position + len(grant_id) + 50]):
                result.append(f"{year}（编号附近原文）")
    for match in re.finditer(r"(?:年度|year|from|during|in)\s*[:：]?\s*((?:19|20)\d{2})", evidence, re.I):
        result.append(f"{match.group(1)}（原文明示）")
    return "; ".join(dict.fromkeys(result))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(input_path: Path, output_root: Path) -> dict[str, Any]:
    package = json.loads(input_path.read_text(encoding="utf-8"))
    metadata = package["metadata"]
    if metadata.get("scope_unique_publications") != 271 or metadata.get("unique_fulltexts_read") != 271:
        raise ValueError("input must contain a successful 271/271 full-text scan")

    output_root.mkdir(parents=True, exist_ok=True)
    evidence_by_id = {item["evidence_id"]: item for item in package["evidence"]}
    publications: dict[str, dict[str, Any]] = {}
    for item in package["publications"]:
        publications.setdefault(item["唯一论文ID"], item)

    rows: list[dict[str, Any]] = []
    for record in package["funding_records"]:
        evidence = evidence_by_id[record["evidence_id"]]
        paragraph = clean(evidence.get("funding_clause_focus") or evidence.get("evidence_text"))
        normalized_sources = split_semicolon(record.get("funder_name_normalized"))
        raw_sources = split_semicolon(record.get("funder_name_raw"))
        names = project_phrases(paragraph)
        sources = normalized_sources or raw_sources
        grants = split_semicolon(record.get("grant_id_raw"))
        # One row per explicit identifier.  A named programme without an
        # identifier still receives one row so it is not silently discarded.
        row_grants = grants or [""]
        for grant_id in row_grants:
            nearby_name = nearest_named_source(paragraph, grant_id)
            ambiguous = not nearby_name and len(sources) > 1 and len(grants) > 1
            noise = (
                bool(record.get("possible_reference"))
                or bool(NOISE.search(paragraph))
                or evidence.get("extraction_method") == "bounded_two_column_region"
            )
            if grant_id and nearby_name and not noise:
                review_state = "明确编号及邻近项目或资助来源"
                confidence = "高" if evidence.get("confidence") == "high" else "中"
            elif grant_id:
                review_state = "明确编号，资助来源对应关系待核"
                confidence = "中" if not noise else "低"
            else:
                review_state = "明确资助项目或计划名称，未提供编号"
                confidence = "中" if sources or names else "低"
            rows.append(
                {
                    "项目或资助计划名称（编号邻近文本，待核）": nearby_name,
                    "段落内项目或计划名称候选": "; ".join(names),
                    "资助来源规范名": "; ".join(normalized_sources),
                    "资助来源原文": "; ".join(raw_sources),
                    "项目编号": grant_id,
                    "项目相关日期或年份": related_years(paragraph, grant_id),
                    "提取判断": review_state,
                    "建议置信度": confidence,
                    "原文可能混入双栏或参考文献": "是" if noise else "否",
                    "论文题名": clean(record.get("title")),
                    "期刊": publications.get(record["publication_id"], {}).get("期刊", ""),
                    "论文发表年份": publications.get(record["publication_id"], {}).get("发表年份", ""),
                    "DOI": publications.get(record["publication_id"], {}).get("DOI", ""),
                    "代表性论著编号": record.get("representative_work_numbers", ""),
                    "论文ID": record["publication_id"],
                    "原文页码": evidence.get("page_number", ""),
                    "出版物页码": evidence.get("publisher_page_number", ""),
                    "原文章节": evidence.get("section_label", ""),
                    "原文段落": paragraph,
                    "证据ID": record["evidence_id"],
                    "人工审核结论": "",
                    "人工修订项目名称": "",
                    "人工修订项目编号": "",
                    "备注": "",
                }
            )

    # De-duplicate exact project evidence rows without collapsing the same
    # grant cited by different papers.
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (row["论文ID"], row["证据ID"], row["项目编号"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    status_rows: list[dict[str, Any]] = []
    for publication_id, item in publications.items():
        status_rows.append(
            {
                "论文ID": publication_id,
                "代表性论著编号": item.get("代表性论著编号", ""),
                "论文题名": clean(item.get("论文题名")),
                "期刊": item.get("期刊", ""),
                "发表年份": item.get("发表年份", ""),
                "DOI": item.get("DOI", ""),
                "扫描状态": item.get("提取状态", ""),
                "资助方数量": item.get("资助方数量", 0),
                "基金编号数量": item.get("基金编号数量", 0),
                "证据条数": item.get("证据条数", 0),
                "全文页数": item.get("全文页数", ""),
                "全文字符数": item.get("全文字符数", ""),
                "读取异常": item.get("读取异常", ""),
            }
        )

    unresolved_rows: list[dict[str, Any]] = []
    for row in status_rows:
        if row["扫描状态"] != "有基金表述但未识别项目":
            continue
        related = [
            clean(item.get("funding_clause_focus") or item.get("evidence_text"))
            for item in package["evidence"]
            if item["publication_id"] == row["论文ID"]
        ]
        unresolved_rows.append({**row, "待核原文段落": " || ".join(related)})

    primary_rows = [row for row in deduped if row["建议置信度"] in {"高", "中"}]
    low_confidence_rows = [row for row in deduped if row["建议置信度"] == "低"]
    project_columns = list(deduped[0]) if deduped else []
    status_columns = list(status_rows[0]) if status_rows else []
    unresolved_columns = list(unresolved_rows[0]) if unresolved_rows else status_columns + ["待核原文段落"]
    write_csv(output_root / "01_明确项目与资助计划清单_待审核.csv", primary_rows, project_columns)
    write_csv(output_root / "02_全部论文逐篇扫描状态_271篇.csv", status_rows, status_columns)
    write_csv(output_root / "03_有资助表述但未识别项目_待核.csv", unresolved_rows, unresolved_columns)
    write_csv(output_root / "04_可能受双栏或参考文献干扰_低置信.csv", low_confidence_rows, project_columns)

    status_counts = Counter(row["扫描状态"] for row in status_rows)
    confidence_counts = Counter(row["建议置信度"] for row in deduped)
    summary = {
        "source_scan_generated_at": metadata.get("generated_at"),
        "method_version": "explicit-project-review-v1",
        "database_write": False,
        "graph_write": False,
        "unique_publications_scanned": len(status_rows),
        "fulltexts_read": metadata.get("unique_fulltexts_read"),
        "publication_status_counts": dict(status_counts),
        "review_rows": len(deduped),
        "primary_review_rows": len(primary_rows),
        "low_confidence_rows": len(low_confidence_rows),
        "rows_with_grant_id": sum(bool(row["项目编号"]) for row in deduped),
        "rows_without_grant_id": sum(not row["项目编号"] for row in deduped),
        "distinct_grant_ids": len({row["项目编号"] for row in deduped if row["项目编号"]}),
        "confidence_counts": dict(confidence_counts),
        "rows_flagged_possible_layout_or_reference_noise": sum(
            row["原文可能混入双栏或参考文献"] == "是" for row in deduped
        ),
        "unresolved_explicit_funding_publications": len(unresolved_rows),
    }
    (output_root / "00_结果摘要.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = f"""# 全部论文全文明确项目提取说明

- 扫描范围：{len(status_rows)} 篇唯一论文，全文成功读取 {metadata.get('unique_fulltexts_read')} 篇。
- 主审清单：{len(primary_rows)} 行；另有 {len(low_confidence_rows)} 行可能受双栏排版或参考文献干扰，单独列出。
- 全部候选：{len(deduped)} 行，其中带项目编号 {summary['rows_with_grant_id']} 行，不带编号 {summary['rows_without_grant_id']} 行。
- 不同项目编号：{summary['distinct_grant_ids']} 个。
- 仍需查看原文才能拆分项目：{len(unresolved_rows)} 篇。
- 本轮没有回写数据库、OpenSearch 或 HugeGraph。

## 阅读口径

每一行都绑定论文、证据页码、章节和原文段落。一个段落同时列出多个资助来源和多个编号时，不擅自将编号逐一配给某个来源，而是标记为“对应关系待核”。“项目相关日期或年份”区分编号内年份、编号附近原文和原文明示年份，不能在人工审核前视为正式项目起止日期。
"""
    (output_root / "检查说明.md").write_text(report, encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
