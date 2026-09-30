# ADR-0013：以 HugeGraph 替换 Neo4j 图投影

- 状态：已接受并实施
- 日期：2026-09-01
- 决策人：项目负责人
- 关联编号：D-05
- 取代：ADR-0006 中的 Neo4j POC 产品选择

## 决策

SmartLib 的专用图投影由 Apache HugeGraph 1.7.0 实现，不再部署、调用或新增 Neo4j 组件。
PostgreSQL 18 继续保存知识对象、关系断言和证据的权威状态，HugeGraph 只保存可重建投影。

公共 API 继续通过 `GraphPort` 提供邻域、有限路径和关系解释能力，不向 Web、MCP、Skill、
Agent 或其他客户端暴露 Gremlin、HugeGraph REST API 或存储凭据。

## 实施边界

- 固定 HugeGraph 1.7.0 单机 RocksDB 镜像用于当前 Demo 和开发验证；
- 使用认证、内部 Compose 网络、独立持久卷和版本化 Schema 初始化；
- Transactional Outbox 使用新的 `hugegraph_graph` 回执名称完整重放历史对象和关系；
- 图查询在 HugeGraph 侧执行节点、边和中间路径的可见性过滤，应用服务继续执行越界后验；
- 保留 PostgreSQL 图适配器作为正确性基线和故障诊断工具；
- Neo4j 容器、卷、配置、适配器、投影 writer 和运行测试全部移除；历史 ADR 和旧 migration
  中的 Neo4j 名称只作为已经发生过的工程历史保留。

## 后果

HugeGraph 成为当前唯一专用图数据库。服务器正式部署仍需补齐备份恢复、容量曲线、认证密钥
管理、漏洞扫描和单机故障恢复验证；在这些门槛完成前，不把当前单机 RocksDB 形态表述为
生产高可用集群。
