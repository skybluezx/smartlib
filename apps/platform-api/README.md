# SmartLib Platform API

SmartLib 的权威领域 API。它连接 PostgreSQL 18，按调用者设置事务级 RLS 上下文，并在创建知识对象时原子写入 Outbox。

开发身份由 `SMARTLIB_DEV_ACTOR_ID` 提供，仅用于隔离的 synthetic Demo 和本地 Compose，不代表真实学校用户或真实角色。D-08 已在 Demo 阶段延后；进入真实用户/数据、试点生产或对真实调用者开放接口前，必须恢复 D-08 并替换为正式统一身份适配器。

## 检索能力

`POST /api/v1/search` 发布稳定的 `search_knowledge` 契约。领域服务只依赖 `SearchPort`，可在 PostgreSQL 基线和 OpenSearch POC 适配器之间切换；底层 DSL 不进入公共接口。

- `SMARTLIB_SEARCH_BACKEND=postgres`：默认路线；
- `SMARTLIB_SEARCH_BACKEND=opensearch`：D-04 POC 路线；
- 身份与调用用途由可信运行上下文注入，客户端不能自行声明；
- 检索前执行后端权限过滤，返回后再做 fail-closed 校验；
- 审计只记录查询指纹，不记录原始查询文本；
- 当前只开放 `lexical`；`semantic` 和 `hybrid` 等待嵌入模型与融合策略决策。

OpenAPI 由 `scripts/export_openapi.py` 导出到共享契约包，再生成 TypeScript 客户端。Web 不维护另一套手写搜索协议。

## 学者星图公共读能力

SG-01 提供四个只读能力：学者目录、事实画像、受限知识网络和证据追溯。它们读取 PostgreSQL 规范对象/关系/证据，并通过同一 GraphPort 使用 PostgreSQL 或 HugeGraph 投影；不包含排名、人才评价、AI 推荐或纠错审批。

Demo 数据通过 `scholargraph-demo-v1` 明确标记为 synthetic。页面与其他入口必须保留 `synthetic`、`dataset_version`、事实类别、审核状态和对象版本，不能把演示对象表述为学校真实学者。
