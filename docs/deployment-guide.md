# TradePilot 私有共享测试环境部署手册

本文只覆盖 Vercel 前端 Preview 与 Railway 后端 staging。不要 Promote 为 Production，不绑定自定义域名，也不要把占位符当成测试地址。

## 1. 仓库与运行方式

| 项目 | 目录 | 技术栈 | 安装 | 启动 | 构建/检查 |
| --- | --- | --- | --- | --- | --- |
| 后端 | 仓库根目录 | Python 3.12、FastAPI、Uvicorn、SQLAlchemy/Alembic、SQLite、Chroma | `python -m pip install -r requirements.txt` | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` | `python -m pytest`、`python -m ruff check .` |
| 前端 | `frontend` | React 19、TypeScript 6、Vite 8 | `npm ci` | `npm run dev` | `npm run lint`、`npm run build`，产物为 `dist` |

前端只通过 `VITE_API_BASE_URL` 获取后端 `/api/v1` 地址。访问码绝不能放入 `VITE_*`；浏览器首次进入时由成员输入。

## 2. 访问控制与共享工作区

- `/api/v1/health` 是唯一匿名应用接口，Railway 健康检查不调用模型。
- 其他 `/api/v1/*` 路由统一要求 `Authorization: Bearer <access-code>`。缺失或错误均返回 401，不回显正确值。
- `APP_API_KEY` 在 staging/production 必填；缺失时应用拒绝启动。真实值只手工写入 Railway Variables。
- staging/production 的 `/docs`、`/redoc` 和 `/openapi.json` 关闭。开发环境可保留文档，但文档页面不能绕过业务接口鉴权。
- CORS 与 Trusted Host 只限制浏览器来源和 Host，不是认证替代品。
- 前端验证通过后把访问码保存到当前标签页的 `sessionStorage`，所有业务请求自动附加 Bearer。收到 401 或点击“退出演示环境”时只清本地凭证，不删除服务器数据。
- 当前没有账户、注册、用户表或 `user_id` 隔离。商品、Agent Run、Conversation、Memory、Report、Upload、公共 RAG 与 Chroma 都属于同一个 `shared_demo` 工作区，任何获准成员都可能看到或影响其他成员的数据。

`sessionStorage` 可被同源 XSS 或恶意浏览器扩展读取，因此后端鉴权、HTTPS、CSP、无第三方脚本和访问码轮换仍是实际边界。共享码泄露后应立即在 Railway 轮换并重新部署。

## 3. Railway 后端 staging

1. 新建 Railway Project 和 `staging` Environment，从 GitHub 导入当前分支。
2. Service Root Directory 留空（仓库根），Config as Code 使用 `/railway.json`。
3. Builder 为 Railpack；启动命令为 `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`；健康检查为 `/api/v1/health`。
4. Replica 数量固定为 `1`。SQLite、Chroma 和进程内准入锁均不支持这个阶段的多副本语义。
5. 创建一个 Railway Volume，Mount Path 精确填写 `/data`。不要删除或 Wipe Volume 来重置演示数据。
6. 在 Variables 中填写下表。不要手工设置 `PORT`。
7. 首次发布后只生成 Railway 提供的 staging domain；不要添加 Custom Domain。

### Railway Variables

| 名称 | staging 值/规则 |
| --- | --- |
| `APP_ENV` | `staging` |
| `APP_DEBUG` | `false` |
| `APP_API_KEY` | 手工生成的高熵共享访问码；必填、Secret |
| `CORS_ALLOWED_ORIGINS` | 实际 Vercel Preview origin；多个用逗号分隔；不带路径、不用 `*` |
| `TRUSTED_HOSTS` | `healthcheck.railway.app,*.up.railway.app,*.railway.internal` |
| `DATABASE_URL` | `sqlite:////data/tradepilot.db` |
| `CHROMA_DIR` / `CHROMA_PERSIST_DIR` | `/data/chroma` |
| `UPLOAD_DIR` | `/data/uploads` |
| `REPORT_DIR` | `/data/reports` |
| `DEMO_BACKUP_DIR` | `/data/backups` |
| `RAG_MANIFEST_PATH` | `/data/index-manifest.sqlite` |
| `PEER_CACHE_DIR` | `/data/peer-cache` |
| `TRADE_TARIFF_DB_PATH` | `/data/tariff-rules.sqlite` |
| `PEER_METADATA_PATH` | `data/filtered/meta_pet_supplies_prefiltered.jsonl` |
| `PEER_REVIEWS_PATH` | `data/filtered/pet_supplies_reviews_prefiltered.jsonl` |
| `PEER_MATCH_CONFIG_PATH` | `config/peer_matching.yaml` |
| `TRADE_HS_MAPPING_PATH` | `config/trade/hs_mapping.yaml` |
| `DEFAULT_DATA_MODE` | `demo`，完成真实数据和模型校验前不要改为 `real` |
| `RAG_USE_CHROMA` | 按实际索引准备情况设置；真实模式通常为 `true` |
| `RUN_WORKER_COUNT` | 推荐 `1` |
| `ANALYSIS_MAX_ACTIVE_RUNS` | 推荐 `1` |
| `ANALYSIS_RATE_LIMIT_REQUESTS` | 推荐 `3` |
| `ANALYSIS_RATE_LIMIT_WINDOW_SECONDS` | 推荐 `60` |
| `LOG_LEVEL` | `INFO` |
| 模型、Embedding、Rerank 密钥 | 只放 Railway Secret；不得放 Git、日志或前端变量 |

准入保护只对被接受的分析启动计数：同一商品存在 pending/running 任务时返回 409；共享工作区达到活跃任务上限或速率上限时返回 429。单进程锁与单副本配置共同防止并发创建；`RUN_WORKER_COUNT=1` 限制实际后台模型工作数。重启时最多恢复 `ANALYSIS_MAX_ACTIVE_RUNS` 个 pending 任务。

### 3.1 真实分析的 Railway 前置项

前后端、共享访问码和 health 已连通并不代表 real mode 已准备完成。real 请求在进入后台队列前还会检查模型、Chroma、Embedding、Git LFS 源文件和 peer SQLite cache。混合 provider 的最小配置为：

```env
RAG_USE_CHROMA=true
EMBEDDING_MODEL=text-embedding-v4
PEER_CACHE_DIR=/data/peer-cache
RAG_MANIFEST_PATH=/data/index-manifest.sqlite
TRADE_TARIFF_DB_PATH=/data/tariff-rules.sqlite
PEER_METADATA_PATH=data/filtered/meta_pet_supplies_prefiltered.jsonl
PEER_REVIEWS_PATH=data/filtered/pet_supplies_reviews_prefiltered.jsonl
```

并同时设置非空的 `DEEPSEEK_API_KEY`、`QWEN_API_KEY`、`MODEL_ANALYSIS`、`MODEL_FAST`、`MODEL_REPORT`、`MODEL_VISION`。真实值只放 Railway Variables；不要放入命令、日志或前端变量。若访问码或模型密钥曾出现在聊天、工单或终端历史中，先在对应平台轮换，再重新部署。

当前路由不依据模型名字猜 provider：`MODEL_ANALYSIS` 使用 DeepSeek；当 Qwen 凭证存在时，`MODEL_REPORT`、`MODEL_FAST` 使用 Qwen，视觉始终使用 Qwen；`text-embedding-*` 使用 Qwen-compatible Embedding。`real_model_configured` 只表示四个文本 Agent 的模型入口可构造，不替代 RAG、Embedding 和数据检查。

在挂载 `/data` 的运行中 Railway service shell 里执行以下只读检查。输出只包含变量是否非空以及文件状态，不打印密钥：

```bash
python - <<'PY'
import os
from pathlib import Path

for name in (
    "DEEPSEEK_API_KEY", "QWEN_API_KEY", "DEEPSEEK_BASE_URL", "QWEN_BASE_URL",
    "MODEL_ANALYSIS", "MODEL_FAST", "MODEL_REPORT", "MODEL_VISION",
    "EMBEDDING_MODEL", "RAG_USE_CHROMA",
):
    print(f"{name}: {'set' if os.getenv(name, '').strip() else 'missing'}")

for value in (
    "data/filtered/meta_pet_supplies_prefiltered.jsonl",
    "data/filtered/pet_supplies_reviews_prefiltered.jsonl",
):
    path = Path(value)
    pointer = path.is_file() and path.read_bytes()[:128].startswith(
        b"version https://git-lfs.github.com/spec/v1"
    )
    print(f"{value}: exists={path.is_file()} size={path.stat().st_size if path.is_file() else 0} lfs_pointer={pointer}")
PY
```

两个源文件必须 `exists=True`、size 大于 LFS pointer 大小且 `lfs_pointer=False`。若仍是 pointer，应先让部署构建取得 Git LFS 实体；不要用 pointer 构建 cache。随后在同一个已挂载 Volume 的运行环境中显式准备可复用 cache：

```bash
python scripts/prepare_peer_data.py \
  --metadata-input data/filtered/meta_pet_supplies_prefiltered.jsonl \
  --reviews-input data/filtered/pet_supplies_reviews_prefiltered.jsonl \
  --cache-dir /data/peer-cache

python scripts/import_us_hts_tariffs.py \
  --input data/raw/us_hts_2026_rev11.csv \
  --normalized-output /data/us_hts_tariffs.jsonl \
  --database-output /data/tariff-rules.sqlite
```

这些命令不会删除 `/data`、业务 SQLite 或已有 Chroma。online real workflow 会把每次选中的 peer 文档写入 `/data/chroma`，因此首次 real run 不要求预先重建全量 Chroma；`RAG_MANIFEST_PATH` 只由显式批量 RAG 索引 CLI 使用。若指定 `us-tariff-provider` 而 tariff 数据尚未准备，运行结果会记录 `background_provider_unavailable` data gap，不再静默伪装为已有背景数据。

变量和 cache 准备完成后再启动一个最小 real run，检查：创建接口返回 202；timeline 依次进入 peer matching、RAG 和四个 Agent 节点；四个 Agent 均为 production 且 `real_model_called=true`；provider/model_name 分别对应当前配置；报告可读取。任何失败都应在 timeline 的失败节点和 Railway 日志中定位，且 `fallback_used=false`。在确实拿到可访问报告前，不得宣称线上真实调用成功。

### 后端验证

以下命令中的地址必须替换为平台真实生成并已打开的 staging 地址。输入访问码时不要打印或写入脚本：

```powershell
$accessCode = Read-Host "Shared access code" -MaskInput
Invoke-WebRequest https://<railway-domain>/api/v1/health -UseBasicParsing
Invoke-WebRequest https://<railway-domain>/api/v1/workflow/metadata -SkipHttpErrorCheck -UseBasicParsing
Invoke-WebRequest https://<railway-domain>/api/v1/workflow/metadata -Headers @{ Authorization = "Bearer $accessCode" } -UseBasicParsing
Invoke-WebRequest https://<railway-domain>/openapi.json -SkipHttpErrorCheck -UseBasicParsing
Remove-Variable accessCode
```

预期依次为 200、401、200、404。还要确认 Alembic upgrade 成功、服务没有重启循环，且日志不包含访问码或模型密钥。

## 4. Vercel 前端 Preview

| Vercel 字段 | 精确值 |
| --- | --- |
| Repository | 同一 TradePilot 仓库和当前 staging 分支 |
| Root Directory | `frontend` |
| Framework Preset | `Vite` |
| Install Command | `npm ci` |
| Build Command | `npm run build` |
| Output Directory | `dist` |
| Node.js Version | `22.x` |
| Preview Variable | `VITE_API_BASE_URL=https://<railway-domain>/api/v1` |

`frontend/vercel.json` 提供 SPA fallback、CSP 和基础安全响应头。`VITE_API_BASE_URL` 是唯一需要的浏览器构建变量；不要创建任何包含访问码或服务端秘密的 `VITE_*` 变量。

Vercel 真实 Preview URL 生成后，把其完整 origin 加入 Railway `CORS_ALLOWED_ORIGINS` 并重新部署后端。浏览器终验应覆盖：访问页、错误码提示、正确码进入、刷新仍在当前会话、业务请求带 Authorization、模拟 401 自动返回访问页、退出按钮清凭证、关闭标签页后凭证消失。

## 5. 持久化边界

| 数据 | 路径 | 重置策略 |
| --- | --- | --- |
| SQLite 业务状态 | `/data/tradepilot.db` | 备份后按表清理；不删数据库文件、不降级 Alembic |
| Chroma / 公共 RAG | `/data/chroma` | 保留；需要时通过显式知识库流程重建 |
| 上传文件 | `/data/uploads` | 演示重置会备份后清空目录内容，保留目录和 Volume |
| 报告文件 | `/data/reports` | 演示重置会备份后清空目录内容 |
| 演示备份 | `/data/backups` | 保留；不要放入 uploads/reports 内 |
| Peer cache / manifest | `/data/peer-cache`、`/data/index-manifest.sqlite` | 保留 |
| Tariff 数据 | `/data/tariff-rules.sqlite` | 保留 |

两个 Git LFS 数据文件体积较大。只有确认 Railway 容器中不是 LFS pointer，并完成 peer cache 和模型供应商验证后，才可开放真实分析。Volume 在 build/pre-deploy 阶段不可用，数据准备必须在已挂载 Volume 的运行环境中显式执行。

## 6. 演示数据备份、重置和恢复

先停止成员操作并确认没有 pending/running 分析。所有 reset 命令默认 dry-run：

```powershell
python scripts/manage_demo_data.py plan
python scripts/manage_demo_data.py export
python scripts/manage_demo_data.py reset
python scripts/manage_demo_data.py reset --confirm RESET_SHARED_DEMO_DATA
python scripts/seed_demo.py --profile generic_cross_border_demo
```

确认 reset 会先创建 SQLite 在线备份，并复制 upload/report 文件到 `DEMO_BACKUP_DIR/<UTC timestamp>`，随后删除：所有运行、阶段、事件、Agent 输出、证据引用、报告、Conversation/Message、ProductFile，以及 `data_origin=user` 的商品与其商品级 offers/reviews/knowledge。最后清空配置的 uploads/reports 目录内容。

不会删除：`real`/`demo` 基础商品及其知识、公共知识库、Chroma、peer cache、manifest、tariff 数据、Alembic schema、环境变量、部署配置或 Railway Volume。存在活跃分析时确认 reset 会拒绝执行。预置案例恢复使用现有幂等 `seed_demo.py`；恢复整个共享记录则应从备份在维护窗口中人工恢复，而不是删除 Volume。

## 7. 回滚

- 代码回滚：`git revert <this-commit>` 后推送 staging 分支；不要改写共享历史。
- Railway：重新部署上一个成功 commit。代码回滚不会自动降级 schema，也不会删除 Volume 数据。
- Vercel：重新部署上一个成功 Preview；不要 Promote to Production。
- 数据回滚：先保留当前 `/data` 快照，再从 `DEMO_BACKUP_DIR` 中选择明确备份恢复 SQLite、uploads 和 reports。不要在运行中的 worker 写数据库时覆盖文件。

## 8. 上线前检查

- [ ] `.env` 与 `.env.*` 被 Git 忽略，只有 example 模板被跟踪；diff 中无真实密钥。
- [ ] Railway 已设置非空 `APP_API_KEY`，Vercel 没有访问码变量。
- [ ] `APP_DEBUG=false`、Replica=1、`RUN_WORKER_COUNT=1`，Volume 挂载到 `/data`。
- [ ] health 匿名 200；核心 API 未认证/错误码为 401；正确码为 200；staging OpenAPI 为 404。
- [ ] CORS 只包含实际 Preview origin，Trusted Hosts 与真实 Railway host 匹配。
- [ ] 前端 401 自动退出和手动退出均已验证，控制台和错误 UI 不显示访问码。
- [ ] 已接受单一共享工作区的数据可见性和互相覆盖风险。
- [ ] 未绑定自定义域名，未创建或提升正式生产部署。

在平台账号授权和实际部署完成前，前端 Preview URL 与后端 Railway URL 均为“未生成”。占位符不是可访问地址，也不得作为部署成功证据。
