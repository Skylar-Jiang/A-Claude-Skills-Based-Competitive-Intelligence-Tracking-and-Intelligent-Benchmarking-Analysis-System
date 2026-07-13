# Development guide

Use Python 3.12 only. Install `requirements-dev.txt`, copy `.env.example` to `.env`, and run the four
verification commands in the README before handing off changes. Never commit `.env`, keys, SQLite,
Chroma state, generated reports, caches, or virtual environments.

To add a domain, add exactly:

1. a profile under `config/domain_profiles/`;
2. a `DomainAdapter` under `app/adapters/domains/`;
3. a data import/cleaning script under `scripts/`.

Do not change `/api/v1`, `TradePilotState`, repository protocols, or the main graph merely to add a
domain. If a contract must change, document the compatibility impact first and add a failing test.
