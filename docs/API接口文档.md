# API 接口文档

Swagger：`GET /docs`。若 `.env` 设置 `APP_API_KEY`，业务接口需要请求头 `X-API-Key`。

统一错误格式：

```json
{"success": false, "error": {"code": "llm_not_configured", "message": "..."}}
```

## 核心正式接口

### GET `/`

健康检查。返回 `{"status":"ok"}`；不调用网络或模型。

### GET `/sources`

返回数据源配置，包括 `source_id`、`source_type`、`urls`、开关、关键词和采集频率。不调用模型。首次运行读取 YAML 默认值；通过数据源 CRUD 修改后读取运行期 JSON，删除和 `last_run_at` 可跨请求保留。

### POST `/collect/run`

查询参数：`force=true`、`use_llm_filter=false`。触发真实网络采集；响应包含每个源的 raw/new/duplicate/rejected 计数、`fetch_errors` 和总 `errors`。公开源失败不会返回虚假样例。

### GET `/records`

参数：`competitor`、`dimension`、`offset`、`limit`。返回 processed 中的真实记录，包含来源名称、原始链接、发布时间和采集时间。不调用模型或网络。

### POST `/rag/rebuild`

以正式 processed 记录重建 Hugging Face + Chroma 知识库。返回 chunk 数、collection 和 embedding 配置。首次可能下载 embedding 模型。

### GET `/rag/search`

参数：`query`、`dimension`、`competitor`、`top_k`。返回 `text`、`source_name`、`source_url`、`published_at` 等证据字段。不调用生成模型。

### POST `/analysis/run`

正式统一分析入口。

```json
{
  "competitor": "全国农产品批发市场",
  "question": "基于公开报告分析黄瓜价格涨跌",
  "mode": "real",
  "top_k": 5
}
```

- `mode=real`：使用 RAG + LangChain RunnableSequence + 真实 OpenAI-compatible 模型。配置缺失返回 503，模型/解析失败返回 502，不回落 Mock。
- `mode=mock`：不调用真实模型，响应包含 `mode=mock`、`mock=true`。
- 无证据：不调用模型，返回 `insufficient_evidence=true` 和补充数据建议。

### POST `/report/generate`

兼容 Skill 报告入口，请求为 `SkillRunRequest`。历史兼容接口默认 `provider=mock` 且响应明确标注 Mock；`provider=openai` 才调用真实模型。报告文件可从 `GET /reports` 查询和 `/reports/{name}/preview` 预览。

## 采集/导入兼容接口

- `POST /ingest/csv`：真实可追溯 CSV 可进入 processed；虚拟/缺字段 CSV 只进入 samples，返回 `indexed=false`。
- `POST /ingest/manual`：仅 sample，不进入正式 RAG。
- `POST /ingest/webpage`、`POST /ingest/rss`：保留通用兼容入口；当前正式演示优先使用专用 `agri_daily` 采集。

## 分析兼容接口

- `POST /analyze`：旧 Agent 入口，默认真实模型，计划迁移到 `/analysis/run`。
- `POST /analyze/multi-agent`：Skill Orchestrator 兼容入口，默认 `provider=mock`；正式调用必须显式传入 `provider=openai`。
- `POST /skills/{skill_name}/run`：单 Skill 兼容入口。
- `GET /agents`、`GET /skills`、`GET /skills/{skill_name}`：能力查询。

## 其他保留接口

- 数据源：`POST /sources`、`DELETE /sources/{source_id}`。
- 日志：`GET /collect/logs`、`GET /logs/skill-trace`、`GET /traces`。
- Memory：`GET|POST|DELETE /memory/conversations/{session_id}`、`DELETE /memory/cache`。
- 报告调度：`GET|POST /report-schedules`、`POST /report-schedules/{schedule_id}/run`。
- 历史与看板：`GET /reports`、`GET /dashboard/summary`、`GET /dashboard/comparison`、`GET /dashboard/risk-tags`。
