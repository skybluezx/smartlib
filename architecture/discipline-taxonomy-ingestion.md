# 权威学科分类对象导入

> 历史批次记录：2026-09-09只读核验发现，当前本地数据库已无有效学科对象。
> 下述计数不代表清库后的现状；新一轮推进见 `research-classification-v1.md`。

## 当前正式数据集

数据集标识为 `authoritative-discipline-taxonomies`，版本为 `2026-09-04-v1`。

| 分类体系 | 正式学科对象 | 质量处理 |
| --- | ---: | --- |
| 教育部研究生教育学科专业目录（2022，含2025调整） | 255 | 正式启用 |
| 教育部原目录对应项 | 70 | 仅用于历史名称和代码映射 |
| 国家自然科学基金申请代码（2026） | 1,426 | 正式启用；OCR修正记录保留告警 |
| GB/T 13745-2009 | 800 | 仅启用带正式编码的一、二级记录 |

GB/T 三级词项 2,306 条没有进入正式对象。解析数量与来源声明口径尚未完全对齐，继续保留在预览区等待复核。

## 存储与关系

- PostgreSQL：保存分类体系、学科对象、来源引用、证据、质量状态和审计记录。
- MinIO：在 `smartlib-reference-data` 桶中保存 41 份下载的官方原始文件，并启用版本控制。
- OpenSearch：投影公开学科对象，支持统一检索。
- HugeGraph：投影学科节点以及 `taxonomy.contains`、`taxonomy.broader`、`taxonomy.replaces` 关系。

学者、论文、机构和项目以后通过 `relation_assertion` 与这些学科对象建立关系，无需复制分类名称到各业务表。

## 可重复执行

导入包由 `prepare_discipline_taxonomy_import.py` 生成。正式写入由 Compose 中的
`controlled-discipline-taxonomy-import` 管理任务执行。对象、来源和关系均使用稳定 UUID；重复执行会复用 MinIO 文件和现有对象，并重新完成数量对账。
