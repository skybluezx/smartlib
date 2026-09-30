"""Synthetic ledgers based only on source schemas, never copying source row values."""

import csv
import io
import json
import zipfile
from pathlib import Path
from smartlib_platform.library_work.parser import CATALOG, parse_upload

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "outputs/library-work-20260930"
OUT.mkdir(parents=True, exist_ok=True)
TOPICS = {
    "staff_learning": ["数据治理实务学习", "读者沟通案例研讨", "资源许可知识学习"],
    "lectures": ["医学与人文阅读", "数字时代的信息素养", "科学写作与阅读"],
    "conferences": ["高校图书馆服务交流", "学科服务专题培训", "馆藏建设工作研讨"],
    "analysis_reports": ["学科服务需求分析", "电子资源使用分析", "阅读服务年度回顾"],
    "party_affairs": ["内部工作交流", "服务流程学习", "公益服务活动"],
    "textbooks": ["信息检索实践教材", "科研数据管理教程", "医学文献阅读基础"],
    "notices": ["数据库使用培训通知", "开放时间调整通知", "文献传递服务通知"],
    "papers": ["高校图书馆读者服务研究", "科研支持服务实践", "馆藏资源建设研究"],
    "book_recommendations": ["医学人文书单", "科研方法书单", "经典阅读书单"],
    "exhibitions": ["科学精神主题展", "阅读文化主题展", "优秀书目展示"],
    "media": ["阅读推广活动报道", "资源共享服务介绍", "数字服务建设纪实"],
    "conference_talks": ["学科服务实践报告", "元数据治理经验交流", "阅读推广案例报告"],
    "auditorium": ["专题学术讲座", "读者教育培训", "校园文化交流"],
    "union_events": ["职工文化交流", "健步活动", "阅读分享活动"],
    "database_changes": ["模拟医学文献数据库", "模拟综合检索数据库", "模拟学术期刊数据库"],
    "online_services": ["模拟文献传递入口", "模拟读者预约服务", "模拟学科咨询入口"],
    "novelty_reports": ["医学信息检索技术", "科研知识组织方法", "临床证据服务流程"],
    "local_databases": ["模拟校史专题库", "模拟医学人文资源库", "模拟学科案例库"],
    "awards": ["模拟服务创新奖", "模拟阅读推广奖", "模拟资源建设奖"],
    "projects": ["学科服务流程优化", "科研信息素养教育", "特色资源整理"],
    "database_trials": ["模拟医学试用资源", "模拟综合试用资源", "模拟学术试用资源"],
    "reader_training": ["医学文献检索入门", "文献管理工具使用", "学术规范与引用"],
    "reader_events": ["阅读分享会", "信息检索挑战赛", "新生入馆活动"],
    "surveys": ["读者服务需求调查", "馆藏资源使用调查", "空间服务满意度调查"],
    "administration": ["业务协调工作会议", "服务流程检查", "资源盘点工作"],
}
archive_path = OUT / "馆务模拟数据.zip"
with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
    for index, spec in enumerate(CATALOG):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=spec["fields"])
        writer.writeheader()
        for i in range(12):
            year, month = 2024 + i // 4, 1 + (i % 4) * 2
            day = 5 + index % 20
            person = f"模拟馆员{index % 8 + 1:02d}"
            dept = ["模拟读者服务部", "模拟科研支持部", "模拟资源建设部", "模拟综合业务部"][index % 4]
            title = f"【模拟】{TOPICS[spec['code']][i % 3]}（{year}年第{i % 4 + 1}期）"
            values = {key: "" for key in spec["fields"]}
            values.update(
                {
                    "序号": str(i + 1),
                    spec["title_field"]: title,
                    spec["date_field"]: f"{year}-{month:02d}-{day:02d}",
                }
            )
            if spec["date_field"] == "出版年":
                values[spec["date_field"]] = str(year)
            if spec["end_field"]:
                values[spec["end_field"]] = f"{year}-{month:02d}-{day + 1:02d}"
            if spec["department_field"]:
                values[spec["department_field"]] = dept
            if spec["audience_field"]:
                values[spec["audience_field"]] = str(18 + (i * 11 + index * 7) % 160)
            for key in spec["fields"]:
                if values[key]:
                    continue
                if key in (
                    "填表人",
                    "主讲人",
                    "报告人",
                    "报告完成人",
                    "报告完成人",
                    "撰稿人",
                    "记者或撰稿人",
                    "主持人",
                    "查新完成人",
                    "委托人",
                    "第一作者",
                    "主编",
                ):
                    values[key] = person
                elif key in ("参加人员", "参与人", "其他作者", "主要参与人", "参会人员"):
                    values[key] = person + "、模拟馆员09"
                elif key in ("备注", "备注（是否为科研项目成果）"):
                    values[key] = "独立生成的模拟记录；非真实业务，仅供功能验收。"
                elif key in ("主要内容", "内容", "活动内容"):
                    values[key] = "模拟开展业务交流与实践活动。"
                elif key in ("地点", "展览地点", "使用区域"):
                    values[key] = ["模拟培训室", "模拟阅览区", "模拟报告厅"][i % 3]
                elif key in ("用途", "申报用途"):
                    values[key] = "教学科研支持（模拟用途）"
                elif key in ("文种",):
                    values[key] = ["中文", "英文"][i % 2]
                elif key in ("来源",):
                    values[key] = "模拟数据来源"
                elif key in ("经费金额",):
                    values[key] = str(5000 + 1000 * i) + " 元（模拟）"
                elif key in ("册数", "发放份数"):
                    values[key] = str(50 + i * 5)
                elif key == "回收份数":
                    values[key] = str(42 + i * 5)
                elif key == "是否发布":
                    values[key] = ["是", "否"][i % 2]
                elif key in ("报告编号", "项目编号"):
                    values[key] = f"DEMO-{year}-{index:02d}-{i + 1:03d}"
                elif key == "活动类别":
                    values[key] = "阅读推广（模拟）"
                elif key == "活动形式":
                    values[key] = "线下交流（模拟）"
                elif key == "调查对象":
                    values[key] = "模拟读者群体"
                elif key in ("总结形式（报告）",):
                    values[key] = "模拟调查汇总报告"
                elif key == "推荐形式":
                    values[key] = "模拟主题书单"
            # A few documented gaps exercise missingness handling without inventing replacements.
            if i == 10 and index in (0, 1, 22):
                values[spec["date_field"]] = ""
            if i == 11 and spec["audience_field"]:
                values[spec["audience_field"]] = ""
            writer.writerow(values)
        archive.writestr(spec["name"] + ".csv", "\ufeff" + stream.getvalue())
result = parse_upload(archive_path.name, archive_path.read_bytes())
assert len(result["records"]) == 300 and not result["errors"], result["errors"]
(OUT / "demo-manifest.json").write_text(
    json.dumps(
        {
            "mode": "demo",
            "records": 300,
            "categories": result["categories"],
            "warning_records": result["warning_count"],
            "source": "Source schemas only; no real workbook rows copied",
            "years": [2024, 2025, 2026],
            "generator": "generate_library_work_demo.py",
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n"
)
print(
    json.dumps(
        {"file": str(archive_path), "records": len(result["records"]), "warnings": result["warning_count"]},
        ensure_ascii=False,
    )
)
