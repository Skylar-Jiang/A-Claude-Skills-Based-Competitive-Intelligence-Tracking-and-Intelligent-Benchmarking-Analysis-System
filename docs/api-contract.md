# API contract

All formal endpoints use `/api/v1` and return one envelope:

```json
{"success":true,"data":{},"meta":{"request_id":"...","api_version":"v1","data_mode":"demo"},"error":null}
```

Errors set `success=false`, `data=null`, and provide `error.code`, `error.message`, and
`error.details`. The ten routes are:

- `GET /api/v1/health`
- `POST /api/v1/products`
- `GET /api/v1/products/{product_id}`
- `POST /api/v1/products/{product_id}/files`
- `POST /api/v1/analysis-runs`
- `GET /api/v1/analysis-runs/{run_id}`
- `POST /api/v1/analysis-runs/{run_id}/feedback`
- `GET /api/v1/reports/{report_id}`
- `POST /api/v1/knowledge/rebuild`
- `GET /api/v1/conversations/{session_id}`

Real mode without model configuration returns HTTP 503 with `llm_not_configured`. It never switches
to Mock or Demo. Real analysis remains unavailable in this scaffold even when configuration exists.
