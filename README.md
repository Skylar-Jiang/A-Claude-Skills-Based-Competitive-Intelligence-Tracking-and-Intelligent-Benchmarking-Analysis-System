# TradePilot backend

TradePilot analyzes an unlisted pet product by matching it to real listed peer products, then grounding market and user
insights in peer metadata, SQL statistics, and peer-review RAG evidence. Real mode uses four LCEL Agents in one
LangGraph workflow and never falls back to Demo or Mock.

## Runtime contract

- Python `>=3.12,<3.13`
- LangChain 1.3.x, LangChain Core 1.4.x, LangGraph 1.2.x
- FastAPI, Pydantic v2, SQLAlchemy/Alembic, SQLite, Chroma
- DeepSeek V4 Flash for ProductMarketAgent and UserInsightAgent
- Qwen 3.7 Plus for OperationsDecisionAgent, Qwen 3.6 Flash for EvidenceAuditAgent
- Qwen3-VL Plus for conditional image understanding and `text-embedding-v4` for bounded candidate/RAG embeddings

Demo mode remains available for deterministic compatibility tests. Real mode requires both provider keys, prepared
offline lookup caches, Chroma, and the real source JSONL files.

## Install

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m alembic upgrade head
```

Fill `DEEPSEEK_API_KEY` and `QWEN_API_KEY` only in the ignored `.env`. Never commit that file.

## Prepare real peer data offline

```powershell
python scripts\prepare_peer_data.py
```

This command scans product metadata and reviews only when the source signature is new or stale. It builds
`data/demo/cache/product_catalog.sqlite` and `review_lookup.sqlite`. The catalog contains normalized lightweight
metadata plus FTS; the review lookup stores source offsets/line numbers, not copied review text. It does not embed the
full dataset and does not read or modify the full Chroma index.

The online `/analysis-runs` path only opens valid prepared caches. Missing or stale caches return
`data_preparation_required`; online analysis never scans raw JSONL or rebuilds a cache.

Peer matching is query-time direct-product matching, not a global product classifier. FTS recalls on product text;
`categories` and price are weak scoring signals, and missing/different categories do not block a real same-terminal
product. Acceptance thresholds and matcher version live in `config/peer_matching.yaml`. Products below the configured
rule/semantic thresholds are never used to fill a quota; fewer than 10 accepted peers produces the traceable
`insufficient_peer_products` data gap.

`peer_group_id` identifies this candidate-specific analysis group. Its stable input excludes the upload/runtime
`product_id` and includes the normalized candidate signature, catalog source signature, full matching config and
matcher version, embedding model, and sorted final `selected_parent_asins`.

## Run

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health: `GET http://127.0.0.1:8000/api/v1/health`. Swagger: `/docs`.

Create a `data_mode=real` product with its name, description, features, parameters, scenarios, target species/users,
target price, and optional uploaded image. Then call `POST /api/v1/analysis-runs` with the returned `product_id`.
Metadata, SSE events, Markdown, and JSON are available from the run/report endpoints documented in
`docs/api-contract.md`.

## Verify

```powershell
python -m pip check
python -m pytest -q
python -m compileall -q app tests scripts
python -m ruff check app tests scripts
python scripts\smoke_test.py
```

Real provider tests are opt-in so normal CI remains deterministic. The final HTTP E2E must be run with local secrets
and `trust_env=False` when the workstation has an incompatible system proxy. See `docs/testing-guide.md` and
`docs/handover/handover.md`.
