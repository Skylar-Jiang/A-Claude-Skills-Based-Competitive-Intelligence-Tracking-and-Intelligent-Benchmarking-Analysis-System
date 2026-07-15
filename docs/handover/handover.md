# TradePilot final backend handover

## Completed production path

- Unlisted user product profile with no fabricated sales, rating, or reviews.
- Explicit offline FTS product catalog and offset-only review lookup with signatures, atomic writes, stale detection,
  and warm idempotent reuse.
- Configured accessory exclusion, rule/FTS prefilter, candidate-only Qwen embedding rerank, stable peer group, and
  exact review lookup for selected `parent_asin` values.
- Peer matching is direct same-terminal-product retrieval, not whole-catalog classification: categories are auxiliary,
  missing categories are accepted, and same-main-category different terminal products cannot qualify on category and
  price alone.
- The candidate-specific `peer_group_id` hashes normalized candidate content (not temporary `product_id`), catalog
  signature, full matcher config/version, embedding model, and sorted accepted ASINs.
- Configured minimum rule/semantic thresholds are quality-first. Low-quality products are never added to reach 10;
  a smaller accepted set becomes an `insufficient_peer_products` limitation throughout Agents and reports.
- Independent runtime SQLite plus small `product_knowledge` and `review_insight` Chroma collections.
- Backward-compatible `exact_product` retrieval and production `peer_group` retrieval.
- Real peer-group SQL statistics separated from review interpretation.
- Four real model-backed LCEL Agents in one LangGraph; the first two truly overlap.
- Conditional Qwen image understanding with magic-byte validation and visible-attribute-only output.
- Deterministic evidence audit for peer attribution/scope, accessories, numeric sources, hypothesis labels, evidence
  existence, semantic conflicts, and known-risk conflicts; model findings are retained as advisory warnings.
- Persisted state/evidence/Agent timings, workflow metadata, SSE events, Markdown content, and JSON report APIs.
- HTTP 202 background execution, ten-stage timeline, status/Agent/peer/evidence/audit frontend views, durable SSE with
  heartbeat and `Last-Event-ID` replay.
- Immutable report versions, evidence-grounded section explanation, guarded local edits with diffs, conversation
  audit records, and append-only rollback.
- Optional dated/jurisdiction-scoped product-background provider contract; the default provides no external facts.
- Explicit failed-run persistence and no Real-to-Demo/Mock fallback.

## Validated real run (2026-07-15)

- Product catalog: 161,540 rows; cold build 100,804 ms.
- Review lookup: 594,175 rows; cold build 43,980 ms.
- Warm preparation reuse: 4 ms; neither cache was rebuilt during the final multi-product or HTTP runs.
- Final HTTP online prefilter: 300; semantic rerank: 40; final peers passing the 0.45 semantic threshold: 20;
  configured accessory exclusions observed: 137.
- Matcher `peer-matcher-v2`, Qwen `text-embedding-v4`, rule threshold 0.2, semantic threshold 0.45; no quota fill and
  no insufficient-peer gap in this run. Peer group: `9546f2b4-d59e-5f7f-bab5-b6f7bb29a7ee`.
- Peer review pool: 89 unique source reviews after identity deduplication; runtime Chroma collections: 20 product
  documents and 89 review documents.
- Final successful HTTP E2E: 60,932 ms; matching 7,100 ms; review offset reads 3 ms; complete online peer service
  10,163 ms; LangGraph workflow 47,962 ms.
- Runtime SQLite peer persistence 62 ms; RAG document build 14 ms; small-Chroma ingest 2,980 ms; RAG retrieval 672 ms;
  peer SQL statistics query 2 ms.
- ProductMarketAgent 17,026 ms; UserInsightAgent 14,591 ms; their intervals overlap.
- OperationsDecisionAgent 25,933 ms; EvidenceAuditAgent 4,284 ms.
- Run status `succeeded`, retry count 0, audit `warning`, manual review false.
- Twenty-nine persisted SSE/workflow events were returned; reconnect after the first ID replayed the remaining 28.
  Timeline, status, Agent, peer, evidence, audit, metadata, Markdown, structured report, exported JSON and report
  support returned successfully.
- Real report contained all required sections and no forbidden candidate-review attribution or Demo/Scaffold text.
- Latest persisted-input real Qwen audit used all 11 supplied evidence records with no deterministic blocker and no
  manual review. Model-only attribution questions remain non-blocking advisories.
- Ten-product real smoke used `text-embedding-v4` and completed in 71,099 ms. Water fountain, automatic feeder, dog
  harness, automatic litter box, orthopedic dog bed, scratching post, pet carrier, grooming clippers, aquarium heater,
  and training collar each selected 20 peers; review pools ranged from 69 to 95 with zero orphan associations.
- Final deterministic regression: 140 passed, 3 skipped; `pip check`, `compileall`, Ruff and Smoke Test all passed.
- Independent official-image smoke verified `qwen3-vl-plus` in 2,710 ms; no reliable candidate image was supplied, so
  the candidate workflow correctly skipped vision rather than using a peer image.

## Operational sequence

1. Restore Git LFS source files.
2. Copy `.env.example` to ignored `.env` and add local provider keys.
3. Run `python scripts/prepare_peer_data.py` offline.
4. Start uvicorn and create a Real candidate product.
5. Upload a candidate image only when it is reliable and belongs to that candidate.
6. Start analysis, then consume metadata/SSE/report endpoints.

## Boundaries and limitations

- Reviews are a bounded peer sample, not candidate feedback and not population statistics.
- Candidate semantic matching embeds only the bounded FTS/rule candidate set; no full embedding occurs.
- Fewer than 10 accepted peers is a supported data limitation, not a reason to lower thresholds or fill with another
  terminal product.
- Model audit advisories can remain as non-blocking warnings; deterministic blockers cause one bounded decision retry
  and then manual review.
- The application does not perform live web market research or generate facts from model memory.
- Demo compatibility code remains intentionally; Real reports never include its disclaimer or scaffold explanation.

Runtime databases, caches, Chroma files, uploaded images, reports, logs, and API keys are ignored and must not be
committed or attached to a handover archive.
