# 学者机构来源分类（V44）

规范机构仍用 knowledge_object，归属仍用 relation_assertion，依据仍用 relation_evidence / evidence_record / source_reference；不另建机构业务实体表。

## 当前落地

- person.authoritatively_affiliated_with：人事权威归属；允许同一学者多个机构、多个有效期记录。来源必须显式配置 personnel_authority=true 且授权有效，关联该学者的 confirmed business_record 证据。普通审核通过不构成人事权威。该关系不允许论文上下文。
- person.affiliated_with：保持既有论文快照语义、论文作者及同篇 PDF 证据约束；不改写成人事关系。
- 学者 API affiliations 返回逐条关系、分类、机构、成果上下文、原文、有效期和证据；不同论文快照不合并。
- 学者目录 department 兼容字段改为所有当前有效人事机构的展示文本；另有 authoritative_organizations、output_organizations 数组。人事与成果机构分别筛选，详情分别展示。
- 未接入人事数据时保留空值；论文年份不能填任职时间。时间未提供时显示来源未提供，不推断主职或兼职。

## 边界

本次不抽取、不导入机构，不连接真实人事系统，不改变人工确认的作者结果。未配置任何既有来源为人事权威。

专利、数据集等其他成果尚无经过核验的作者署名来源流程；目前成果机构正式写入仍限定论文，未来必须为相应成果补充来源/作者映射验证后扩展，不绕过论文约束。

人事来源配置和写入复用治理底层；尚未提供专门的人事同步管理页面或连接器。来源撤权时须在同一事务撤销对应正式关系，避免继续展示失去依据的权威信息。

## 验收

verify_scholar_affiliations.py 在回滚事务验证分类读取、有效期、证据变更保护；不保留测试对象。前后端另有学者服务与页面回归测试。
