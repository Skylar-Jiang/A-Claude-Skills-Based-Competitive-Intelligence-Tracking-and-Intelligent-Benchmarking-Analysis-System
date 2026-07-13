# TradePilot backend scaffold

TradePilot is a domain-neutral backend scaffold for a multi-agent cross-border product operations
assistant. This phase proves contracts, orchestration, persistence, and API integration only.
All bundled analysis is deterministic Demo data and is marked `data_origin=demo` and
`implementation_status=scaffold`; it is not real business analysis.

## Requirements

- Python 3.12 (`>=3.12,<3.13`)
- No model key is needed for Demo mode

## Run locally

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts\init_db.py
.\.venv\Scripts\python.exe scripts\seed_demo.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Health: `GET http://127.0.0.1:8000/api/v1/health`. Swagger: `/docs`.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app tests scripts
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

Real mode requires model configuration and never falls back. Even when configured, this scaffold
returns a clear 503 because real Agent implementations are intentionally deferred. See
`docs/handover.md` and `docs/team-work-split.md` before extending the system.
