# 分析与报告留档

## 选范围

```sh
analysis-options
scopes
analyses
```

读取机构、学者、项目种类和已保存范围候选。重名时确认对象；同类条件并集、不同条件交集。优先用已有范围；需要图语句时通过后端受控只读图查询执行，不直接连接 HugeGraph 任意执行。条件 JSON：

```json
{
  "start_year":2024,
  "end_year":2026,
  "organization_ids":["实际机构UUID"],
  "minimum_publication_count":2,
  "edge_limit":120,
  "people_include_external":false,
  "institution_settings":{"mode":"root","root_ids":[],"groups":[]}
}
```

`custom_scope_id` 或 `graph_query` 二选一。字段由项目 `AnalysisDefinition` 校验，未知字段阻断。`institution_settings` 可用 root/internal/expanded，层级不是合作。条件文件仅是传给现有后端的参数，不能改变准入策略。

```sh
analyze --definition /绝对路径/范围.json
analyze --definition /绝对路径/范围.json --module people_collaboration
analysis-save --definition /绝对路径/范围.json --name '本次合作分析' --kind snapshot --run-key <本次任务唯一标识> --apply
analysis-save --definition /绝对路径/范围.json --name '每年复用的分析条件' --kind template --run-key <模板任务唯一标识> --apply
analysis-detail --id <分析记录UUID>
```

不提供 definition 表示当前可见全部论文，不能默认为2026项目代表作。支持 journals/funding/disciplines/people_collaboration/institution_collaboration；不恢复已下线“基金项目期刊指标”。选择一个模块仅返回那个模块，不能说全部已分析。

`analyze` 调服务端计算并生成本地 JSON+Markdown 简报。模板只存条件，下次运行获取最新结果；快照由后台重算存储，随后从快照详情读取，报告绑定同一个 `result_hash`，不是上传先前本地结果假装快照。数据库可能更新，不能把预览与后存快照说成同一时刻；以快照详情为历史依据。新一轮快照用新 run-key，同一轮重跑只读原记录。

## 解释结果

- 当前待核验事实可参与分析，状态和来源保留；采集队列尚未形成规范事实的条目不因这条规则自动进入分析。
- 论文范围是共同分母。项目资助成果与项目代表作分开；同篇多方向/多种类可使覆盖率之和超过100%。
- JCR 按发表年份匹配；缺失不补0、不换年，影响因子是期刊指标而非论文质量。注明覆盖和样本量。
- 合作结构用完整范围计算；显示连线和探索筛选不等于重新分簇，不能拿截取人数当全簇人数。结构、中心候选、成果/基金/学科指标结合论文证据解释。
- PostgreSQL 事实统计和 HugeGraph 投影不是天然实时一致；接口或图查询失败报告未验证，不回退成不等价范围。
- 样本不代表全校完整表现；没有未获批申请分母不能计算成功率，没有外部基准不称全球领先，没有因果设计不说合作模式促成获批。

文件简报只是计算摘要，用户要求深度分析时继续读取 JSON 中簇、论文、覆盖和证据链接，形成有依据的解释，不把固定摘要当完整管理结论。
