# SmartLib Database

本目录保存 SmartLib 平台权威数据库的版本化定义。数据库采用 PostgreSQL 18，schema 由 Flyway migration 唯一管理。

## 目录

- `migrations`：只追加的 Flyway SQL migration；已经进入共享环境的文件不得原地修改。
- `tests`：数据库约束、权限、RLS、事务与 Outbox 验证。

## 边界

- 原始文件和大对象不保存在 PostgreSQL；
- 搜索、图、向量和聚合系统不是权威来源；
- 应用不得在启动时自动创建或修改生产表；
- Web 和其他用户入口不得直接连接数据库；
- 数据库登录凭据由运行环境提供，不进入 migration。

搜索投影位于独立的 `smartlib_projection` schema。应用登录只能按 RLS 读取可见文档；投影 worker 使用独立最小权限登录，并且只能通过 security-definer 函数领取事件、刷新投影和确认各投影目标的处理结果。OpenSearch 与 PostgreSQL 投影分别确认，不能以一个目标成功掩盖另一个目标失败。

论文数据采用“原始导入行、规范化论文、标识符、作者序列、字段核验、结论历史”分层保存。原始 Excel 值不会被规范化结果覆盖；核验结论只允许将旧结论退役并追加新结论，以保留完整审计链。论文对象仍由 `knowledge_object` 统一管理，后续可投影到搜索和 HugeGraph。

JCR 等期刊指标采用“数据资产版本、指标发布版、期刊身份、来源行、学科关联、论文匹配”分层保存。JCR 与中科院分区是不同指标体系；指标发布必须通过来源授权、许可目的、记录数和人工权限四重门槛。当前契约见 [`../architecture/journal-metric-governance.md`](../architecture/journal-metric-governance.md)。

## 本地执行

从仓库根目录运行：

```bash
docker compose --env-file infra/compose/.env.local -f infra/compose/compose.yaml up -d
```

查看 migration：

```bash
docker compose --env-file infra/compose/.env.local -f infra/compose/compose.yaml run --rm migrate info
```

验证 migration：

```bash
docker compose --env-file infra/compose/.env.local -f infra/compose/compose.yaml run --rm migrate validate
```

## 虚拟演示数据策略

运行环境不再提供演示种子入口。当前切面只允许通过受控导入任务写入已授权的真实数据；历史演示方案保留在架构决策文档中，不作为可执行数据包。

启动可选 OpenSearch 3.8 POC：

```bash
docker compose --env-file infra/compose/.env.local -f infra/compose/compose.yaml --profile search-poc up -d
```

该 profile 在本机关闭 OpenSearch Security 插件，只用于隔离开发 POC，不能作为生产部署模板。
