# ADR-0010：授权策略与细粒度访问控制路线

- 状态：已决定延后；首次 Demo 阶段不新增统一策略层
- 日期：2026-08-26
- 决策人：项目负责人（用户）
- 关联编号：D-09

## 背景

SmartLib 当前已有 PostgreSQL RLS、最小数据库角色、许可 grant、投影过滤、搜索/图 service 后验和 append-only 审计。这些是真实防护，但策略仍分散在 SQL、adapter、service 和 helper，尚无跨 Web、API、MCP、Skill、Agent、小程序与客户端共享的正式决定合同。

D-08 在 synthetic Demo 阶段已延后，因此当前只能使用明确标记的测试主体；但授权与许可不能整体跳过，否则搜索、图、治理、问答、导出和多入口将出现真实数据边界缺口。

## 目标路线提案（保留，尚未接受实施）

采用 **SmartLib `PolicyDecisionPort` + PostgreSQL 权威策略数据与 RLS 当前主路线；OPA POC 延后至跨服务/策略独立发布阶段；OpenFGA POC 延后至关系授权规模阶段**。

当前不部署 OPA 或 OpenFGA，不组合三套授权运行时。首期建立产品中立策略合同与进程内 adapter，并把现有规则逐步迁入；外部引擎未来只能通过同一 port 接入。

## 当前决定：首次 Demo 阶段延后

项目负责人于 2026-08-26 决定：基于当前首次 Demo 展示阶段，D-09 新增统一授权策略层暂时跳过，不启动 `smartlib_platform.policy`、`PolicyDecisionPort`、OPA 或 OpenFGA 的开发与 POC。

此次延后只针对“新增统一策略抽象和外部授权运行时”，不授权删除、放宽或绕过当前已经生效的 PostgreSQL RLS、最小数据库角色、许可默认拒绝、搜索/图谱查询前过滤、service 后验和 append-only 审计。当前防护是 Demo 既有数据边界，不是待选产品。

本 ADR 的目标路线提案、动作词表、决定合同和触发条件保留。恢复 D-09 时必须结合当时入口范围、真实角色/数据、许可复杂度和软件版本重新确认，不得把本次延后解释为目标路线已接受。

## 延后期间必须保持的边界

- 不改变现有 RLS policy、`NOBYPASSRLS` 角色、schema/table 最小授权；
- 未知、待审、暂停、过期和未来许可继续默认拒绝；
- OpenSearch/HugeGraph 查询仍在适配器前置过滤，并由 service 做越界后验；
- 任何越界投影结果仍整体拒绝，不能为了展示继续返回；
- synthetic actor、角色、campus 语义不得表述为学校真实权限验证；
- 首次 Demo 不开放给不受控真实调用者，不使用真实敏感/许可数据；
- 后续代码不得复制新的授权判断到前端、MCP、Skill、Agent 或客户端；
- 写操作、许可状态和治理访问继续保留审计。

## 恢复触发条件

出现以下任一条件即重新开启 D-09：

1. 接入真实用户、真实角色、组织、项目成员或真实许可数据；
2. 首次 Demo 转为多人试点、试点生产或外部网络开放；
3. Public API、MCP、Skill、Agent、小程序或客户端向真实调用者开放；
4. 新增第二个需要复制权限判断的领域或独立服务；
5. 需要展示真实允许/拒绝原因、处理义务或人工批准；
6. 出现共享、继承、反向授权查询或复杂用途许可；
7. 进行正式安全、合规、等保或验收测试。

## 必须保持的边界

- PostgreSQL 保存许可、资源、关系、组织和审核权威事实；
- RLS 是不可绕过的纵深防护，不等于完整应用授权；
- 默认拒绝；未知、待审、暂停、过期、事实缺失和策略不可用不能放行；
- 决定至少返回 effect、reason codes、obligations、policy/facts version 和 decision ID；
- 客户端提供的角色、owner、许可、网络和用途不能直接视为可信；
- 列表、搜索、分面、图路径、问答上下文、导出和计数都执行权限过滤；
- 投影系统在查询前过滤，service 在返回前后验，发现越界整体拒绝；
- allow、deny 和 approval_required 均记录 append-only 审计且不泄漏受限对象存在性；
- D-08 延后期间，所有主体/角色演示必须标记 synthetic，不宣称真实人员授权；
- OPA/OpenFGA 产品 ID、Rego、tuple 或查询语言不得进入 Public API 和领域模型。

## 恢复后的首期实施

1. 新建 `smartlib_platform.policy` 模块；
2. 定义 `PolicyRequest`、`PolicyDecision`、`PolicyDecisionPort` 和稳定动作/原因/义务词表；
3. 提供 in-process adapter 和默认拒绝；
4. 统一许可状态/用途判定；
5. 接入搜索、图和治理的 service 后验与审计；
6. 增加单对象、列表、分面、路径、投影撤权和故障测试；
7. 保留 OPA/OpenFGA adapter 契约，不启动运行时。

## OPA 重新评估触发

- 跨两个以上独立服务/语言复用属性和用途策略；
- 策略需要独立于应用审核、签名、发布和回滚；
- Python policy core 的规则组合与义务明显不可维护；
- bundle、决策日志脱敏、HA 和运维责任已明确。

## OpenFGA 重新评估触发

- 多层组织/项目/集合/文档继承与用户分享成为核心需求；
- `ListObjects`/反向授权查询成为性能关键；
- 关系规模和变化率使 PostgreSQL 基线不能满足 SLO；
- 已有真实模型、tuple、撤权、迁移、对账和恢复测试集。

## 后果

### 正面

- 继续强化当前真实权限/许可链路，而不为 synthetic Demo 增加无证据的基础设施；
- 多入口共享稳定策略语义；
- SmartLib 许可和证据义务不被通用引擎模型吞没；
- OPA/OpenFGA 可在触发后替换 adapter，不重写业务 API。

### 代价

- 当前团队必须维护严格的 Python policy core、版本和测试；
- 外部策略人员暂不能独立用 Rego 发布；
- 关系分享和大规模反向查询仍需 PostgreSQL 基线；
- D-08 延后意味着当前只能证明 synthetic 主体下的授权正确性，不能证明学校真实角色矩阵。

## 退出与替换

- OPA POC 通过：作为 attribute/context policy adapter，PostgreSQL/RLS 保持；
- OpenFGA POC 通过：作为 relationship projection adapter，权威关系仍在 PostgreSQL；
- 两者均未触发：继续使用 in-process adapter；
- 任一外部引擎退出：由 PostgreSQL 权威事实和版本化策略重建或切回 in-process adapter。
