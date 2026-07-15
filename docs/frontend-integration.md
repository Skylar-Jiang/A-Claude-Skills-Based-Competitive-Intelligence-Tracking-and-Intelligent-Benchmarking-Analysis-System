# Frontend integration

Create the product first, then start analysis with `POST /api/v1/analysis-runs`. A successful submission returns
HTTP 202 and a durable `run_id`; it does not wait for models or report export.

Read `GET /api/v1/workflow/metadata` once to render stable Chinese node names, responsibilities, execution order,
parallel groups, provider/model configuration and graph edges.

Use either of these progress patterns:

1. Poll `GET /analysis-runs/{run_id}/status` and render the ten ordered rows returned by `/timeline`.
2. Open `GET /analysis-runs/{run_id}/events` as SSE. Store the last numeric event ID and reconnect with
   `Last-Event-ID`; the server replays only later persisted events. Comment heartbeats are not business events.

Terminal statuses are `succeeded`, `manual_review`, and `failed`. A failed run includes a structured persisted error
and never silently returns Demo or Mock output. On success, fetch:

- `/agents` for the four structured Agent outputs and timings;
- `/peers` for `peer_group_id`, selected ASINs and peer facts;
- `/evidence` for traceable citations;
- `/audit` for evidence-audit status and findings;
- `/metadata` for matching, RAG, SQL, parallel-overlap and workflow timings;
- `/reports/{report_id}`, `/markdown`, and `/json` for presentation or export.

All JSON routes except the raw Markdown/JSON download routes use the common `success/data/meta/error` envelope.
Treat `product_id` as the uploaded candidate record ID and `peer_group_id` as the stable candidate/data/config/result
analysis-group ID; they are intentionally different. Peer reviews must always be labelled as peer-market samples.

Report sections have stable `section_id` values and Markdown anchors. Use these IDs for navigation and report-support
requests rather than matching localized headings.
