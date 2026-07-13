# Refactor mapping

This historical mapping is retained only to explain the cleanup; none of these removed paths are
runtime dependencies.

| Removed legacy area | TradePilot replacement |
| --- | --- |
| root application entry and duplicate API server | `app/main.py`, `app/api/v1/router.py` |
| sequential analysis and report orchestration | `app/workflows/graph.py` |
| old competitor-specific RAG chain | `app/rag/` two-domain ports |
| old shared agent/skill core | four independent files under `app/agents/` |
| legacy source configuration and business data | generic profile and marked fixtures under `config/` and `data/demo/` |
| legacy report writer | `app/services/report_exporter.py` |

Reusable ideas—not copied business definitions—included injected model/storage clients, evidence
metadata, deterministic test fixtures, Markdown/JSON output, and local persistent vector storage.
