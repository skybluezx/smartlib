# SmartLib Web

SmartLib 智能知识平台的 Web 入口。它已经进入最终系统的正式仓库结构，但当前页面仍使用明确标注的演示数据；后续将按技术决策逐步接入统一能力 API，不再在页面内扩展新的业务数据实现。

## 已实现工作区

- 平台总览
- 学者星图 ScholarGraph
- 知源智研 ResearchNavigator
- 学科罗盘 DisciplineCompass
- 成果智桥 InnovationBridge
- 知识基础设施
- 治理与许可

## 本地开发

```bash
npm install
npm run dev
```

生产构建：

```bash
npm run build
```

## 容器运行

从仓库根目录执行：

```bash
docker compose -f infra/compose/compose.yaml up --build -d
```

默认容器地址为 `http://localhost:18080`，健康检查地址为 `http://localhost:18080/healthz`。本地 Vite 开发服务仍默认使用 `http://localhost:5173`。

当前边界：Web 是 SmartLib 多入口体系中的一个渠道。开放 API、MCP、Skill、Agent、小程序和客户端将在统一能力契约上逐项建设，不能直接依赖本目录中的演示数据。
