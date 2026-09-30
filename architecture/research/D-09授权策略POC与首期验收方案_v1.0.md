# D-09 授权策略 POC 与首期验收方案 v1.0

- 状态：首次 Demo 阶段已延后；恢复 D-09 后执行
- 日期：2026-08-26
- 当前对象：恢复后的 SmartLib PolicyDecisionPort + in-process adapter + PostgreSQL/RLS；当前不启动，OPA/OpenFGA 条件 POC 继续延后

## 1. 首期必须贯通

1. 同一 `PolicyRequest`/`PolicyDecision` 契约用于治理许可、知识对象、搜索和图；
2. 每个决定包含 effect、reason、obligations、policy/facts version 和 decision ID；
3. 数据库 RLS、投影查询前过滤、service 返回前后验三层一致；
4. 许可从 status/time 扩展到 action/purpose/content/principal/context；
5. allow、deny、approval_required 进入 append-only 审计；
6. Web 可以展示安全的拒绝原因和许可义务，不泄漏受限对象；
7. Web、Public API 与未来 MCP/Agent 适配器共享动作和决定语义。

## 2. 绝对门槛

以下任一失败不得标记 D-09 首期通过：

- 未知、缺失、待审、暂停、过期或未来许可默认允许；
- `campus`、角色、owner、purpose 或 network 由客户端任意声明后可提权；
- 列表、搜索命中、分面计数、图路径或错误信息泄漏不可见对象；
- 任一投影返回越权对象但 service 静默过滤并继续返回部分错误结果；
- ID/类型/动作缺失或 policy adapter 不可用时继续执行业务写操作；
- `approval_required` 被调用方当作 allow；
- 高角色可绕过电子资源许可、外部模型或 TDM 禁止项；
- 决定没有策略/事实版本或关键审计；
- RLS 关闭、数据库角色拥有 `BYPASSRLS` 或适配器直连底层投影绕过平台；
- synthetic 角色被表述为学校真实权限验证。

## 3. 授权哨兵矩阵

至少覆盖：

- public/campus/restricted/private × owner/non-owner；
- approved/pending/suspended/expired/future/unknown；
- view_metadata/view_abstract/view_fulltext/download_single/download_batch；
- text_data_mining/create_embedding/send_to_external_model/train_model；
- Web/API/MCP/Agent channel；
- interactive_search/research_analysis/governance_review/export purpose；
- 节点可见但边不可见、边可见但证据正文不可见、路径含隐藏中间节点；
- 列表为空与对象不存在对外表现一致；
- 策略版本切换、许可撤销、投影延迟和 adapter 故障。

## 4. 验收指标

| 指标 | 门槛 |
|---|---:|
| 未授权对象/关系/证据/计数泄漏 | 0 |
| 默认拒绝矩阵一致率 | 100% |
| 许可动作/用途期望一致率 | 100% |
| allow/deny/approval_required 审计覆盖率 | 100% |
| 决定携带 policy/facts version | 100% |
| 投影越界被整体拒绝 | 100% |
| 多入口策略合同一致率 | 100% |
| synthetic 边界展示覆盖率 | 100% |

## 5. 自动化证据

- 纯策略表驱动测试与 property-based 边界测试；
- PostgreSQL RLS/角色/事务身份数据库行为测试；
- FastAPI 集成测试：单对象、列表、搜索、图、许可、写操作；
- PostgreSQL/OpenSearch 与 PostgreSQL/HugeGraph 同场授权差分测试；
- OpenAPI/capability catalog 动作和授权要求契约测试；
- Web 拒绝/义务/空状态组件与浏览器测试；
- 许可撤销、投影延迟、adapter 不可用和策略版本回滚测试；
- 日志与错误响应的受限对象存在性扫描。

## 6. OPA 条件 POC 验收

触发后验证：同一黄金矩阵在 in-process 与 OPA adapter 结果完全一致；Rego/bundle 测试、签名/版本/回滚、外部事实新鲜度、延迟、HA、无决定失败关闭、decision log 脱敏和恢复。不允许为了通过 POC 改写 Public API 或放弃 RLS。

## 7. OpenFGA 条件 POC 验收

触发后验证：组织/项目/集合/资源多层关系、Check/ListObjects、条件、模型迁移、tuple 写入幂等、outbox 延迟、撤权 SLO、对账/重建、服务故障失败关闭和 PostgreSQL 正确性基线。不把合同许可或证据正文迁入 OpenFGA。
