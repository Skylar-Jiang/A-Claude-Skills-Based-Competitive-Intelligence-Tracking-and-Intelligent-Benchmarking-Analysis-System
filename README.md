# 生鲜电商竞品动态追踪与价格舆情分析系统

本项目基于现有 Skill + Agent + RAG + FastAPI + 报告生成架构，研究对象切换为生鲜电商竞品分析。系统面向盒马、叮咚买菜、美团买菜、朴朴超市、京东七鲜、永辉生活、山姆会员店、京东生鲜等平台，监控肉蛋奶、基础蔬菜、水果、水产、预制菜等日常生鲜商品的价格波动、促销变化、新品/节令上架和负面舆情。

## 为什么选择生鲜电商

- 生鲜价格每天变化明显，适合验证价格监控与时序分析。
- 肉蛋奶、蔬菜、水果是高频消费品，生活贴近、业务价值高。
- 生鲜平台竞争集中在价格、促销、履约、品质和售后，适合验证多 Agent 分析。
- 系统可优先使用公开价格信息、开放平台、行业媒体和手工 CSV 舆情样例，不绕过登录、验证码和反爬。

## 数据源

默认配置文件：

```text
config/sources.yaml
```

数据源类型：

- 政府/行业价格公开页面：全国农产品批发市场价格信息、商务部食用农产品价格信息。
- 平台价格与促销手工 CSV：盒马、叮咚买菜、美团买菜、京东生鲜等。
- 行业媒体手工 CSV：供应链、门店扩张、即时零售竞争。
- 社交与投诉舆情手工 CSV：知乎、小红书、微博、黑猫投诉、应用商店评论等公开样例。

知乎、小红书、微博等平台默认采用 `manual_csv` 手工导入公开样例，不写绕过登录、验证码、反爬、App 抓包的代码。生鲜平台 App 数据可通过授权 API 或手工 CSV 接入。

## 快速运行

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Swagger：

```text
http://127.0.0.1:8000/docs
```

默认 LLM Provider 使用 OpenAI-compatible 协议。`.env` 可以直接配置 DeepSeek 官方兼容网关：

```text
OPENAI_API_KEY=<你的 DeepSeek Key>
OPENAI_BASE_URL=https://api.deepseek.com/v1
MODEL_FAST=deepseek-v4-flash
MODEL_ANALYSIS=deepseek-v4-pro
MODEL_REPORT=deepseek-v4-pro
```

这三个模型变量不要合并：`fast` 用于轻量抓取/清洗/分类，`analysis` 用于结构化竞品分析，`report` 用于报告生成。可以按 DeepSeek 账号实际可用模型分别配置。

RAG 默认使用 Hugging Face `BAAI/bge-m3` + Chroma。首次真实重建向量库时会下载模型；如果网络不稳定，可以在 `.env` 中保留 `HF_ENDPOINT=https://hf-mirror.com` 或改成可用镜像。

## 推荐演示顺序

1. `GET /sources`：查看生鲜数据源。
2. `POST /ingest/csv`：导入任一手工 CSV，例如 `data/raw/hema_price_manual.csv`。
3. `POST /rag/rebuild`：重建 Chroma 生鲜知识库。
4. `GET /rag/search`：查询 `盒马 鸡蛋 牛奶 番茄 价格 促销 舆情`。
5. `GET /skills`：查看 Skill 列表。
6. `POST /analyze/multi-agent`：运行生鲜多 Agent 分析。
7. `POST /report/generate`：生成生鲜竞品报告。
8. `GET /reports`：查看报告列表。
9. `GET /logs/skill-trace`：查看 Skill 调用记录。

更完整的阶段边界、验收接口和剩余风险见：

```text
docs/任务边界与验收总说明.md
docs/接口说明.md
```

`/analyze/multi-agent` 示例：

```json
{
  "competitor": "盒马",
  "query": "分析盒马近期肉蛋奶和基础蔬菜的价格变化、促销活动和负面舆情",
  "dimensions": ["price", "product", "sentiment", "trend"],
  "report_type": "weekly",
  "provider": "mock",
  "date_range": {
    "start": "2026-07-01",
    "end": "2026-07-06"
  }
}
```

## 架构说明

原有通用架构保持不变，只替换业务场景：

```text
公开数据/手工 CSV
  -> 数据清洗与分块
  -> Chroma RAG 知识库
  -> 价格 / 新品 / 舆情 / 趋势 Skill
  -> orchestrator_skill 多 Agent 汇总
  -> 生鲜竞品报告生成
  -> FastAPI + Swagger 演示
```

默认 `provider=mock`，不依赖真实模型 Key；如果切换 `provider=openai` 或调用 `/analyze`，系统会使用 `.env` 中的 OpenAI-compatible 配置。
