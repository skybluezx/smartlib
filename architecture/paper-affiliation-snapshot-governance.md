# 论文署名机构快照数据模型

## 权威边界

学者的人事机构归属与论文署名机构是两类事实。本模型只表达论文发表时由全文 PDF
呈现的作者—affiliation 快照。ROR、ORCID、OpenAlex 和机构官网可以辅助规范化机构身份，
但不能替代论文全文证明某名作者在某篇论文中使用了该 affiliation。

当前已升级到 V39；迁移及接口说明见 [通用导入与领域来源扩展](generic-ingestion-and-domain-provenance.md)。

## 最终模型

```text
knowledge_object(person/publication/organization)
        │
publication_authorship（论文中的作者席位与原始 affiliation）
        │
evidence_record[evidence_kind=author_affiliation]
        │  PDF资源、页码、marker、原文、坐标、审核状态
        ▼
relation_assertion[person.affiliated_with]
        │  context_object_id=publication
        ├── publication_relation_provenance
        │      publication_authorship_id=作者席位
        └── relation_evidence ──> 已确认的 PDF 证据
```

无法确认的步骤不创建候选关系，而是写入通用 `review_task`。审核任务可以指向证据、
关系、知识对象或论文作者席位，并保留候选对象、机器建议、原因、置信度和最终决定。

## 强制约束

- 已审核的 `person.affiliated_with` 必须连接有效的 person 与 organization。
- 每条关系必须携带论文上下文和该论文的作者席位，且作者、论文必须一致。
- 每条关系必须链接同一篇论文的、状态为 confirmed 的全文 affiliation 证据。
- confirmed 证据必须有 PDF 资源、原文和页码。
- 同一学者在同一机构发表多篇论文时保留多条论文快照，不跨论文聚合为一条事实。
- `publication_authorship.affiliation_organization_ids` 旧缓存列已在 V39 删除；机构映射通过来源扩展和正式关系查询。

## 历史数据迁移

V29 将现存 `affiliation_raw` 按论文作者席位转为 `author_affiliation` 证据。由于历史字段
没有可靠的 PDF 页码和坐标，这些证据统一标为 `needs_review`，并逐条创建
`PDF_AFFILIATION_RECHECK_REQUIRED` 审核任务。迁移不自动创建机构对象，也不自动批准
学者—机构关系。
