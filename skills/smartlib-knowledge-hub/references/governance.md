# 质量检查和治理

```sh
hub-list --section rules
hub-list --section governance
quality-run --id <规则UUID> --run-key <本次任务唯一标识> --reason '检查本次采集论文的摘要完整性' --apply
hub-list --section audit
```

`quality-run` 不带 `--apply` 只展示计划。实际运行会生成检查记录和问题台账，属于受权限约束的写操作。一次任务用固定 `--run-key`；只有用户要求新一轮检查才换标识。只选择已存在、启用、适用于目标数据资产/来源的规则，不能把全库规则假称为单批次规则。当前执行器主要检查论文题名、摘要、期刊名、年份、ISSN、eISSN 等完整性，不等于全量一致性审计。0条范围/不支持规则不是检查通过。

治理顺序：报告缺陷及影响 → 找依据 → 提出具体字段变更 → 用户授权修订 → 写入版本与原因 → 回读 → 再运行适用规则。馆务直接使用 `library-revise`，详见 [馆务说明](library.md)。

## 规范对象修订建议

人员、机构和关系通过系统修订流程，JSON 结构：

```json
{
  "context_object_id":"实际对象UUID",
  "source_label":"可核对的证据名称",
  "reason":"修改原因和依据",
  "proposals":[{
    "target_kind":"object",
    "target_id":"实际对象UUID",
    "field_path":"canonical_name",
    "proposed_value":"有依据的新名称",
    "base_version":1
  }]
}
```

```sh
change-submit --file /绝对路径/修订建议.json --apply
change-detail --id <建议UUID>
```

只能用刚读取的实际版本，不能猜版本1。后台校验字段白名单及证据；论文、期刊对象必须使用领域工作流，不走通用修订。提交的是 **待处理建议**，不会自动采纳或暗改已核验状态。没有实现的领域写接口应明确告知，不用 SQL 替代。`change-submit` 回执去重，成功后回读建议；未知提交结果与论文同样禁止盲重试。

审计需要单独读取权限。403不是“系统没有记录”；检查任务不得变成改角色、放宽权限或核验批量通过。

## 首次登记规则与资产

如果 `hub-list --section rules` 返回空，不能假称已经完成质量检查。先 `hub-options`、`hub-list --section resources` 确认资产与来源；用户要求建立质检流程时可以登记所需规则。JSON 按项目 `knowledge_hub/models.py` 的 `RuleCommand` 填写，例如：

```json
{"data_asset_id":"实际资产UUID","code":"publication.abstract.complete","name":"论文摘要完整性","field":"abstract","severity":"medium","reason":"根据用户要求建立摘要缺项检查"}
```

```sh
register --kind rules --file /绝对路径/规则.json --apply
```

只有确需登记且用户授权时，`register --kind sources|domains|resources` 分别复用 `SourceCommand`、`DomainCommand`、`AssetCommand`；先查实时目录避免重复创建，所有命令保留原因、权限、提交回执和工作台回读。来源登记只是元数据，不会自动抓取外部数据；资产登记也不会自动把既有论文绑定到它。不应创建一个没有论文关联的资产然后宣称检查覆盖了全部论文。没有关联时应报告范围为空并查清业务链路。
