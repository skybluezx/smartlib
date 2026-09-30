# MinIO Community 本地对象存储

该目录提供 SmartLib Demo 使用的 MinIO Community 源码构建镜像和幂等初始化程序。

- 源码固定为 MinIO 官方仓库最后提交 `7aac2a2c5b7c882e68c1ce017d8256be2feea27f`；
- 镜像内保留上游 `LICENSE` 和 `SOURCE_REF`；
- 数据写入 Compose 命名卷 `smartlib-minio`，重建容器不会删除对象；
- `minio-init` 自动创建 `smartlib-publications` 桶并开启版本控制；
- 初始化可重复执行，不删除、不覆盖已有对象。

本配置适用于本地开发和 Demo。上游 Community 仓库已经停止维护，正式生产前应重新完成安全、许可、升级、备份和高可用评估。

## 地址

- S3 API：`http://localhost:19000`
- 管理控制台：`http://localhost:19001`

登录账号和密码读取 Compose 环境中的 `SMARTLIB_MINIO_ROOT_USER`、`SMARTLIB_MINIO_ROOT_PASSWORD`。`.env.example` 只提供占位符，实际密码由私有 `.env.local` 或密钥管理提供。

## 论文全文入库

日常使用不需要登录 MinIO 控制台。在论文核验页面打开一条已关联论文，选择“录入后续信息”→“全文文件”，即可上传 PDF：

- Web 只负责选择文件，不要求人工填写对象地址、文件类型或校验码；
- Platform API 校验 PDF 格式和大小，计算 SHA-256，并按论文与内容摘要生成稳定对象路径；
- 文件写入 `smartlib-publications` 桶后，PostgreSQL 登记受控 `s3://` 地址、大小、校验值和补充证据；
- 同一内容重复提交时复用已有对象；数据库登记失败时，API 会回滚本次新建的对象版本；
- 新增全文沿用论文增量补充机制，保留历史记录并触发后续核验状态更新。

默认仅接收 PDF，单文件上限为 100 MiB，可通过 `SMARTLIB_FULLTEXT_MAX_BYTES` 调整。HTTP 接口为
`POST /api/v1/knowledge-hub/publications/{publication_id}/fulltext`，需要
`publication_supplement.submit` 权限。

### 受控批量任务

批量任务固定读取 `outputs/2026_nsf_fulltext_download/manifest.json` 与其正式 `PDF/`
目录。`.download_cache` 不会被扫描。先运行匹配预检：

```bash
docker compose --env-file infra/compose/.env.local -f infra/compose/compose.yaml \
  --profile controlled-import run --rm controlled-fulltext-match
```

预检通过后执行上传、文本层解析、必要时 OCR 和结构化提取：

```bash
docker compose --env-file infra/compose/.env.local -f infra/compose/compose.yaml \
  --profile controlled-import run --rm controlled-fulltext-ingestion
```

两步报告分别写入 `data/fulltext-ingestion/match-report.json` 和
`data/fulltext-ingestion/ingestion-report.json`。任务按内容校验码幂等，可安全重跑。
