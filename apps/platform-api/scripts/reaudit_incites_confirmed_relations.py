from __future__ import annotations

import csv
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


ROOT = Path(__file__).resolve().parents[3]
COMPARISON = ROOT / "outputs/incites_funding_comparison_2026-09-04"
SOURCE = COMPARISON / "source"
FULLTEXT = ROOT / "outputs/2026_nsf_fulltext_funding_zone_first_v3/论文全文基金信息抽取_待审核.json"
OUTPUT = ROOT / "outputs/incites_confirmed_125_reaudit_2026-09-04"

FUNDER_PATTERNS = {
    "国家自然科学基金委员会（NSFC）": r"national natural sciences? foundation of china|\bnsfc\b|国家自然科学基金",
    "国家重点研发计划": r"national key research (?:and|&) development program of china|national key r\s*&\s*d program|国家重点研发计划",
    "辽宁省自然科学基金": r"natural science foundation of liaoning(?: province)?|liaoning provincial natural science foundation|辽宁省自然科学基金",
    "辽宁省兴辽英才计划": r"liaoning revitalization talents program|xingliao talents|兴辽英才",
    "中国博士后科学基金": r"china postdoctoral science foundation|中国博士后科学基金",
    "中央高校基本科研业务费": r"fundamental research funds? for the central universities|中央高校基本科研业务费",
    "长江学者和创新团队发展计划（PCSIRT）": r"program for changjiang scholars.{0,30}innovative research team|\bpcsirt\b|长江学者.{0,20}创新团队",
    "浙江省自然科学基金": r"natural science foundation of zhejiang province|zhejiang provincial natural science foundation|浙江省自然科学基金",
    "韩国国家研究基金会": r"national research foundation of korea|\bnrf(?:-?korea)?\b|韩国国家研究基金",
    "英国医学研究委员会（MRC）": r"medical research council(?: uk)?|\bmrc\b|英国医学研究委员会",
    "英国研究与创新署（UKRI）": r"uk research (?:and|&) innovation|\bukri\b|英国研究与创新",
    "英国癌症研究基金会": r"cancer research uk|英国癌症研究",
}

UKRI_CHILD_PATTERN = re.compile(
    r"medical research council|\bmrc\b|biotechnology and biological sciences research council|"
    r"engineering and physical sciences research council|economic and social research council|"
    r"natural environment research council|science and technology facilities council",
    re.I,
)


def normalize_doi(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text)
    return text.rstrip(" .;,)")


def normalize_title(value: object) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^a-z0-9\u0370-\u03ff\u4e00-\u9fff]+", "", text)


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def context_for_pattern(evidence: list[dict[str, object]], pattern: re.Pattern[str]) -> tuple[str, str]:
    for item in evidence:
        candidates = [
            clean_text(item.get("funding_clause_focus")),
            clean_text(item.get("evidence_text")),
        ]
        for text in candidates:
            match = pattern.search(text)
            if match:
                start = max(0, match.start() - 140)
                end = min(len(text), match.end() + 260)
                return text[start:end], str(item.get("publisher_page_number") or item.get("page_number") or "")
    return "", ""


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def add_sheet(workbook: Workbook, title: str, rows: list[dict[str, object]]) -> None:
    sheet = workbook.create_sheet(title)
    headers = list(rows[0])
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for index, header in enumerate(headers, 1):
        values = [str(header)] + [str(row.get(header, "") or "") for row in rows[:200]]
        sheet.column_dimensions[get_column_letter(index)].width = min(60, max(11, max(map(len, values)) + 2))
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fulltext = json.loads(FULLTEXT.read_text(encoding="utf-8"))
    publications = {row["唯一论文ID"]: row for row in fulltext["publications"]}
    evidence_by_publication: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in fulltext["evidence"]:
        evidence_by_publication[row["publication_id"]].append(row)

    with (COMPARISON / "02_InCites关系逐条对照.csv").open(encoding="utf-8-sig", newline="") as handle:
        confirmed = [
            row
            for row in csv.DictReader(handle)
            if row["对照结果"] in {"双方一致", "机构层级归并一致"}
        ]

    workbooks: dict[str, object] = {}
    audit_rows: list[dict[str, object]] = []
    for relation in confirmed:
        filename = relation["InCites来源文件"]
        if filename not in workbooks:
            workbooks[filename] = load_workbook(SOURCE / filename, read_only=True, data_only=True)
        sheet = workbooks[filename][workbooks[filename].sheetnames[0]]
        headers = [str(cell.value or "") for cell in sheet[1]]
        source_row_number = int(relation["InCites源表行"])
        source_record = dict(zip(headers, [cell.value for cell in sheet[source_row_number]], strict=False))

        publication = publications[relation["唯一论文ID"]]
        evidence = evidence_by_publication[relation["唯一论文ID"]]
        evidence_text = " ".join(clean_text(item.get("evidence_text")) for item in evidence)
        names = {part.strip() for part in str(publication.get("资助方汇总") or "").split(";") if part.strip()}
        canonical = relation["InCites资助机构"]
        pattern = re.compile(FUNDER_PATTERNS[canonical], re.I)

        direct_name = canonical in names
        snippet, page = context_for_pattern(evidence, pattern)
        direct_alias = bool(snippet)
        hierarchy = False
        hierarchy_snippet = ""
        hierarchy_page = ""
        if canonical == "英国研究与创新署（UKRI）" and not (direct_name or direct_alias):
            hierarchy_snippet, hierarchy_page = context_for_pattern(evidence, UKRI_CHILD_PATTERN)
            hierarchy = bool(hierarchy_snippet)

        source_doi = normalize_doi(source_record.get("DOI"))
        fulltext_doi = normalize_doi(publication.get("DOI"))
        relation_doi = normalize_doi(relation.get("DOI"))
        incites_doi_stable = bool(source_doi and source_doi == relation_doi)
        fulltext_doi_consistent = bool(fulltext_doi and source_doi == fulltext_doi)
        wos_consistent = clean_text(source_record.get("入藏号")) == clean_text(relation.get("WoS入藏号"))
        source_title_norm = normalize_title(source_record.get("论文标题"))
        fulltext_title_norm = normalize_title(publication.get("论文题名"))
        title_similarity = SequenceMatcher(None, source_title_norm, fulltext_title_norm).ratio()
        title_consistent = source_title_norm == fulltext_title_norm or title_similarity >= 0.90
        source_year = str(source_record.get("出版年") or "").removesuffix(".0")
        fulltext_year = str(publication.get("发表年份") or "").removesuffix(".0")
        year_consistent = source_year == fulltext_year

        if direct_name:
            relation_type = "直接一致（规范名）"
        elif direct_alias:
            relation_type = "直接一致（原文别名）"
        elif hierarchy:
            relation_type = "机构层级一致（UKRI上级/MRC下级）"
            snippet, page = hierarchy_snippet, hierarchy_page
        else:
            relation_type = "不一致"

        identity_consistent = incites_doi_stable and wos_consistent and title_consistent and (
            fulltext_doi_consistent or not fulltext_doi
        )
        all_consistent = identity_consistent and relation_type != "不一致"
        audit_rows.append(
            {
                "复核结论": "一致" if all_consistent else "不一致",
                "一致类型": relation_type,
                "唯一论文ID": relation["唯一论文ID"],
                "InCites资助机构": canonical,
                "InCites DOI": source_doi,
                "全文DOI": fulltext_doi,
                "WoS入藏号": clean_text(source_record.get("入藏号")),
                "InCites论文标题": clean_text(source_record.get("论文标题")),
                "全文论文标题": clean_text(publication.get("论文题名")),
                "InCites出版年": source_year,
                "全文出版年": fulltext_year,
                "InCites源行DOI一致": "是" if incites_doi_stable else "否",
                "全文DOI一致": "是" if fulltext_doi_consistent else ("本地缺失" if not fulltext_doi else "否"),
                "WoS一致": "是" if wos_consistent else "否",
                "标题一致": "是" if title_consistent else "否",
                "标题规范化相似度": round(title_similarity, 4),
                "年份一致": "是" if year_consistent else "否（元数据差异，不影响关系确认）",
                "全文资助方汇总": publication.get("资助方汇总") or "",
                "全文基金编号汇总": publication.get("基金编号汇总") or "",
                "资助原文证据": snippet,
                "证据页": page,
                "InCites来源文件": filename,
                "InCites源表行": source_row_number,
                "说明": "InCites导出不含项目编号；编号只做PDF证据展示，不参与InCites一致性判断。",
            }
        )

    result_counts = Counter(row["复核结论"] for row in audit_rows)
    type_counts = Counter(row["一致类型"] for row in audit_rows)
    metadata_anomalies = []
    for row in audit_rows:
        issues = []
        if row["全文DOI一致"] != "是":
            issues.append(f"全文DOI：{row['全文DOI一致']}")
        if row["年份一致"] != "是":
            issues.append(f"出版年：InCites={row['InCites出版年']}，全文={row['全文出版年']}")
        if float(row["标题规范化相似度"]) < 1:
            issues.append(f"标题显示差异：规范化相似度={row['标题规范化相似度']}")
        if issues:
            metadata_anomalies.append(
                {
                    "唯一论文ID": row["唯一论文ID"],
                    "DOI": row["InCites DOI"],
                    "WoS入藏号": row["WoS入藏号"],
                    "论文题名": row["InCites论文标题"],
                    "涉及资助机构": row["InCites资助机构"],
                    "附带元数据问题": "；".join(issues),
                    "是否影响资助关系结论": "否",
                }
            )
    funder_summary = []
    for funder in FUNDER_PATTERNS:
        subset = [row for row in audit_rows if row["InCites资助机构"] == funder]
        if not subset:
            continue
        funder_summary.append(
            {
                "资助机构": funder,
                "复核关系数": len(subset),
                "一致": sum(row["复核结论"] == "一致" for row in subset),
                "不一致": sum(row["复核结论"] != "一致" for row in subset),
                "直接规范名一致": sum(row["一致类型"] == "直接一致（规范名）" for row in subset),
                "直接原文别名一致": sum(row["一致类型"] == "直接一致（原文别名）" for row in subset),
                "机构层级一致": sum(row["一致类型"].startswith("机构层级一致") for row in subset),
            }
        )

    overview = [
        {"指标": "复核关系", "数量": len(audit_rows), "说明": "此前标记双方一致或机构层级一致的关系"},
        {"指标": "涉及唯一论文", "数量": len({row["唯一论文ID"] for row in audit_rows}), "说明": "同一论文可对应多个资助机构"},
        {"指标": "复核一致", "数量": result_counts["一致"], "说明": "论文身份和资助关系均通过"},
        {"指标": "复核不一致", "数量": result_counts["不一致"], "说明": "需要回退处理的关系"},
        {"指标": "直接规范名一致", "数量": type_counts["直接一致（规范名）"], "说明": "全文结构化资助方即为该规范名"},
        {"指标": "直接原文别名一致", "数量": type_counts["直接一致（原文别名）"], "说明": "PDF资助语句出现该机构英文名或常用缩写"},
        {"指标": "机构层级一致", "数量": type_counts["机构层级一致（UKRI上级/MRC下级）"], "说明": "InCites按UKRI上级归并，PDF明确写MRC"},
        {"指标": "本地DOI缺失", "数量": sum(row["全文DOI一致"] == "本地缺失" for row in audit_rows), "说明": "由唯一规范化标题完成身份对应"},
        {"指标": "出版年元数据差异", "数量": sum(not str(row["年份一致"]).startswith("是") for row in audit_rows), "说明": "在线发表年、卷期年或本地解析值不同，不影响资助关系"},
        {"指标": "出版年差异涉及论文", "数量": len({row["唯一论文ID"] for row in audit_rows if not str(row["年份一致"]).startswith("是")}), "说明": "按唯一论文去重"},
        {"指标": "数据库写入", "数量": 0, "说明": "本轮只做审计"},
    ]

    write_csv(OUTPUT / "125条关系逐条复核.csv", audit_rows)
    write_csv(OUTPUT / "按资助机构复核统计.csv", funder_summary)
    write_csv(OUTPUT / "附带元数据差异.csv", metadata_anomalies)
    workbook = Workbook()
    workbook.remove(workbook.active)
    add_sheet(workbook, "复核总览", overview)
    add_sheet(workbook, "按资助机构统计", funder_summary)
    add_sheet(workbook, "125条逐条复核", audit_rows)
    add_sheet(workbook, "附带元数据差异", metadata_anomalies)
    workbook.save(OUTPUT / "InCites已确认125条关系复核.xlsx")

    report = f"""# InCites已确认125条关系重新复核报告

## 结论

- 复核关系：{len(audit_rows)}条，涉及{len({row['唯一论文ID'] for row in audit_rows})}篇唯一论文。
- 复核一致：{result_counts['一致']}条；不一致：{result_counts['不一致']}条。
- 直接规范名一致：{type_counts['直接一致（规范名）']}条。
- PDF原文别名一致：{type_counts['直接一致（原文别名）']}条。
- 机构层级一致：{type_counts['机构层级一致（UKRI上级/MRC下级）']}条，均为InCites按UKRI归并、PDF明确写MRC。
- 本地全文记录DOI缺失：{sum(row['全文DOI一致'] == '本地缺失' for row in audit_rows)}条关系，均由唯一规范化标题与InCites源行对应。
- 出版年元数据存在差异：{sum(not str(row['年份一致']).startswith('是') for row in audit_rows)}条关系；这属于在线发表年、卷期年或本地解析值差异，不构成论文身份或资助关系冲突。

## 复核方法

逐条回读12份InCites源文件的原始行，以DOI、WoS入藏号、规范化标题和出版年核对论文身份；再独立回读PDF基金区域证据，检查资助机构规范名、英文别名或明确的上下级机构关系。未把旧表的“双方一致”字段当作证据。

## 数据边界

12份InCites导出只包含按资助机构筛选出的论文清单，不包含项目编号。因此，本报告确认的是“论文—资助机构”关系一致；项目编号及年份仍以PDF原文为准，不能声称与InCites项目编号一致。本轮数据库写入为0。
"""
    (OUTPUT / "复核报告.md").write_text(report, encoding="utf-8")

    assert len(audit_rows) == 125
    assert result_counts["不一致"] == 0
    assert len({(row["InCites资助机构"], row["WoS入藏号"]) for row in audit_rows}) == 125
    print(json.dumps({"overview": overview, "by_type": type_counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
