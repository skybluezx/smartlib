# SmartLib Knowledge Platform

赛事申报材料、业务数据和历史分析产物保留在本地 `outputs/`，不纳入公开代码仓库。

SmartLib 智能知识平台是图书馆牵头建设的学校级知识基础设施。本仓库用于持续建设最终系统；当前已具备 Web、Python/FastAPI 平台核心、PostgreSQL 18 权威数据层、MinIO Community 对象存储、OpenSearch 3.8 检索投影和 HugeGraph 1.7 图投影的首个真实纵向切片，后续能力按架构决策逐项接入。

## 当前工程状态

- `apps/web`：可运行的 Web 入口；知识基础设施页和学者星图页已读取真实公共 API，其他未迁移页面仍明确标出演示数据。
- `apps/platform-api`：Python 3.14/FastAPI 模块化平台核心，包含来源、知识、关系、检索、知识网络、任务和健康接口。
- `packages/api-contracts`、`packages/capability-catalog`：版本化 OpenAPI 和面向 MCP/Skill/Agent 的协议无关能力目录。
- `database`：PostgreSQL 18 权威数据库的 Flyway migration 与行为测试。
- `infra/compose`：开发、集成和首版展示环境的容器编排基线；包含源码构建的 MinIO Community 与论文文件桶初始化。
- `architecture`：技术架构、选型决策单和 ADR。
- `assets`：总体设计与架构素材；`work`、`outputs` 为本地资料与产物目录，不随源码发布。

## 代码与数据边界

本仓库保存当前 Web/API 源码、测试、数据库迁移、配置模板、架构说明和 `skills/smartlib-knowledge-hub`。数据库备份、论文全文、InCites/JCR 原始文件、馆务工作表、业务报告、部署验收记录及访问凭据不随代码公开。部分历史批次测试和脚本依赖这些独立保管的材料；代码仓库不等于业务数据库备份，也不能据此宣称这些材料已完成导入。

配置文件只提交 `.env.example`。实际环境值保存在被忽略的 `infra/compose/.env.local` 或由部署环境注入。不要提交真实密码、私钥、Token、数据库导出或带业务数据的静态报告。

主数据库已确认 PostgreSQL 18，平台核心已确认 Python/FastAPI，校内 Web 已确认 React 19.2/TypeScript 6/Vite 8，当前 Demo 对象存储采用源码构建的 MinIO Community，搜索 POC 已确认 OpenSearch 3.8，专用图投影已切换为 HugeGraph 1.7。AI/Agent 框架仍将在对应 ADR 确认后加入。MinIO 保存论文全文等大对象，PostgreSQL 保存对象元数据、受控引用和校验值；HugeGraph 仅保存可重建投影。

## 启动当前底座

首次克隆后复制配置模板，填写五个独立的随机密码，并将全文来源目录设为自己有权使用的路径。已有本地 `.env.local` 时不要覆盖。

```bash
cp infra/compose/.env.example infra/compose/.env.local
chmod 600 infra/compose/.env.local
```

完成配置后启动：

```bash
docker compose --env-file infra/compose/.env.local -f infra/compose/compose.yaml up --build -d
```

同时启动已确认的搜索与图投影 POC：

```bash
docker compose --env-file infra/compose/.env.local -f infra/compose/compose.yaml --profile search-poc --profile graph-poc up --build -d
```

查看状态：

```bash
docker compose --env-file infra/compose/.env.local -f infra/compose/compose.yaml ps
```

停止：

```bash
docker compose --env-file infra/compose/.env.local -f infra/compose/compose.yaml down
```

默认容器 Web 地址：`http://localhost:18080`  
容器健康检查：`http://localhost:18080/healthz`
Platform API：`http://localhost:18081`  
OpenAPI 文档：`http://localhost:18081/docs`
MinIO S3 API：`http://localhost:19000`  
MinIO 管理控制台：`http://localhost:19001`  
HugeGraph REST：`http://localhost:18082/versions`

HugeGraph Hubble：`http://localhost:18088`。在 Hubble 中登记图服务时使用内部地址
`http://hugegraph:8080`、图名 `hugegraph`、用户 `admin`，密码读取当前部署环境的
`SMARTLIB_HUGEGRAPH_PASSWORD`；不要填写浏览器访问用的 `localhost:18082`。

构建镜像源通过 `SMARTLIB_NODE_IMAGE`、`SMARTLIB_NGINX_IMAGE` 和 `SMARTLIB_PYTHON_IMAGE` 配置。默认使用 Docker Hub；受限网络环境可在本地 `.env` 中切换为组织批准的等价镜像地址，无需修改 Dockerfile。

PostgreSQL 默认只在 Compose 内部网络开放，不映射主机 5432。`.env.example` 仅包含密码占位符；真实密码必须由私有配置或密钥管理提供。直接启动 Python 服务时也必须配置连接参数，源码不再包含连接密码。数据库 migration、验证和恢复说明见 [`database/README.md`](database/README.md) 与 [`infra/backup/README.md`](infra/backup/README.md)。

MinIO 初始化任务会幂等创建 `smartlib-publications` 桶并开启对象版本控制，文件保存在独立命名卷 `smartlib-minio`。当前 Community 镜像固定从 MinIO 官方最后源码提交构建，适合本地开发和 Demo；上游仓库已停止维护，正式生产前必须重新评估安全维护、AGPLv3 许可、高可用和支持方案。部署细节见 [`infra/minio-community/README.md`](infra/minio-community/README.md)。

## 本地前端开发

```bash
cd apps/web
npm install
npm run dev
```

本地 Vite 开发服务默认使用 `http://localhost:5173`，可与容器入口同时运行。

前端完整质量门槛：

```bash
npm run check
npm run test:e2e
```

`npm run check` 依次验证 OpenAPI 生成客户端无漂移、严格类型、lint、组件/架构测试与 Vite 生产构建。`npm run test:e2e` 验证 URL 深链接与 axe 无障碍规则。更新平台 OpenAPI 后先运行 `npm run generate:api`，不要手工修改 `src/generated`。

当前七个工作区均有独立 URL：`/`、`/scholars`、`/research`、`/disciplines`、`/transfer`、`/infrastructure`、`/governance`。Compose 的 `SMARTLIB_WEB_DEMO_MODE=true` 明确启用展示数据；正式环境应设为 `false`，未接入真实领域服务的模块会显示明确的未接入状态。

Demo 阶段暂缓外部连接器与 SeaTunnel POC。模拟数据只允许作为明确标记、版本化和可替换的种子数据，通过真实 PostgreSQL、应用服务、权限、证据、Outbox、搜索/图投影和公共 API 链路进入页面；不得新增仅存在于前端数组中的业务事实，也不得把模拟数据表述为已接入真实学校系统。首批真实数据接入前重新打开 ADR-0007。

既有页面的模拟数据例外、迁移顺序和完成证据见 [`architecture/Demo模拟数据治理与迁移清单_v1.0.md`](architecture/Demo模拟数据治理与迁移清单_v1.0.md)。

D-07 已完成首期 synthetic 基线：治理与许可页现在通过公共 API 读取 PostgreSQL 中的治理资产、许可、质量规则/运行/问题、责任和当前身份审计，并支持资产及知识对象来源追溯。OpenMetadata 仍按 ADR-0008 延后到真实技术元数据阶段。

D-12 的 SG-01、SG-02 已完成：`scholargraph-demo-v1` 通过 PostgreSQL 规范对象、关系、证据、Outbox、搜索/图投影和四个 Scholar 公共读能力提供数据；`/scholars` 已迁出 fixture，通过公共 Scholar ID 展示人才发现、事实画像、知识网络和证据追溯。SG-03 将继续完成 PostgreSQL/HugeGraph、PostgreSQL/OpenSearch 双后端、故障降级和最终演示验收。

论文治理已增加 JCR 期刊指标存储：按资产版本、年度、期刊、来源行和 WoS 学科保存，并通过独立匹配表关联论文。当前两份本地工作簿仅作为来源未核验、许可待审的暂存版本，不会自动进入论文结论；发布门槛与使用边界见 [`architecture/journal-metric-governance.md`](architecture/journal-metric-governance.md)。

当外部镜像仓库临时不可用、但本地已经存在 SmartLib 镜像时，可使用 `infra/compose/compose.local-source.yaml` 只读挂载当前 API 源码和已验证的 Web `dist` 完成本机 QA。该覆盖文件不用于共享、测试或生产环境。

## 建设规则

每项底层技术先完成选择和 ADR，再进入实现。Web、API、MCP、Skill、Agent、小程序和客户端必须共享统一能力、授权、许可、证据与审计，不得分别复制数据和业务逻辑。
