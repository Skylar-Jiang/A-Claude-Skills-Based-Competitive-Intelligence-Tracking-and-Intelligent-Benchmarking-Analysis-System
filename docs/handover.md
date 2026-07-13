# Handover

## Completed backend base

- Python 3.12 project contract, Settings, safe example environment, and ignore rules.
- One `app/` backend package, one FastAPI app/entry, ten `/api/v1` routes and unified envelopes.
- Pydantic v2 product, evidence, four Agent output, audit, report, and `TradePilotState` contracts.
- SQLAlchemy/SQLite baseline tables and repository interfaces.
- Two logical RAG domains, an in-memory test store, and an injected-embedding Chroma adapter.
- True LangGraph fan-out/fan-in, separate decision/audit nodes, and one bounded retry.
- Final state, four outputs, evidence, and Demo JSON/Markdown report persistence.
- Generic Demo adapter/fixtures, scripts, tests, and empty frontend placeholder.

## Current Stub content

All four Agents run deterministic LCEL chains and return `data_origin=demo` plus
`implementation_status=scaffold`. The first two return `insufficient_evidence` when their knowledge
domain is empty. Audit only checks required scaffold markers. Reports contain a prominent Demo notice.

## Not implemented

There are no production prompts, model calls, source collectors, embeddings, retrieval tuning,
review cleaning, sentiment analysis, market statistics, price analysis, operational rules, semantic
audit, multi-round local recomputation, marketing content, or frontend.

## Decisions and assumptions

The user's later scope restriction overrides earlier requests for complete Agent/RAG/business logic.
The same restriction overrides planning-document frontend proposals. The requested clean replacement
overrides the planning document's possible legacy retention; only proven-unreferenced legacy is
removed, while `new-docs/` is preserved. Mock and configured Real analysis return explicit 503 rather
than pretending Demo Stub output belongs to another mode.

## Next entry points

See `docs/team-work-split.md` for the three owners. Domain additions must leave API,
`TradePilotState`, repository interfaces, and graph topology unchanged unless the team explicitly
approves a contract revision.
