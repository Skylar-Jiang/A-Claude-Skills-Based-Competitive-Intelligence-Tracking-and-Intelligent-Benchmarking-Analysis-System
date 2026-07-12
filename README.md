# 基于 Claude Skill 的竞品动态追踪与智能对标分析系统

当前版本以后端为核心，已用少量真实、公开、可追溯的数据跑通：

```text
农业农村部公开日度报告
  -> 专用解析与 raw 保存
  -> 清洗、公开 URL 校验、去重与 processed 保存
  -> LangChain 分块 + Hugging Face embedding + Chroma
  -> 带原文/来源/链接/发布时间的检索
  -> LangChain RunnableSequence 结构化分析
  -> FastAPI / Swagger / Markdown + JSON 报告
```

当前业务边界是全国农产品批发市场日度动态，重点验证黄瓜及蔬菜价格涨跌信号。现有区域供应源手工 CSV 只作为 sample，不进入正式知识库；当前不开发前端，不声称具备区域成交价、大规模全网采集或生产部署能力。

## 真实数据

- 来源：农业农村部市场与信息化司、中国农业农村信息网。
- 数量：8 条，发布日期覆盖 2026-01-05 至 2026-06-18。
- raw：`data/raw/real/agri_daily_wholesale_reports.csv`。
- processed：`data/processed/intelligence_records.csv`。
- 字段：标题、正文、来源名称、原始链接、发布时间、采集时间、分析对象、维度、稳定记录 ID。
- 重复采集：第一次新增 8 条，第二次新增 0 条、识别重复 8 条。

完整说明见 `docs/数据源与采集说明.md`。

## 安装与配置

推荐 Python 3.12，并使用仓库现有虚拟环境或新建环境：

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

真实模型使用 OpenAI-compatible 配置：

```text
OPENAI_API_KEY=<key>
OPENAI_BASE_URL=https://api.deepseek.com/v1
MODEL_FAST=<可用模型>
MODEL_ANALYSIS=<可用模型>
MODEL_REPORT=<可用模型>
RAG_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
```

Key 缺失时真实分析返回 503，不会降级成 Mock。正式接口 `/analysis/run` 默认 `mode=real`，只有显式传入 `mode=mock` 才使用 Mock；历史 Skill 兼容接口仍默认 `provider=mock`，其响应会明确标注 Mock，正式调用需显式传入 `provider=openai`。

## 运行主链

启动服务：

```powershell
$env:COLLECTION_SCHEDULER_ENABLED="false"
.\venv\Scripts\python.exe -m uvicorn modules.api_server:app --host 127.0.0.1 --port 8000
```

Swagger：`http://127.0.0.1:8000/docs`

推荐顺序：

1. `GET /sources` 查看真实数据源。
2. `POST /collect/run?force=true&use_llm_filter=false` 采集；结果中的 `errors` 和 `fetch_errors` 必须为空才是全成功。
3. `GET /records` 查看清洗后的真实记录。
4. `POST /rag/rebuild` 重建 Chroma。
5. `GET /rag/search?query=黄瓜价格涨跌%20农产品批发价格200指数` 检索证据。
6. `POST /analysis/run`，传 `mode=real` 做正式分析，或显式传 `mode=mock` 只验证结构。
7. `POST /report/generate` 使用兼容 Skill 报告入口；已生成报告可从 `GET /reports` 查询。

正式分析请求示例：

```json
{
  "competitor": "全国农产品批发市场",
  "question": "基于公开日度报告分析黄瓜价格涨跌信号，并明确证据日期与局限",
  "mode": "real",
  "top_k": 5
}
```

## 测试

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe tests_local.py
.\venv\Scripts\python.exe -m compileall -q main.py modules tests
```

2026-07-12 最终门禁：28 个新增单元/集成测试全部通过，原有回归脚本通过，编译通过，Uvicorn 健康接口与 Swagger 均通过。TestClient 会显示 Starlette/httpx 弃用警告，不影响本次结果，已列为依赖升级事项。

## 文档

- `docs/现状审计报告.md`
- `docs/当前阶段边界与后续扩展.md`
- `docs/后端架构与模块边界.md`
- `docs/数据与接口约定.md`
- `docs/数据源与采集说明.md`
- `docs/API接口文档.md`
- `docs/测试报告.md`
- `docs/项目交接文档.md`
