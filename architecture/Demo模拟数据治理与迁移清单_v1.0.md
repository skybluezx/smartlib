# Demo 模拟数据治理与迁移清单 v1.0

- 状态：当前基线，随模块接入逐项关闭例外
- 日期：2026-08-26
- 目的：允许 Demo 使用模拟数据，但不把前端原型误当成最终平台实现

## 1. 允许的模拟数据路线

目标路线：

```text
版本化 synthetic 数据集
  → 可重复执行的 seed/import runner
  → FastAPI 应用服务与 PostgreSQL 规范模型
  → 权限、许可、证据、审计与 Outbox
  → OpenSearch/HugeGraph 可重建投影
  → Public API
  → Web / MCP / Skill / Agent / 小程序 / 客户端
```

模拟数据与未来真实数据使用相同业务链路。差异只在来源与真实性标签，不在接口、权限、数据模型或前端实现。

## 2. 当前审计结果

| 区域 | 当前数据来源 | 当前性质 | 处理决定 |
|---|---|---|---|
| 知识基础设施实时对象 | PostgreSQL + FastAPI | 真实平台链路，内容为演示/验证对象 | 保留并改造成正式 synthetic seed |
| D-04 检索面板 | `search_knowledge` API + PostgreSQL/OpenSearch 投影 | 真实平台链路 | 保留 |
| D-05 知识网络面板 | `get_knowledge_neighborhood` API + PostgreSQL/HugeGraph 投影 | 真实平台链路 | 保留 |
| 学者星图 | `scholargraph-demo-v1` → PostgreSQL/RLS → FastAPI/OpenAPI → Web；网络经 GraphPort 读取当前投影 | 真实平台初版，内容为明确标记的 synthetic 数据 | SG-01、SG-02 已完成；SG-03 做双后端与演示验收 |
| 知源智研 | 同一前端 fixture 与组件内固定结果 | 前端展示原型 | 暂时保留，后续随可信问答/任务能力迁移 |
| 学科罗盘 | 同一前端 fixture | 前端展示原型 | 暂时保留，第二批迁移 |
| 成果智桥 | 同一前端 fixture | 前端展示原型 | 暂时保留，第三批迁移 |
| 治理与许可 | `governance-demo-v1` → PostgreSQL/RLS → FastAPI/OpenAPI → Web | 真实平台初版，内容为明确标记的 synthetic 数据 | D-07 例外已关闭；D-08 真实认证与 D-09 新增统一策略层在首次 Demo 阶段延后；既有 RLS/许可/投影防护保持 |
| 全局搜索 | `globalSearchItems` 前端 fixture | 前端展示原型 | 迁移为统一 `search_knowledge` 能力 |

现有架构测试已额外证明 Scholar 路由指向独立真实能力组件，且该组件不导入 fixture。`DemoWorkspaces` 和 `AppShell` 仍为其他模块消费 fixture，因此仍不能宣称“所有页面已使用真实 API”。

## 3. 临时允许条件

既有前端 fixture 在迁移前可以继续用于 Demo，但必须同时满足：

- `SMARTLIB_WEB_DEMO_MODE=true` 时才显示；
- 页面全局提示明确写明“演示数据”；
- 对外介绍区分“已接通真实平台链路”和“待接通展示原型”；
- 不从 fixture 反向写入数据库；
- 不在 fixture 中放入真实个人信息、电子资源原文、密钥或受限数据；
- 不以 fixture 数字支持真实管理判断、绩效评价或资源配置；
- 不再为新能力扩充前端业务事实。

## 4. synthetic seed 规范

每个种子数据集至少包含：

- `dataset_id` 和语义版本；
- `synthetic: true` 与展示说明；
- 固定、可重复的 UUID；
- 明确的数据源记录，`source_type=manual`，授权状态仅代表演示使用；
- 对象、证据、关系和许可标签；
- 期望对象数、关系数、证据数和校验和；
- seed runner 所需平台版本；
- 幂等重跑验证；
- 清理范围与未来真实数据隔离规则。

种子 runner 不使用数据库超级用户，不直接绕过应用校验；若为大批量初始化需要专用导入端口，必须与正式写入共享验证、审计和 Outbox。

## 5. 迁移顺序

1. 建立 synthetic dataset manifest 和幂等 seed runner；
2. 把现有 SmartLib 核心三节点关系切片登记为 `smartlib-core-demo-v1`；
3. **已完成：** 把学者星图的学者、机构、成果、项目、研究方向和证据写入规范模型；
4. **已完成：** 学者目录、画像、网络和证据能力已接入 `/scholars`，页面对应 fixture 和 `DemoBoundary` 例外已关闭；
5. 全局搜索改用统一搜索 API；
6. 学科罗盘改用统计/画像读模型；
7. 成果智桥改用候选匹配和关系解释能力；
8. **已完成：** 治理页改用来源、许可、质量和审计读模型；
9. 知源智研在任务、检索和模型治理路线确认后迁移；
10. 所有 fixture 消费清零后关闭 `DemoBoundary` 例外。

## 6. 每项例外关闭证据

一个模块只有同时满足以下条件才可从“展示原型”改为“真实平台初版”：

- 数据由 synthetic seed 或获授权真实源进入 PostgreSQL；
- API 契约在能力目录登记；
- 身份、权限、许可和审计生效；
- 页面不再导入相应 fixture；
- Demo mode 关闭时该模块仍能展示真实 API 状态或明确空状态；
- 自动测试覆盖幂等 seed、权限、API 和页面；
- 浏览器运行验证无硬编码回退。

## 7. 当前不可作出的声明

在迁移清单关闭前，不得宣称：

- 全部七个工作区已经使用真实平台数据；
- 已经接入学校人事、科研、学科或电子资源系统；
- 页面中的人数、成果数、项目数、趋势和推荐是学校真实统计；
- Demo 已经完成外部数据持续更新。

当前可以准确表述为：SmartLib 已有真实 PostgreSQL/FastAPI/权限/搜索投影/图投影纵向底座；治理与许可工作区、学者星图工作区已经迁移到版本化 synthetic seed 与真实公共 API，其他多个业务工作区仍是明确标记的模拟数据交互原型，正在逐项迁移到同一真实平台能力。
