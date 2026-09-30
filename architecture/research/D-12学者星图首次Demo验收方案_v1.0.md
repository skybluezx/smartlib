# D-12 学者星图首次 Demo 验收方案 v1.0

- 状态：执行中；SG-01 数据与公共读模型、SG-02 真实 Web 切片已通过，SG-03 待执行
- 日期：2026-08-26
- 对象：`scholargraph-demo-v1`、Scholar 公共能力、PostgreSQL/OpenSearch/HugeGraph、React `/scholars`

## 1. 必须贯通

1. synthetic manifest 和幂等 seed 生成固定对象、来源、证据与关系；
2. 学者目录、关键词/院系/方向筛选只读取公共 API；
3. 学者详情展示事实画像、代表成果、项目、方向和可见统计口径；
4. 学者网络展示成果、项目、方向、机构和合作者关系；
5. 关系或方向可追溯到 evidence、source、observed time 和 dataset version；
6. PostgreSQL/HugeGraph 与 PostgreSQL/OpenSearch 的可见业务结果一致；
7. 页面正确处理加载、空、失败、无权限和投影不可用；
8. synthetic、事实/分析类别和未接入真实系统的边界明确可见。

## 2. 绝对门槛

- 页面仍读取 `scholars` 或 `evidenceItems` fixture；
- 页面指标与 PostgreSQL 可见事实不一致；
- 关系无证据却显示固定“高可信”说明；
- 隐藏节点、边、证据、计数或路径存在性泄漏；
- HugeGraph/OpenSearch 不可用时静默显示硬编码成功结果；
- synthetic 学者被表述为学校真实人员；
- 事实、分析和推断没有类别或审核状态；
- 未实现的比较、纠错、导出按钮显示成功提示；
- 浏览器或未来入口可提交 Cypher、DSL 或任意查询脚本；
- Demo mode 关闭后回退到前端 fixture。

## 3. 数据验收

| 项目 | 门槛 |
|---|---:|
| synthetic 学者 | 6 |
| 院系 | 4 |
| 学科 | 3 |
| 研究主题 | 6 |
| 代表成果 | 12 |
| 项目 | 6 |
| 对象/关系证据 | ≥30 |
| 关系 | ≥45 |
| 跨院系合作路径 | ≥1 |
| 低置信度或待确认分析关系 | ≥1 |
| 幂等 seed 重跑新增记录 | 0 |

## 4. 自动化与运行证据

- 数据库约束、RLS、幂等 seed、Outbox 和引用完整性测试；
- Scholar service 对事实/分析分层、计数、空值和证据过滤的单元/集成测试；
- OpenAPI operation ID、能力目录和生成客户端无漂移；
- PostgreSQL/HugeGraph 邻域及路径对照；
- PostgreSQL/OpenSearch 搜索结果与过滤对照；
- React 组件测试和 `/scholars` 浏览器 E2E；
- `SMARTLIB_WEB_DEMO_MODE=true/false` 双模式验证；
- Compose 冷启动、投影重建与后端不可用降级演练。

### SG-02 已取得的运行证据

- `/scholars` 不再导入学者 fixture 或受 `DemoBoundary` 控制；
- 公共编号 `SL-DEMO-0001` 可直接读取画像、网络和证据，内部 UUID 不再成为入口契约；
- Web 组件与架构测试共 9 项通过，生成客户端无漂移，严格类型、lint 和生产构建通过；
- 容器浏览器验证真实搜索、事实画像、PostgreSQL 图投影、证据抽屉、明暗主题、390px 移动端和 axe 无障碍；
- `VITE_SMARTLIB_DEMO_MODE=false` 独立构建与同一浏览器脚本通过，没有 fixture 回退；
- 当前浏览器运行已切换 HugeGraph 图投影；PostgreSQL/HugeGraph 一跳网络已经逐 ID 对照一致。OpenSearch 对照、冷启动和故障降级仍在 SG-03 验收。

## 5. 演示验收脚本

1. 从首页进入学者星图，看到明确 synthetic 提示；
2. 输入研究主题，筛选到相关学者；
3. 打开一位学者，解释事实画像和直接计算指标；
4. 打开代表成果/项目，展示方向依据；
5. 切换合作网络，发现跨院系合作者；
6. 点击一条关系，展示来源、证据、版本和审核状态；
7. 说明同一能力未来可由 API、MCP、Skill、小程序和客户端复用；
8. 明确当前未接入学校真实系统、未作人才评价结论。
