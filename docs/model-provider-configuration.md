# Model Provider Configuration

Last updated: 2026-07-17

This document explains how to configure TradePilot real-mode model providers after the July 17, 2026 compatibility update.

## Summary

TradePilot now supports three practical real-mode setups:

1. `DeepSeek-only` for text analysis and report generation.
2. `DeepSeek + Qwen` for mixed-provider operation, especially when you want Qwen embeddings or Qwen vision.
3. `OpenAI-compatible` as a legacy fallback for text generation.

`real_model_configured` covers the four text-Agent entry points. A complete HTTP real run also requires `RAG_USE_CHROMA=true`, an explicit `EMBEDDING_MODEL`, prepared peer sources/caches, and any requested background dataset.

## Where to configure

Create or edit the ignored local file:

`F:\TradePilot\.env`

The application loads:

1. `.env`
2. `.env.<APP_ENV>`

`APP_ENV=development` means `.env.development` can override shared values.

## Option 1: DeepSeek-only

Use this when you want the simplest real-mode setup and do not want to depend on Qwen credentials.

Recommended configuration:

```env
APP_ENV=development

DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_BASE_URL=https://api.deepseek.com

QWEN_API_KEY=
OPENAI_API_KEY=
OPENAI_BASE_URL=

MODEL_ANALYSIS=deepseek-v4-flash
MODEL_FAST=deepseek-v4-flash
MODEL_REPORT=deepseek-v4-flash
MODEL_VISION=qwen3-vl-plus

EMBEDDING_MODEL=your_openai_compatible_embedding_model
RAG_USE_CHROMA=true
```

Notes:

- `MODEL_ANALYSIS`, `MODEL_FAST`, and `MODEL_REPORT` must all be set.
- Leave `QWEN_API_KEY` empty. Do not keep a placeholder string there.
- A deployed real run must not leave `EMBEDDING_MODEL` empty. The local hash embedding is limited to tests, CLI validation and offline development.
- A non-Qwen embedding model also requires the configured OpenAI-compatible embedding credentials. If those are unavailable, use the mixed DeepSeek + Qwen configuration below.
- If no candidate image is uploaded, image understanding is skipped and Qwen vision is not required.
- If you later upload candidate images and want real vision analysis, you still need a valid `QWEN_API_KEY`.

## Option 2: DeepSeek + Qwen

Use this when you want:

- DeepSeek for text agents
- Qwen embeddings
- Qwen vision
- the original mixed-provider setup

Recommended configuration:

```env
APP_ENV=development

DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_BASE_URL=https://api.deepseek.com

QWEN_API_KEY=your_qwen_key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

OPENAI_API_KEY=
OPENAI_BASE_URL=

MODEL_ANALYSIS=deepseek-v4-flash
MODEL_FAST=qwen3.6-flash
MODEL_REPORT=qwen3.7-plus
MODEL_VISION=qwen3-vl-plus

EMBEDDING_MODEL=text-embedding-v4
RAG_USE_CHROMA=true
```

Notes:

- Qwen placeholder text is not safe. A non-empty fake value will still be treated as configured and will fail later with `401 Unauthorized`.
- `text-embedding-v4` currently routes to the Qwen-compatible embedding endpoint.
- This setup is the right choice if you want real image understanding and Qwen embeddings.

## Option 3: OpenAI-compatible fallback

Use this only if you intentionally want to run against an OpenAI-compatible endpoint instead of DeepSeek.

Minimum text-only configuration:

```env
APP_ENV=development

OPENAI_API_KEY=your_openai_compatible_key
OPENAI_BASE_URL=https://your-compatible-endpoint/v1

DEEPSEEK_API_KEY=
QWEN_API_KEY=

MODEL_ANALYSIS=your-analysis-model
MODEL_FAST=your-fast-model
MODEL_REPORT=your-report-model

EMBEDDING_MODEL=your-embedding-model
RAG_USE_CHROMA=true
```

Notes:

- The current `real_model_configured` fallback accepts `OPENAI_API_KEY + MODEL_ANALYSIS`.
- Some downstream paths are still more battle-tested with DeepSeek text models than with fully custom OpenAI-compatible stacks.
- If `EMBEDDING_MODEL` does not start with `text-embedding-`, embeddings route through the OpenAI-compatible configuration instead of the Qwen configuration.

## Current routing behavior

As of 2026-07-17:

- `ProductMarketAgent` and `UserInsightAgent` use the analysis model path.
- `OperationsDecisionAgent` prefers Qwen when `QWEN_API_KEY + MODEL_REPORT` exist; otherwise it can use DeepSeek.
- `EvidenceAuditAgent` prefers Qwen when `QWEN_API_KEY + MODEL_FAST` exist; otherwise it can use DeepSeek.
- `create_vision_model()` still requires Qwen when a real candidate image actually needs to be analyzed.
- `EMBEDDING_MODEL=text-embedding-v4` uses the Qwen-compatible embedding endpoint.
- blank `EMBEDDING_MODEL` uses local `tradepilot-hash-embedding` only in tests/offline helpers; the deployed real-mode readiness check rejects it.

## Common failure modes

### `llm_not_configured`

Usually means one of these is missing:

- `DEEPSEEK_API_KEY`
- `MODEL_ANALYSIS`
- `MODEL_FAST`
- `MODEL_REPORT`

or the fallback OpenAI-compatible text configuration is incomplete.

### `401 Unauthorized` from DashScope embeddings

Usually means:

- `QWEN_API_KEY` is invalid, or
- `QWEN_API_KEY` is still a placeholder string, or
- `EMBEDDING_MODEL=text-embedding-v4` is enabled when you intended to run DeepSeek-only.

### `Real image understanding requires QWEN_API_KEY`

This only matters when a valid candidate image must be analyzed by the real vision path.

For text-only real runs without uploaded candidate images, the service now skips vision cleanly.

## Recommended checks

After editing `.env`, restart Uvicorn and verify the resolved configuration:

```powershell
@'
from app.core.config import Settings
s = Settings()
print("real_model_configured =", s.real_model_configured)
print("deepseek_api_key =", bool(s.deepseek_api_key))
print("qwen_api_key =", bool(s.qwen_api_key))
print("openai_api_key =", bool(s.openai_api_key))
print("model_analysis =", s.model_analysis)
print("model_fast =", s.model_fast)
print("model_report =", s.model_report)
print("embedding_model =", repr(s.embedding_model))
print("rag_use_chroma =", s.rag_use_chroma)
'@ | & C:\Users\ASUS\.conda\envs\shixun\python.exe -
```

For a DeepSeek-only text stack (before the separate real RAG readiness check), the expected shape is:

```text
real_model_configured = True
deepseek_api_key = True
qwen_api_key = False
model_analysis = deepseek-v4-flash
model_fast = deepseek-v4-flash
model_report = deepseek-v4-flash
embedding_model = ''
rag_use_chroma = True
```

## Recommended real-run command

After configuration is ready:

```powershell
cd F:\TradePilot
& C:\Users\ASUS\.conda\envs\shixun\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then submit the product and analysis run through the existing API workflow.

