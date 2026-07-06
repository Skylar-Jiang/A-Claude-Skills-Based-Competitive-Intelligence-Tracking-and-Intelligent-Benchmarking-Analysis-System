# Claude Skill Competitor Intelligence System

基于 Claude Skill 的竞品动态追踪与智能对标分析系统实战。

## Day 1 环境搭建

本项目使用 Python 3.12 和项目内虚拟环境 `venv`，依赖统一写入 `requirements.txt`。

### Windows PowerShell

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

如果 PowerShell 无法激活虚拟环境，可按老师文档提示以管理员身份执行：

```powershell
Set-ExecutionPolicy RemoteSigned
```

### 配置密钥

复制 `.env.example` 为 `.env`，填写对应平台的 Key。

默认先使用 DeepSeek 做低成本测试，后续切换 GPT 时仍使用同一套 OpenAI-compatible 配置：

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_FAST=deepseek-v4-flash
MODEL_ANALYSIS=deepseek-v4-pro
MODEL_REPORT=deepseek-v4-pro
```

三个模型配置对应老师的分层规范：`MODEL_FAST` 用于抓取、清洗、关键词提取；`MODEL_ANALYSIS` 用于结构化分析和竞品对标；`MODEL_REPORT` 用于复杂推理和报告生成。

正式使用 GPT 时，将 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_FAST`、`MODEL_ANALYSIS`、`MODEL_REPORT` 改为对应服务商配置即可。

### 连通性测试

```powershell
python test_llm.py
```

如果 `.env` 中没有填写 Key，脚本会提示需要补充配置，不会发起模型请求。
