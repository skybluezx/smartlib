# ADR-0009：统一身份认证与学校 SSO 路线

- 状态：已决定延后；Demo 阶段不实施
- 日期：2026-08-26
- 决策人：项目负责人（用户）
- 关联编号：D-08

## 背景

SmartLib 同时面向 Web、Public API、MCP、Skill、Agent、小程序和原生/桌面客户端。当前 `X-SmartLib-Actor-Id` 和 Web 角色选择器只服务 synthetic Demo，无法证明调用者身份，不能演进为生产认证。

学校可能提供 OIDC、SAML、CAS 或既有身份代理；这些组织事实尚未取得。若现在把 Keycloak、SAML 或某校 SDK 写入业务核心，将使平台身份边界受部署产品牵制。

## 目标生产路线（保留，尚未接受实施）

采用 **OIDC-first 产品中立认证主路线：学校 IdP 直连优先，Keycloak 仅条件代理**。

1. 学校身份平台是人员身份权威，SmartLib 不建设重复密码账户；
2. 学校 IdP 满足受信发行者合同并提供 OIDC 时直接连接；
3. 只有 SAML/多 IdP/声明归一/客户端能力缺口等触发条件成立时，才启动 Keycloak 代理 POC；
4. 现代 Apereo CAS 若提供合格 OIDC，仍按直连 OIDC；传统 CAS 不成为 SmartLib 全渠道协议；
5. Web 采用 Authorization Code + PKCE 的 BFF 会话；令牌留在服务端；
6. API、MCP、Skill、Agent、小程序和客户端使用面向各自 audience/scope 的短期凭据；
7. 核心只依赖 `IdentityProviderPort` 与归一主体 `(issuer, subject) -> principal_id`；
8. 认证与 D-09 授权分离：学校 claims 是策略输入，不是最终对象/许可决定。

## 当前决定：Demo 阶段延后

项目负责人于 2026-08-26 决定：基于当前使用模拟数据的 Demo 展示，D-08 统一身份认证暂时跳过，不启动 V10 身份域、OIDC/BFF、学校 SSO 或 Keycloak POC 开发。

本 ADR 中的 OIDC-first 内容作为未来生产路线提案保留，但此次延后不等于已经接受该产品路线，也不等于当前系统已具备真实认证能力。恢复 D-08 时仍需结合当时学校身份协议、测试环境、安全要求和依赖版本重新确认。

## 延后期间必须保持的边界

- `X-SmartLib-Actor-Id` 和 Web 角色选择仅用于明确标记的 synthetic Demo；
- Demo 不得宣称已经接入学校统一身份、MFA、账号停用、真实角色或真实人员权限；
- 当前 Demo 只能运行在隔离、非生产、无真实敏感数据环境；
- 不向公网、外部 MCP/Agent 客户端或未经控制的调用者开放当前开发身份机制；
- synthetic 用户 UUID、角色和数据不得被解释为学校真实账号或组织授权；
- 后续模块不得把 actor header 固化为正式 Public API 契约；
- 真实用户、真实数据、试点生产或校级系统联调进入前，必须恢复并完成 D-08。

## 恢复触发条件

出现以下任一条件即重新开启 D-08 决策与实施：

1. 接入学校真实用户、组织、账号状态或统一身份；
2. 引入任何真实、受限、许可或个人信息数据；
3. Demo 环境转为试点生产、公开网络或多人真实使用；
4. Public API、MCP、Skill、Agent、小程序或客户端向真实调用者开放；
5. 需要依据教师、学生、馆员、部门或项目身份进行真实授权；
6. 进行等保、密码应用、安全审计或正式验收。

## 实施约束

- 生产环境移除不可信 `X-SmartLib-Actor-Id`；开发身份模拟只能在显式 development/test authenticator 下启用；
- JWT/API 验证必须覆盖签名、允许算法、issuer、audience、时间、token type、client 和 scope；
- ID Token 不作为 API access token；令牌不得写入 URL、日志、Skill、提示词或浏览器持久存储；
- Web BFF 使用 Secure、HttpOnly、SameSite Cookie，并实现 CSRF、会话固定、代理目标白名单、登出和超时防护；
- 人员、服务、Agent 与委托主体分型，审计保存委托链；
- 邮箱、姓名和可变工号不能作为外部身份唯一键；身份绑定冲突必须人工或受控处置；
- Keycloak 若触发，不得成为学校人员权威，且必须单独通过 HA、备份恢复、升级、安全补丁和管理员隔离验收。

## 恢复后的首期 POC 范围

在不等待学校环境的情况下，使用本地受控测试发行者和测试密钥完成：真实 Authorization Code + PKCE/BFF 会话、API JWT 验证、归一主体映射、开发身份 seam 隔离、四类负向令牌、会话/审计与 OpenAPI security scheme。学校联调或 Keycloak POC 是随后替换适配器，不重写业务模块。

逻辑组件、五个信任边界、各入口时序和威胁控制见《D-08 统一身份认证逻辑架构与信任边界 v1.0》；代码迁移批次见《D-08 统一身份认证开发任务清单 v1.0》。

## 后果

### 正面

- 多入口共享稳定身份语义；
- 能先开发真实认证骨架，又不虚构学校协议；
- 可直接接学校 OIDC，也可在必要时插入代理；
- 身份产品替换不会泄漏到领域 API、授权策略和数据库主键。

### 代价

- BFF、身份映射和严格令牌验证比开发请求头复杂；
- 学校协议、claims、MFA、停用与登出事实仍需正式对接；
- 若触发 Keycloak，将新增安全关键基础设施和持续运维成本。

## 退出与替换

- 学校 OIDC 能力完善：不部署 Keycloak；
- 学校仅 SAML/多 IdP：在 `IdentityProviderPort` 外增加 Keycloak 或校级代理；
- 学校已有其他合格代理：接其 OIDC，不要求改为 Keycloak；
- 代理退出：保留内部 `principal_id` 和外部身份绑定，通过新 issuer 映射迁移，业务对象不换主键。
