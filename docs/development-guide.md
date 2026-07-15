# Development guide

Use Python 3.12 and install the locked requirement ranges. Copy `.env.example` to ignored `.env`; never commit keys,
SQLite, Chroma state, prepared caches, uploaded images, reports, logs, or virtual environments.

## Real configuration

Use the official provider bases already shown in `.env.example`. Recommended validated model IDs are
`deepseek-v4-flash`, `qwen3.6-flash`, `qwen3.7-plus`, `qwen3-vl-plus`, and `text-embedding-v4`. Structured Agents
explicitly disable provider thinking mode so hidden reasoning cannot exhaust the bounded JSON output budget.

Prepare caches separately before starting the API:

```powershell
python scripts\prepare_peer_data.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Do not add raw JSONL scans or cache builds to request handlers. Do not replace candidate-only embedding with full
dataset embedding, and do not call the full-index rebuild path from peer-group analysis.

## Change rules

- Preserve both retrieval scopes; new Real candidate work uses `peer_group`, existing tests may use `exact_product`.
- Keep exact numeric facts in `StatisticsResult` or user input, not review text or model memory.
- Preserve `peer_group_id`, selected peer IDs/ASINs, statistics, product/review evidence, sample scope, match metadata,
  vision output, node timings, and workflow timing in `TradePilotState`.
- Add a failing test before changing matching, retrieval, Agent semantics, audit, or error behavior.
- Apply Alembic migrations with `python -m alembic upgrade head`; never rewrite an applied migration.

Use `config/peer_matching.yaml` for accessory/exclusion terms and selection limits instead of scattering business terms
through Python modules.
