# 馆务入库和修订

下列命令均接在 `项目Python <SKILL>/scripts/hub.py` 后：

```sh
library-catalog
library-import --file /绝对路径/工作表.zip --mode real
library-import --file /绝对路径/工作表.zip --mode real --apply --reason '按用户要求导入本馆业务台账'
library-list --mode real --category reader_training --year 2025
library-detail --id <记录UUID>
library-report --mode real --year 2025
```

CSV、XLSX、ZIP 限制20 MB；类型和字段从实时 `library-catalog` 读取。模糊文件名可用 `--category <类型code>` 指定。XLSX 按服务端选择“总表”等业务工作表，不能套用论文“首表”的规则。`real` 为正式台账，`demo` 为模拟数据；不得把模拟值放入正式用途。当前25类仅是基线，以实时目录为准。

`library-import` 不带 `--apply` 只创建服务端预检，不写业务台账。带 `--apply` 时自动预检、提交、回读批次状态/数量。预检错误整批阻断；日期不全、人数无法解析等警告保留原值和缺失，不填0。回执保留预检和实际入库批次两个 ID（重复文件可能复用旧批次）。

已有预检 ID 可以安全继续：

```sh
library-commit --id <预检批次UUID> --apply --reason '继续已授权的馆务导入'
```

后台 commit 幂等，超过24小时且尚未提交的预检需重做。相同文件重复提交复用原批次；换文件但含已有台账完全相同事项时整批冲突，不静默跳过。不要以新文件名或输出目录绕过重复检查。

## 有依据的修订

先 `library-detail` 取得完整字段、用途、版本；再创建补丁 JSON，仅写待改原始字段。例如 `{"听众人数":"42"}`。

```sh
library-revise --id <记录UUID> --base-version 1 --patch /绝对路径/patch.json --reason '依据已确认签到汇总修正人数'
library-revise --id <记录UUID> --base-version 1 --patch /绝对路径/patch.json --reason '依据已确认签到汇总修正人数' --apply
```

脚本保留未修改字段、类型、用途及状态。版本不符就停止，不能取最新版本后强行重放旧补丁。只能依据用户或来源证据修正，不能把预警消失当治理目的。该命令不提供撤回、改用途、删除入口。

## 分析

`library-report` 和 `library-list` 共用 `--mode`、`--category`、`--year`、`--department`、`--q`。列表自动分页读取；报告使用服务端聚合。事项数≠绩效，人数合计≠去重读者数；不同业务人数口径不能相加。空年度/人数保留缺失。统计仅覆盖当前身份可见记录，不表述为全馆完整统计。报告不默认导出敏感人员明细。

“系统预警记录”只包括后端当前配置的时间、人数等检查，不是全字段完整性结果。用户要求检查缺失时，继续读取实时目录与 `library-list` 的全部分页，按业务类型、字段统计空值；区分必填缺陷、可补充空值、不适用与合法精度（例如出版年只有年份）。不得为了消除预警编造月日，不能把不适用字段当缺陷。按年份筛选会排除无法归年的记录，范围内日期缺失0不代表全库无缺失。
