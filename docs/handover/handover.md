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
- Main peer-group Chroma retrieval uses configurable MMR and records its selection strategy; the exact-product
  evaluation pipeline retains optional external reranking with explicit use/fallback metadata.
- Four real model-backed LCEL Agents in one LangGraph; the first two truly overlap.
- All four Real Agents terminate in `PydanticOutputParser`, retry only malformed JSON/Schema output within a separate
  bound, and persist model-call/parse-retry/token-usage metadata.
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
- Environment-aware `.env` plus `.env.<APP_ENV>` loading, safe request logs, and programmatic migrations that do not
  replace application logging handlers.

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

## Excellence-gate validation (2026-07-16)

- Clean real HTTP run `5cef095f-1f8c-4d2b-8327-d542e33e768f` succeeded after the typed-parser/MMR/logging changes:
  20 peers, 89 review documents, 109 total small-Chroma documents, MMR 0.7, and true parallel Agent overlap.
- All four Agent outputs recorded `PydanticOutputParser`, one real model call, zero parse retries and actual provider
  token usage. Request logs contained the allow-listed request metadata only.
- Report inspection found and fixed a Chinese-unit decimal boundary bug. A second real run found and fixed an object
  shaped `positioning` response by routing it into the bounded parse retry.
- An intermediate post-fix rerun was externally blocked by DeepSeek HTTP 402 `Insufficient Balance`; Real mode
  persisted the failure without fallback. Deterministic regression covers both defects found before that run.

Balance was subsequently restored and final run `33855f70-0be7-4dbb-a0c3-d70627fadb4f` succeeded with audit `pass`,
true parallel overlap, four single-call typed Agents, MMR 0.7, 20 peers, 89 review documents and a 73,845 ms total HTTP
duration. Final Markdown inspection confirmed sourced decimals, Chinese user-facing narrative, all required sections,
and no forbidden candidate-review attribution or Demo/Scaffold text. A transient Windows HNSW segment-reader failure
encountered during the clean rebuild is now covered by a bounded read retry and a deterministic regression test.
Final local gates are 154 passed and 3 opt-in skips; `pip check`, compileall, Ruff and Smoke Test all pass.

## Operational sequence

1. Restore Git LFS source files.
2. Copy `.env.example` to ignored `.env` and add local provider keys.
3. Optionally copy `.env.development.example` or `.env.production.example` to the corresponding ignored overlay.
4. Run `python scripts/prepare_peer_data.py` offline.
5. Start uvicorn and create a Real candidate product.
6. Upload a candidate image only when it is reliable and belongs to that candidate.
7. Start analysis, then consume metadata/SSE/report endpoints.

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

## Product inventory and final integration validation (2026-07-17)

- The source-derived catalog inventory flags all 161,540 catalog rows: 493 resolved terminal-type buckets and one
  `__unresolved__` bucket containing 9,387 rows with missing source categories. Its second run reused the ignored
  `product_type_flags.sqlite`; it did not rebuild catalog FTS, review offsets or any full vector index.
  The cache now records classifier version `source-leaf-v1` and invalidates independently when that version changes.
- The ten smoke examples are not the catalog taxonomy. Online matching remains candidate-specific FTS/rule recall
  plus bounded Qwen reranking; the inventory flag is never a hard peer filter.
- Accessory regressions now exclude cat-fountain filters and cleaning kits while retaining a complete fountain that
  merely contains a pump/filter. A real Qwen check selected 20 complete fountain peers and 20 complete automatic
  litter-box peers.
- Final Real HTTP run `c8cec70c-be10-48d7-9bb6-7dbacd7f429d`, report
  `457d11a6-bc27-4246-9201-488a3b0e987e`, succeeded with audit `pass` and no EvidenceAudit manual review. The
  separate customs-broker review flag remained true for the candidate HTS classification. It selected 20 peers,
  ingested 99 small-Chroma documents, returned 33 SSE events plus 32 replay events and passed report support,
  evidence-detail, Markdown and JSON checks.
- Matching took 6,854 ms; review offset reads 33 ms; SQLite persistence 54 ms; RAG build/ingest 8/2,331 ms; RAG
  retrieval 659 ms; SQL statistics 2 ms. ProductMarketAgent took 18,964 ms and UserInsightAgent 13,091 ms with real
  overlap. A semantic audit finding triggered one bounded workflow correction; the accepted OperationsDecisionAgent
  call took 31,577 ms and EvidenceAuditAgent 5,475 ms. Total HTTP E2E was 111,347 ms.
- Operations strategy fields remain strict on the first LCEL parse. If the bounded retry still returns nested strategy
  objects, only readable narrative values are flattened; evidence IDs, ASINs, priorities and machine fields are
  discarded before final `OperationPlan` validation.
- Real Markdown is Chinese for user-facing explanations, retains immutable foreign product/brand names and official
  codes, hides sample counts and machine IDs, and exposes numbered evidence links. JSON and the evidence-detail API
  retain the complete mapping and original source data.
- Final deterministic gates: `pip check` clean, 194 tests passed with 3 opt-in skips, `compileall` and Ruff passed,
  and Smoke Test returned four Agent outputs, three evidence records and one report.
