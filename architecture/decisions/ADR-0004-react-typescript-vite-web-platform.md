# ADR-0004：React/TypeScript/Vite 作为校内 Web 主路线

- 状态：已接受
- 决策日期：2026-08-25
- 关联决策：D-02

## 背景

SmartLib 已有七个 React 工作区、成熟视觉样式、Nginx 静态部署和一条经 FastAPI/PostgreSQL 18 验证的真实 API 链路。Web 是多个渠道之一，不拥有独立领域规则；公开 API、MCP、Skill、Agent、小程序和客户端共享能力契约、授权与审计语义，而不是共享页面代码。

## 决策

校内 Web 平台采用：

- React 19.2；
- TypeScript 6.0 严格模式；
- Vite 8；
- React Router 7 Data Mode；
- TanStack Query 5 管理服务端状态；
- 由版本化 OpenAPI 生成 TypeScript 类型和 API 客户端；
- Vitest、Testing Library 与浏览器端到端测试；
- Nginx 静态镜像，同源代理 FastAPI `/api`。

TypeScript 7 暂不作为首版基线，因为当前稳定版不提供编程 API，而 ESLint 等工具链仍以 TypeScript 6 API 为兼容基线。待生成器、lint、编辑器和测试工具完整支持后单独升级。

公开门户、小程序和原生客户端是独立渠道应用。未来若有经确认的 SEO/SSR/SSG 需求，可在 `apps/public-web` 单独评估 Next.js，不把校内平台改造成第二后端。

## 工程边界

1. `app` 只负责应用装配、路由和全局提供器。
2. `routes` 负责路由页面组合，不直接手写网络协议。
3. `features` 拥有具体场景组件和用例状态。
4. `shared` 保存无领域所有权的 UI、布局和基础工具。
5. `generated` 只由 OpenAPI 生成，禁止手工编辑。
6. `fixtures/demo` 只服务测试或明确演示模式；生产真实路由不得静态导入 demo fixture。
7. Web 只调用平台能力 API，不直接访问数据库或复制许可、RLS、审核和审计规则。

## 迁移策略

先在 Vite 7 上建立 TypeScript 6、路由、测试和契约门槛，再把 Vite 8/Rolldown 作为独立变更升级。每阶段均需通过类型、lint、测试、生产构建、深链接刷新、同源 API 和容器健康验证。

## 后果

现有 React 资产可以渐进保留，Web 镜像继续无状态且易于私有化部署。代价是需要显式维护路由、服务端状态、契约生成和测试基线；Vite 本身不替代这些工程能力。

## 实施记录（2026-08-25）

- 已在 Vite 7.3.6 上先完成 TypeScript 6.0.2 严格迁移、React Router 7.18.2、TanStack Query 5.102.3、路由分包和测试基线，再独立升级到 Vite 8.2.2 / React 插件 6.1.0；
- 七个工作区已形成 `/`、`/scholars`、`/research`、`/disciplines`、`/transfer`、`/infrastructure`、`/governance` 深链接；
- OpenAPI 客户端由 `@hey-api/openapi-ts` 0.99.0 生成，并以漂移检查禁止手改；`openapi-typescript` 7.13.0 因 peer 依赖仍限定 TypeScript 5.x 未采用；
- ESLint 10、typescript-eslint、Vitest、Testing Library、Playwright 和 axe 已形成质量门槛；JSX 无障碍旧插件尚未支持 ESLint 10，因此无障碍验收放在真实浏览器 axe 测试；
- `fixtures/demo` 由 `SMARTLIB_WEB_DEMO_MODE` 显式控制，路由层测试禁止直接导入 fixture；知识基础设施页通过生成客户端和 TanStack Query 读取真实 API；
- 契约漂移、严格类型、lint、3 项组件/架构测试、Vite 8 生产构建、浏览器深链接、axe、Nginx 深链接、同源 API 和 Compose 健康均已通过；npm audit 为 0 项漏洞；
- Vite 7 基线构建约 1.52 秒，Vite 8 同等门槛下约 0.70 秒，主入口 gzip 约由 119.71 kB 降至 117.87 kB。该数据只用于本次迁移对比，不是长期性能承诺。

## 复审条件

- 学校冻结其他前端技术规范并提供可持续团队及组件资产；
- 校内平台必须与公开 SEO 门户同应用、同路由、同发布单元；
- 校内受管终端浏览器低于 Vite 8 支持基线且无法升级；
- 真实运行证据显示静态 SPA 无法满足首屏、缓存或可用性目标。
