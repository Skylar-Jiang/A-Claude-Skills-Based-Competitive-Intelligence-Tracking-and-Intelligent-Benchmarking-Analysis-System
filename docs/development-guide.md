# Development guide

Use Python 3.12 only. Install `requirements.txt` with `python -m pip install -r requirements.txt`, copy
`.env.example` to `.env`, and run the verification commands in the README before handing off changes.
Never commit `.env`, keys, SQLite, Chroma state, generated reports, caches, or virtual environments.

To add a domain, add exactly:

1. a profile under `config/domain_profiles/`;
2. a `DomainAdapter` under `app/adapters/domains/`;
3. a data import/cleaning script under `scripts/`.

Do not change `/api/v1`, `TradePilotState`, repository protocols, or the main graph merely to add a
domain. If a contract must change, document the compatibility impact first and add a failing test.

Domain profiles are loaded with `load_domain_profile` and select their adapter with
`load_domain_adapter`; scripts must not import one concrete adapter as the runtime selection rule.
RAG consumers receive `KnowledgeStore` through `app.rag.factory`, and analysis Agents receive a
validated `StatisticsResult` written by the `statistics_provider` graph node.

## Migrations and shared contracts

Initialize or upgrade with `python -m alembic upgrade head` (or `python scripts/init_db.py`). Create
schema changes with `python -m alembic revision --autogenerate -m "message"`, inspect the revision,
and test downgrade/upgrade. Never edit the initial migration after teammates have branched.

Shared schemas, state, graph, router, models/migrations, enums, and cross-team ports belong to the
Contract Maintainer. Follow `docs/contract-governance.md`: public changes use a standalone Contract
PR with compatibility, migration, tests, and merge/rebase order. Business PRs stay inside the owner
paths in `docs/team-work-split.md`.
