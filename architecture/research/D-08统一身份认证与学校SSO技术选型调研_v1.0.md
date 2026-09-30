# D-08 统一身份认证与学校 SSO 技术选型调研 v1.0

- 状态：调研已完成；项目负责人决定 Demo 阶段延后实施
- 日期：2026-08-26
- 范围：身份认证、身份归一、会话与令牌边界；不代替 D-09 授权决策

## 1. 当前阶段决定与目标建议

项目负责人于 2026-08-26 决定：当前模拟数据 Demo 暂不实施真实统一身份认证。本调研保留为进入真实用户、真实数据、试点生产或对真实调用者开放多接口时的决策输入，不表示目标建议已经被接受或当前 Demo 已具备认证能力。

建议采用 **OIDC-first、学校 IdP 直连优先、Keycloak 条件代理** 的产品中立路线：

1. 学校统一身份平台始终是人员身份权威，SmartLib 不建立第二套用户名/密码体系；
2. 学校 IdP 满足 SmartLib 接入合同并提供合格 OIDC 时直接连接；
3. 学校仅提供 SAML 2.0、存在多个 IdP、或关键声明/客户端能力无法统一时，才引入 Keycloak 作为身份代理和声明归一层；
4. 如果学校使用现代 Apereo CAS 且已启用 OIDC，则按“学校 OIDC 直连”处理；传统 CAS-only 不作为 SmartLib 全渠道公共认证协议；
5. Web 使用 BFF 会话，令牌只保存在服务端；Public API、MCP、Skill、Agent、小程序和原生客户端按各自客户端类型使用短期、限 audience/scope 的访问令牌；
6. FastAPI 只依赖稳定的 `IdentityProviderPort` 与归一主体，不依赖 Keycloak、SAML 或某校厂商 SDK。

Keycloak 在这一路线中是可插拔兼容设施，不是 SmartLib 的固有组成，也不是学校目录的替代品。

## 2. 当前基线与缺口

当前 FastAPI 使用可选的 `X-SmartLib-Actor-Id` 形成开发请求上下文，Web 角色切换也是展示控件。这一机制没有验证签名、发行者、受众、有效期或会话，必须明确限定为本地 synthetic Demo seam。

生产环境不能继续“要求请求方传 actor header”，因为调用者可以伪造任意主体。D-08 实施后：

- 外部请求只接受受信发行者签发并完整验证的凭据，或 BFF 建立的服务端会话；
- `actor_id` 由认证适配器从已验证身份映射生成，而不是从不可信请求头读取；
- 非开发 OpenAPI 不再暴露 `X-SmartLib-Actor-Id`；
- D-09 使用认证结果做策略输入，但学校角色声明本身不是最终授权决定。

## 3. 方案比较

| 方案 | 全渠道适配 | 额外运维 | 优点 | 主要风险/边界 | 结论 |
|---|---:|---:|---|---|---|
| A. 学校 OIDC 直连 | 高 | 低 | 权威链路短；沿用学校 MFA、会话与停用；少一层关键基础设施 | 依赖学校测试环境、声明质量、客户端注册和令牌能力 | **满足合同即首选** |
| B. Keycloak 身份代理 | 高 | 高 | 可代理 OIDC/SAML、归一声明、连接多 IdP，并统一 SmartLib-facing OIDC | 新增高价值安全面、数据库、HA、备份、升级和补丁责任；错误账号链接有接管风险 | **仅条件触发** |
| C. SmartLib 直接做 SAML SP | Web 中；API 低 | 中 | 可快速接入只提供 SAML 的学校 | SAML 断言不是多渠道 API 令牌；仍需本地会话/令牌转换；协议逻辑渗入平台 | 不作公共主路线 |
| D. SmartLib 直接做传统 CAS 客户端 | Web 中；其他低 | 中 | 兼容遗留学校登录 | 不足以统一 API、MCP、Agent、原生客户端和服务主体；扩大自研协议面 | 仅临时兼容桥，不推荐 |
| E. 现代 Apereo CAS 的 OIDC 能力 | 高 | 低 | 学校保留 CAS 运维，SmartLib 仍使用标准 OIDC | 取决于学校是否真正启用 OIDC discovery、客户端注册和所需 claims | 归入 A |

Keycloak 官方文档确认其支持 OIDC、SAML、身份代理和 LDAP/AD 用户联邦，但这同时意味着它是需要持续运维的安全关键服务器，而不是一个无成本“转换组件”（[Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/)）。Apereo CAS 当前协议概览包含 CAS、SAML、OAuth 2.0 与 OIDC，因此不能仅凭“学校使用 CAS”推断必须在 SmartLib 内实现传统 CAS（[Apereo CAS Protocol Overview](https://apereo.github.io/cas/8.0.x/protocol/Protocol-Overview.html)）。

## 4. 产品中立认证合同

### 4.1 受信发行者合同

每个生产发行者必须登记并版本化：

- 精确 `issuer`、discovery 地址、JWKS 地址和允许算法；
- SmartLib 的 client、redirect URI、post-logout URI 与 audience；
- 支持 Authorization Code、PKCE `S256`、`state`、`nonce` 的证据；
- access token 格式、有效期、时钟偏差、密钥轮换与故障策略；
- `sub` 稳定性、账号停用、人员号/组织/身份类型等声明定义；
- MFA/认证强度的 `acr`/`amr` 语义；
- 前后端登出、会话失效、测试租户和测试账号；
- 运维联系人、安全事件、证书/密钥轮换和变更通知机制。

OIDC 的身份主键是 `(issuer, subject)`，不得用 email、姓名、手机号或可变工号作为唯一外部身份键。OIDC Core 明确定义了发行者、主体、受众、时间与认证上下文等 ID Token claims，并要求客户端验证认证结果（[OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)）。

### 4.2 SmartLib 归一主体

认证适配器至少产出：

```text
principal_id        SmartLib 内部稳定 UUID
principal_type      human | service | agent | delegated
issuer + subject    外部身份不可变组合键
institutional_id    经治理的学校人员/系统标识，可空
display_name        展示属性，不作为主键
affiliations        学校、院系、人员类型及版本时间
acr / amr            认证强度和认证方式
auth_time / session  认证时刻和会话引用
client_id / audience / scopes
delegation_chain     用户、代理 Agent、服务主体的委托链
```

建议在 PostgreSQL 增加 `principal`、`external_identity`、`affiliation_snapshot`、`service_principal` 和必要的身份绑定审计表。只保存映射与审计所需信息，不保存学校密码，不明文长期保存 access/refresh token。

## 5. 不同入口的认证方式

| 入口 | 推荐流程 | SmartLib 接收形态 | 关键边界 |
|---|---|---|---|
| Web | OIDC Authorization Code + PKCE；FastAPI BFF 作为 confidential client | Secure、HttpOnly、SameSite 会话 Cookie | 令牌不进入 localStorage/sessionStorage；BFF 防 CSRF，代理目标白名单 |
| Public API / SDK | 用户委托 token 或服务主体 token | Bearer/必要时 sender-constrained access token | 验证 issuer、signature、audience、time、scope；最小权限 |
| 原生/桌面客户端 | 系统外部浏览器 + Authorization Code + PKCE | 短期 access token | 禁止嵌入 WebView 收集学校凭据 |
| 小程序 | 平台后端完成学校身份绑定和 code exchange | 小程序专用短期 token | 不复用 Web client；绑定、解绑和设备风险可审计 |
| MCP / Skill | 宿主经受控连接获得用户委托，或独立服务主体 | 限能力、限用途、短期 token | 不把生产令牌写入 URL、Skill 包或提示词 |
| Agent | 用户委托 + Agent 身份，或独立服务主体 | 带委托链和任务上下文 | 不能把 Agent 等同最终用户；高风险动作另行批准 |
| 系统间任务 | Client Credentials，优先 `private_key_jwt`/mTLS | 服务主体 token | 不冒充人员；凭据可轮换；独立 audience/scope |

RFC 9700 要求公共客户端使用 PKCE，并建议 confidential client 也使用；同时不建议 implicit flow，要求 access token 做 audience 和权限限制（[OAuth 2.0 Security Best Current Practice, RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html)）。原生应用应通过系统外部浏览器完成授权，不能用嵌入式 WebView 获取凭据（[OAuth 2.0 for Native Apps, RFC 8252](https://www.rfc-editor.org/rfc/rfc8252.html)）。

Web 首选 BFF 是为了不向浏览器 JavaScript 暴露 access/refresh token；IETF 浏览器应用安全草案把 BFF 描述为服务端 confidential client，同时要求严格限制代理目标并处理 CSRF。该文档仍是 Internet-Draft，因此这里将其作为架构安全依据，而非已发布 RFC（[OAuth 2.0 for Browser-Based Applications draft](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-browser-based-apps)）。

## 6. API 令牌验证最小门槛

资源服务器必须失败关闭并验证：

1. 发行者精确匹配受信配置，禁止根据请求动态信任任意 issuer；
2. 签名与允许算法；密钥只来自登记的 discovery/JWKS，支持安全缓存与轮换；
3. `aud` 包含目标 SmartLib API；
4. `exp`、`nbf`、`iat` 与有限时钟偏差；
5. 客户端、scope 与 token 类型适用于目标接口；
6. ID Token 只用于登录认证，不当作 Public API access token；
7. bearer token 不出现在 URL、日志、错误、审计详情、提示词或前端持久存储；
8. 未知发行者、错误受众、过期、错误算法、缺少主体、身份绑定冲突一律拒绝；
9. `trace_id`、`principal_id`、`client_id`、动作和策略结果进入审计，但令牌原文不进入；
10. 高风险或高敏数据可要求更高 `acr`、重新认证或 sender-constrained token。

## 7. Keycloak 条件触发与边界

满足任一项时才启动 Keycloak POC：

- 学校只提供 SAML 2.0，且身份部门不提供面向 SmartLib 的 OIDC；
- 两个以上学校/联盟 IdP 需要统一 SmartLib-facing issuer 与 claims；
- 学校 IdP 不能提供 SmartLib 所需客户端类型、服务主体、委托或令牌 audience；
- 学校明确指定 Keycloak 为校级身份代理，已有运维、安全和备份责任人。

采用后必须遵守：学校 IdP/目录仍是人员权威；禁止本地密码登录生产人员账号；只同步最少 claims；账号链接要防冲突和接管；管理员权限、密钥、数据库、HA、备份恢复、日志、安全补丁和应急流程纳入生产验收。Keycloak 版本必须在实际 POC 时重新确认，不在 ADR 中永久钉死当前版本。

## 8. 当前缺少的学校事实

在真实学校 SSO 联调前必须取得：协议与版本、OIDC discovery 或 SAML metadata、测试环境、测试身份矩阵、客户端注册流程、claims 字典、MFA 规则、账号停用时效、登出语义、密钥/证书轮换、网络与域名要求、审计与等保要求、身份团队责任人。

这些事实决定“直接 OIDC”还是“条件代理”的部署分支，但不阻塞先实现产品中立的认证端口、JWT 验证和本地测试发行者 POC。

## 9. Python 实现库选项

首期不手写 OAuth/OIDC 协议。候选分为：

- **Authlib：** 覆盖 Starlette/FastAPI Web OAuth/OIDC client、metadata、Authorization Code、PKCE 与 ID Token 处理，适合作为 BFF 主候选（[Authlib Web Clients](https://docs.authlib.org/en/stable/oauth2/client/)）；
- **PyJWT：** 聚焦资源服务器 JWT/JWKS 验证，`PyJWKClient` 支持 JWKS 获取、缓存和未知 `kid` 刷新，适合作为 API 验证的小边界基线（[PyJWT Usage](https://pyjwt.readthedocs.io/en/latest/usage.html)）；
- **完全手写：** 需要自行覆盖 discovery、state、nonce、PKCE、claims、算法约束、JWKS 缓存与轮换，安全维护风险过高，排除。

建议在 ADR 确认后用当前 Python 3.14/FastAPI 版本同场验证 Authlib 单库方案与 Authlib(BFF)+PyJWT(API) 方案。以负向安全测试、类型兼容、密钥轮换、依赖边界和可维护性决定最终锁定版本，不把当前网页显示版本写成长期架构承诺。实施拆分见《D-08 统一身份认证开发任务清单 v1.0》。
