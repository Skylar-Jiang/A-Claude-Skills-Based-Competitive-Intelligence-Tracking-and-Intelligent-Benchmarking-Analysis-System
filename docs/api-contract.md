# API contract

Formal endpoints use `/api/v1`. JSON endpoints return the unified envelope:

```json
{"success":true,"data":{},"meta":{"request_id":"...","api_version":"v1","data_mode":"real"},"error":null}
```

Errors use `success=false`, `data=null`, and structured `error.code`, `error.message`, and `error.details`. Real mode
never substitutes Demo/Mock output. Workflow exceptions persist a failed run when a run has already been created.

The 24 routes are:

- `GET /api/v1/health`
- `GET /api/v1/workflow/metadata`
- `POST /api/v1/products`
- `GET /api/v1/products/{product_id}`
- `POST /api/v1/products/{product_id}/files`
- `POST /api/v1/analysis-runs`
- `GET /api/v1/analysis-runs/{run_id}`
- `GET /api/v1/analysis-runs/{run_id}/status`
- `GET /api/v1/analysis-runs/{run_id}/timeline`
- `GET /api/v1/analysis-runs/{run_id}/agents`
- `GET /api/v1/analysis-runs/{run_id}/peers`
- `GET /api/v1/analysis-runs/{run_id}/evidence`
- `GET /api/v1/analysis-runs/{run_id}/audit`
- `GET /api/v1/analysis-runs/{run_id}/metadata`
- `GET /api/v1/analysis-runs/{run_id}/events`
- `POST /api/v1/analysis-runs/{run_id}/feedback`
- `GET /api/v1/reports/{report_id}`
- `GET /api/v1/reports/{report_id}/markdown`
- `GET /api/v1/reports/{report_id}/json`
- `POST /api/v1/reports/{report_id}/support`
- `GET /api/v1/reports/{report_id}/versions`
- `POST /api/v1/reports/{report_id}/rollback`
- `POST /api/v1/knowledge/rebuild`
- `GET /api/v1/conversations/{session_id}`

`POST /analysis-runs` is asynchronous and returns `202`. `status` is the compact polling contract; `timeline` exposes
the ten stable stages; `agents`, `peers`, `evidence`, and `audit` are frontend-ready persisted views. `metadata`
exposes peer scope, selected ASINs, review sample scope, matching limitations, preparation/matching timings,
actual peer count, `insufficient_peer_products`, matcher/embedding versions, configured rule/semantic thresholds,
runtime SQLite persistence, RAG document/ingest/retrieval, SQL statistics, workflow timings, and node execution
timestamps. The `peer_group_id` is an analysis-group ID derived from stable
candidate content, catalog/config/model context, and the accepted ASIN set; it is not the temporary `product_id` or a
category label. `events` is a persisted `text/event-stream` with numeric `id`, named `event`, JSON `data`, heartbeat,
terminal close, and `Last-Event-ID` replay. The Markdown endpoint returns `text/markdown`; the JSON endpoint returns
the exact exported report document. Report support can explain a section or create a guarded local edit as a new
immutable version; rollback also creates a new version and never mutates history.

Common Real-mode errors include `llm_not_configured`, `data_preparation_required`, `knowledge_unavailable`, and
`workflow_failed`. `/openapi.json` is the authoritative typed frontend contract.
