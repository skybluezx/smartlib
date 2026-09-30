# 机构实体准入与目录过滤（2026-09-08）

## 不变原则

原始 affiliation 属于 evidence，不属于 organization。字符串匹配失败、名称清洗完成、PDF 抽取成功以及 reviewed_source_label 均不构成新机构准入依据。匹配既有机构不需要再创建一个对象；不明确的候选保留证据，等待独立实体判断。

## 新机构创建

1. 保存来源证据。在独立实体判断完成后，以 `organization_identity` 类型保存确认依据，`verification_state=confirmed`。这不是把 `author_affiliation` 改名，需单独记录实体判定依据。
2. 有 `change.decide` 权限的审核人调用 `smartlib.confirm_organization_entity(规范名称, 实体证据ID, 判定理由)`。函数返回决定编号，并记录审核人、时间、依据与理由。
3. 创建 organization 时将编号放入 `attributes.entity_decision_id`。数据库强制检查决定存在、名称一致、实体证据仍有效；一个决定只能用于一个机构对象。
4. 决定只追加，不可更新、删除或清空；决定的历史进入统一 entity_revision/change_event。审核人可通过 `read_organization_entity_decision` 追溯。

这是数据库治理入口，尚未新增专门的前端实体审核表单。通用创建 API 对没有决定编号的机构返回 422；伪造或不匹配的编号由数据库拒绝。旧批次 `import_reviewed_organizations.py` 已显式停用，不能直接重跑；未来批次必须先解析到既有对象或取得实体决定。

## 存量兼容

V48/V49 只增加规则、决定存储和属性契约，不给现有机构补造实体确认。存量对象可继续进行治理编辑；其历史决定编号不可替换。非机构对象转为机构同样经过准入校验。存量疑点仍须另行治理，不表示所有旧对象已经满足新准入标准。

## 目录

普通列表、分页总数、关联筛选、层级筛选、层级选项与祖先路径排除 rejected/superseded；层级及关联筛选也排除失效关系和失效端点。pending 未被一并隐藏。历史对象仍在数据库中，未删除，追溯读取入口未关闭。

## 本地验收

- V48/V49 已迁移；本地 API 已同步并重启，健康状态 ready。
- 目录专项测试：8 项通过。
- 实库回滚测试：未确认候选、伪造编号、错误证据、名称不符、重复编号、无权限均拒绝；明确确认可创建。
- 实库目录：247 条，完整分页读取，废止对象 0 条。
- 业务校验值修复前后相同：knowledge_object 2088 条，relation_assertion 8434 条，evidence_record 11280 条。
- 全量测试：135 通过，15 失败；失败涉及缺失的历史导入 JSON/Excel 等文件，不计为验收通过。
- 测试数据已回滚，实体决定表仍为空；未改动存量名称、机构归属、关系及证据。
- 本轮仅本地实施，未部署远端服务器；没有新增前端审核页面，也未进行浏览器视觉验收。

回归入口：`database/tests/verify_organization_admission.sql`（事务最终回滚）；`apps/platform-api/tests/test_knowledge_catalog.py`。
