# ADR-0011：任务执行与工作流编排路线

- 状态：已决定延后；首次 Demo 阶段不建设通用任务执行链路
- 日期：2026-08-26
- 决策人：项目负责人
- 关联编号：D-10

## 背景

SmartLib 已有 PostgreSQL `async_job`、Outbox、任务状态读取 API，以及搜索/图投影 worker，但尚无通用任务创建、并发领取、租约/心跳、尝试/步骤历史、取消、幂等、SSE 和故障接管。Web “知源智研”的任务进度和结果仍是前端模拟。

当前没有足够真实流程证明应部署 Temporal、Camunda 或 Airflow。原提案中的真实任务闭环可以成为未来工作流引擎的业务契约起点，但本次 Demo 的展示重点已经明确为“学者星图”，不以“知源智研”后台任务过程作为价值证明。

## 当前决策

**D-10 的路线确认和开发均延后。** 首次 Demo 不补建通用任务状态机、任务 worker、SSE 进度或外部工作流引擎；保留现有 `async_job`、Outbox、搜索/图投影 worker 和前端模拟任务，且不得把它们表述为已经完成的通用任务平台。

恢复 D-10 时，以 **SmartLib PostgreSQL 持久任务状态机 + 幂等 Python worker** 作为待重新确认的首选提案；Temporal、Camunda、Airflow/Dagster 仍按流程类型和复杂度触发 POC，而不是默认引入。

## 必须保持的边界

- PostgreSQL 保存 SmartLib 产品任务的权威状态和 append-only 事件；
- 任务 handler 通过 registry 注册，客户端不能提交任意代码/命令；
- 领取使用并发安全锁与有限 lease，worker 崩溃后可接管；
- 所有 handler 按至少一次执行设计，副作用必须有幂等键；
- 状态迁移有前置状态、版本和审计，终态不可静默倒退；
- 重试只针对明确可重试错误，指数退避且有上限；
- 取消是请求—确认语义，不能假装强制终止已发生的外部副作用；
- 输入/输出、handler、数据、策略、模型和产物按适用版本化；
- 大 payload/产物进入对象存储，不塞入 PostgreSQL JSON；
- RLS 保证用户只能读取自己的任务；worker 使用独立最小权限角色；
- 外部引擎未来通过 task/workflow adapter 接入，不泄漏其 execution ID 到 Public API；
- synthetic 任务和预制结果不得表述为真实模型/真实数据运行。

## 延后期间保留边界

- `async_job`、Outbox 和现有投影 worker 作为骨架保留，不为本次 Demo 扩建通用能力；
- “知源智研”的模拟进度和预制结果必须继续明确标记为演示，不宣称真实后台执行或模型生成；
- 学者星图所需的图投影更新仍沿用现有专用 worker，不因 D-10 延后而停用；
- 不新增 RabbitMQ、Temporal、Camunda、Airflow/Dagster 或任务编排基础设施；
- 不允许客户端通过现有任务字段提交任意代码、命令或 handler；
- 后续真实任务开发不得绕过任务幂等、审计、许可和 RLS 边界。

## 恢复后的候选实施

1. 版本化增强 `async_job` 并新增 attempt/step/event/artifact/lease；
2. job type/handler registry 和输入输出 schema；
3. create/get/cancel/list API 与 SSE 进度；
4. PostgreSQL 并发领取、heartbeat、lease expiry、retry/dead-letter；
5. 幂等、取消、超时和故障恢复；
6. 选择当时优先场景作为第一个真实 handler，不预先绑定“知源智研”；
7. 数据库、后端、Web 和双 worker 竞争/崩溃恢复测试。

## 外部引擎触发

- Temporal：长时间代码工作流、timer/signal、复杂补偿/并行和 Agent 持久恢复；
- Camunda：BPMN、用户任务、表单、指派/候选组/期限成为业务核心；
- Airflow/Dagster：多条定时数据 DAG、分区回填、依赖和数据平台运维达到规模，优先复用学校现有平台。

## D-10 恢复触发

- Demo 范围重新纳入需要真实创建、执行、取消和追踪的后台任务；
- 学者星图出现必须异步运行的画像重建、批量图投影、导出或报告任务，现有专用 worker 无法安全承载；
- 真实数据接入带来定时加工、回填、失败恢复、人工确认或跨服务长流程；
- Public API、MCP、Skill、Agent、小程序或客户端需要统一任务状态；
- 出现双 worker 竞争、宕机接管、幂等副作用或可追溯进度的正式验收要求；
- BPMN、长时间 durable execution 或数据 DAG 规模达到外部引擎 POC 条件。

## 后果

### 正面

- 首次 Demo 的开发资源集中于学者星图；
- 不为非重点展示链路提前增加任务平台的实现和故障测试成本；
- 不把一个 loading 动画误做成大型工作流平台采购依据。

### 代价

- 首次 Demo 不具备真实、通用、可取消和可恢复的后台任务闭环；
- “知源智研”继续停留在明确标注的前端模拟状态；
- 多入口统一任务状态、BPMN、复杂 DAG 和跨服务 durable execution 均待后续建设。

## 退出与替换

- 当前闭环持续满足：保留 PostgreSQL worker；
- 外部 POC 通过：adapter 将执行交给引擎，SmartLib job ID 和状态 API 保持；
- 外部引擎退出：依据 SmartLib 权威任务记录、业务幂等键和产物引用恢复/迁移；
- 不允许同时让多个引擎成为同一任务状态的权威。
