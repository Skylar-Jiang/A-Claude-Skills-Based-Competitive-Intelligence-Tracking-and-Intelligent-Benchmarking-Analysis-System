# TradePilot backend scaffold

TradePilot is a domain-neutral backend scaffold for a multi-agent cross-border product operations
assistant. This phase proves contracts, orchestration, persistence, and API integration only.
All bundled analysis is deterministic Demo data and is marked `data_origin=demo` and
`implementation_status=scaffold`; it is not real business analysis.

## Requirements

- Python 3.12 (`>=3.12,<3.13`)
- LangChain 1.3.11 (the complete `langchain` package), LangChain Core 1.4.8, and LangGraph 1.2.7
- No model key is needed for Demo mode

The current Agent scaffold uses an LCEL `RunnableLambda | RunnableLambda | RunnableLambda`
pipeline compiled as a `RunnableSequence`. It does not use legacy `LLMChain`, `ConversationChain`,
`RetrievalQA`, or `SequentialChain` APIs.

## Run locally

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python scripts\init_db.py
python scripts\seed_demo.py
python -m uvicorn app.main:app --reload
```

Health: `GET http://127.0.0.1:8000/api/v1/health`. Swagger: `/docs`.

Database initialization uses Alembic. Apply the current schema directly with:

```powershell
python -m alembic upgrade head
```

## Verify

```powershell
python -m pip check
python -m pytest -q
python -m compileall -q app tests scripts
python -m ruff check app tests scripts
python scripts\smoke_test.py
```

Real mode requires model configuration and never falls back. Even when configured, this scaffold
returns a clear 503 because real Agent implementations are intentionally deferred. See
`docs/handover.md` and `docs/team-work-split.md` before extending the system.
Shared contracts and migrations follow `docs/contract-governance.md`.
