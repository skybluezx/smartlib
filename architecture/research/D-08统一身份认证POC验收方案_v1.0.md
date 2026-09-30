# D-08 统一身份认证 POC 验收方案 v1.0

- 状态：Demo 阶段已延后；恢复 D-08 后执行
- 日期：2026-08-26
- 当前对象：恢复后的产品中立认证骨架与本地测试发行者；当前 Demo 不执行，学校 SSO/Keycloak 联调按触发条件追加

## 1. 首期必须贯通

1. Web 从未登录跳转到测试 IdP，完成 Authorization Code + PKCE 后建立 BFF 会话；
2. 浏览器只能获得 Secure、HttpOnly、SameSite 会话 Cookie，无法读取 access/refresh token；
3. FastAPI 从验证后的 access token 或 BFF 身份生成 `RequestContext`；
4. `(issuer, subject)` 稳定映射到内部 `principal_id`；
5. API、审计和治理链路区分 human、service、agent 与 delegated 主体；
6. production 配置下不接受 `X-SmartLib-Actor-Id`，OpenAPI 使用标准 security scheme；
7. 退出登录、会话过期、账号停用/绑定冲突走可观察的拒绝路径。

## 2. 绝对门槛

以下任一失败均不得标记 D-08 POC 通过：

- 未签名、错误签名、错误 issuer、错误 audience、过期/未生效 token 任一可访问受保护 API；
- ID Token 被当作 API access token 接受；
- 调用者可用 actor header 冒充他人；
- token 出现在 URL、浏览器 storage、应用日志、审计详情、错误响应或提示词；
- email/姓名变化导致内部人员主键变化或账号串联；
- Web 登录缺少 PKCE `S256`、`state`/`nonce`、精确 redirect URI 或 CSRF 防护；
- BFF 可以把用户 token 转发到未登记目标；
- 学校角色 claim 被直接当作电子资源许可允许结论；
- service/agent 调用被记录为某个人且无委托证据；
- JWKS 轮换后持续拒绝合法新密钥或无界接受已撤销旧密钥。

## 3. 测试身份与负向哨兵

- 教师、学生、馆员、离职/停用人员；
- 同名不同人、同邮箱变更、同一人多 affiliation；
- 两个 issuer 下相同 `sub`；
- 人员主体、服务主体、Agent 主体、用户委托 Agent；
- 正确 token、错误 audience、错误 issuer、过期、未来 `nbf`、未知 `kid`、`alg=none`、错误 token type、缺 scope；
- 会话固定、CSRF、开放跳转、BFF 任意代理、重放授权码；
- 密钥轮换、discovery/JWKS 短暂不可用、时钟偏差。

## 4. 验收指标

| 指标 | 门槛 |
|---|---:|
| 非法令牌拒绝率 | 100% |
| 生产 actor header 冒充成功数 | 0 |
| token 泄漏扫描发现数 | 0 |
| `(issuer, subject)` 映射稳定率 | 100% |
| 受保护 API 认证覆盖率 | 100% |
| 认证/登出/绑定/委托关键审计覆盖率 | 100% |
| PKCE、state/nonce、CSRF 与 redirect 负向用例通过率 | 100% |
| JWKS 正常轮换成功率 | 100% |
| 身份产品类型泄漏到领域/Public API 的位置 | 0 |

## 5. 自动化证据

- 单元测试：claim 验证、主体归一、失败关闭、开发 authenticator 门控；
- 集成测试：真实签名 JWT、discovery/JWKS 缓存和轮换、PostgreSQL 身份绑定/RLS/审计；
- 端到端测试：浏览器登录、会话续期/到期、登出、CSRF、错误 issuer/audience；
- 契约测试：OpenAPI security scheme、Public API 与 MCP/Agent 适配器不接受 actor header；
- 静态扫描：URL、前端 storage、日志、错误和 fixture 中无生产 token；
- 恢复测试：身份映射数据库备份恢复后 principal 绑定不变化。

## 6. 学校 SSO 联调追加验收

取得学校测试环境后追加：claims 字典、测试身份矩阵、MFA/acr、账号停用时效、单点登录、登出边界、证书/密钥轮换、网络故障、联系人与变更通知。若 direct OIDC 全部通过，不启动 Keycloak。

## 7. Keycloak 条件 POC 追加验收

仅在 ADR 触发条件成立时执行：SAML/OIDC broker、claim 映射、账号首次登录与链接冲突、防账号接管、学校停用传播、管理员隔离、HA、数据库备份恢复、版本升级、安全补丁时限和代理退出迁移。通过也只证明其可作为代理，不把人员权威迁入 Keycloak。
