# Real E2E validation — 2026-07-15

Environment: Python 3.12.6, real DeepSeek/Qwen credentials from ignored `.env`, Uvicorn on localhost, independent
`data/demo` SQLite/Chroma/report directories. No source JSONL, prepared cache, or full index was modified.

## Prepared data and multi-product smoke

- Catalog: 161,540 rows; recorded cold build 100,804 ms.
- Review offsets: 594,175 rows; recorded cold build 43,980 ms.
- Warm preparation: 4 ms, `catalog_rebuilt=false`, `review_lookup_rebuilt=false`.
- Ten-product real `text-embedding-v4` smoke: 71,099 ms.
- Each of water fountain, automatic feeder, dog harness, automatic self-cleaning litter box, orthopedic dog bed,
  scratching post, carrier, grooming clippers, aquarium heater and training collar selected 20 threshold-qualified
  complete products. Review pools were 69–95 and orphan review count was zero.

## HTTP run

- Candidate: unlisted automatic self-cleaning cat litter box; no candidate sales, rating or reviews.
- Peer group: `9546f2b4-d59e-5f7f-bab5-b6f7bb29a7ee`.
- Prefilter/rerank/final: 300 / 40 / 20; 137 configured accessories excluded.
- Unique peer reviews: 89; runtime Chroma: 20 product and 89 review records.
- Matching 7,100 ms; review seek 3 ms; SQLite persist 62 ms; document build 14 ms; Chroma ingest 2,980 ms.
- RAG retrieval 672 ms; SQL statistics 2 ms; workflow 47,962 ms; HTTP E2E 60,932 ms.
- ProductMarketAgent 17,026 ms and UserInsightAgent 14,591 ms started 3 ms apart and overlapped.
- OperationsDecisionAgent 25,933 ms; EvidenceAuditAgent 4,284 ms.
- Four Agents used real LCEL model paths; `fallback_used=false`. Audit completed with non-blocking warning and the run
  succeeded without manual review.
- 29 durable SSE events were returned; reconnect after event 1 replayed 28. All frontend read views, Markdown, JSON
  and report-support explanation succeeded.

The final HTTP duration is 14.7% below the earlier 71,435 ms handover baseline. Provider latency dominates the
remaining time; evidence volume, structured validation and audit coverage were not weakened to force a nominal 15%.

No reliable candidate-owned image was supplied in this run, so image understanding was correctly skipped. A separate
verified smoke used `qwen3-vl-plus`; peer images are never substituted for a candidate image.

## Backend excellence-gate run — 2026-07-16

After adding safe HTTP request logs, environment overlays, typed parse retries, provider token accounting and
peer-group Chroma MMR, a clean real HTTP run completed successfully:

- Run `5cef095f-1f8c-4d2b-8327-d542e33e768f`, report `2a474d34-b772-4baf-91df-b78b4ffeaada`, status `succeeded`.
- Stable peer group `dbf2d261-8712-577f-98b6-2ff82a3dfd29`; prefilter/rerank/final peers `300 / 40 / 20`;
  137 configured accessory candidates excluded.
- Runtime group contained 20 product documents and 89 unique review documents (109 total); 5 bounded review evidence
  records reached the Agent context after MMR/top-k selection.
- Chroma evidence recorded `selection_strategy=mmr` and `mmr_lambda=0.7`.
- ProductMarketAgent 26,504 ms and UserInsightAgent 18,604 ms overlapped. OperationsDecisionAgent took 39,629 ms;
  EvidenceAuditAgent took 8,831 ms. Workflow duration was 75,975 ms and total HTTP E2E was 93,218 ms.
- All four Agent views recorded `real_model_called=true`, `model_call_count=1`, `parse_retry_count=0`, and
  `structured_output_parser=PydanticOutputParser`.
- Provider token totals were: ProductMarketAgent 15,673; UserInsightAgent 4,052; OperationsDecisionAgent 11,143;
  EvidenceAuditAgent 8,006.
- Parallel overlap, 29 durable SSE events, 28 replayed events, Markdown/JSON reports, evidence scope, audit warning
  without manual review, and report-support explanation all passed.

Manual report inspection then found a pre-existing numeric guard defect: a valid decimal immediately followed by a
Chinese unit could be split into `299.待验证数值`. A RED test reproduced the Unicode-boundary issue and the guard now
uses ASCII identifier boundaries, preserving sourced decimals such as `299.99美元` while still replacing unsupported
numbers. A subsequent real run exposed a model variant that returned `positioning` as an object; another RED test now
converts that mismatch into a bounded structured-output retry instead of an unhandled `AttributeError`.

The final post-fix provider rerun on 2026-07-16 reached both parallel DeepSeek Agents and then failed with HTTP 402
`Insufficient Balance`. The persisted run is `7353e415-0406-4269-b17a-e33fae178be9`; both parallel Agent nodes failed,
downstream Qwen Agents did not run, and `fallback_used=false`. Therefore the successful real evidence above proves the
new LCEL parser/MMR/logging/token path, while the two final local fixes are covered by deterministic regression tests.
At that point only restored DeepSeek balance was needed for the final external rerun.

After the account balance was restored, final clean run `33855f70-0be7-4dbb-a0c3-d70627fadb4f` completed with report
`4f1de521-6591-48c7-985b-75086066b928` and audit status `pass`:

- Same stable peer group; prefilter/rerank/final peers `300 / 40 / 20`, 137 accessories excluded, 89 unique peer
  reviews, and 109 small-Chroma documents.
- Peer matching took 11,318 ms; review offset reads 3 ms; runtime SQLite persistence 127 ms; RAG document build 21 ms;
  Chroma ingest 3,722 ms; RAG retrieval 1,065 ms; SQL statistics 3 ms.
- ProductMarketAgent 19,934 ms and UserInsightAgent 17,487 ms overlapped. OperationsDecisionAgent took 26,862 ms and
  EvidenceAuditAgent 4,886 ms. Workflow duration was 52,809 ms; total HTTP E2E was 73,845 ms.
- All four Agents made one real model call with zero parse retries and `PydanticOutputParser`. Token totals were
  14,920 / 4,237 / 10,309 / 6,947 respectively in workflow order.
- MMR 0.7, 29 SSE events plus 28-event replay, report support, Markdown, JSON, evidence scope and all required report
  sections passed. The Markdown retained sourced `299.99`, contained no broken decimal, replacement character,
  forbidden peer-review attribution, or Demo/Scaffold text. English remained only in immutable product/brand names,
  ASINs, units, JSON/anchor identifiers and source excerpts.
- Final deterministic gates: `pip check` passed, 154 tests passed with 3 opt-in external tests skipped, compileall and
  Ruff passed, Smoke Test returned four Agent outputs, three evidence references and one report.

## Final peer-inventory and marketing-report run — 2026-07-17

- Run `bf27ffc7-518b-404a-a0f6-6130bd487db6`, report `7712b5f5-1436-463e-9650-ea82156274fa`, status `succeeded`,
  audit `warning`, manual review false.
- Prefilter/rerank/final peers: 300 / 40 / 20; 477 accessory candidates excluded; 20 real peer products and 79
  unique peer reviews produced 99 small-Chroma documents. Matcher `peer-matcher-v2`, Qwen `text-embedding-v4`, rule
  threshold 0.2 and semantic threshold 0.45 were recorded.
- ProductMarketAgent 17,530 ms and UserInsightAgent 21,395 ms overlapped. OperationsDecisionAgent 102,566 ms used two
  real Qwen calls because the first strategy-list Schema was invalid; EvidenceAuditAgent 4,651 ms. Workflow 129,813
  ms; complete HTTP E2E 145,315 ms.
- The run returned 29 SSE events with 28-event replay, all read views, evidence detail, Markdown, JSON and report
  support. Real mode never fell back during preceding provider connection, timeout or Schema failures.
- Post-run rendering audit removed peer-group UUIDs, ASINs, empty inline evidence labels, Python object literals and
  exact peer/review counts from customer Markdown. `证据N` links preserve the JSON/detail mapping to raw source data.
- Final deterministic gates: `pip check` clean, 182 passed and 3 opt-in skips, `compileall`, Ruff and Smoke Test all
  returned zero.

## Final semantic-audit and report run — 2026-07-17

- Run `c8cec70c-be10-48d7-9bb6-7dbacd7f429d`, report `457d11a6-bc27-4246-9201-488a3b0e987e`, status `succeeded`,
  final EvidenceAudit status `pass`. The separate candidate-HTS customs-broker review requirement remained true.
- The same candidate/catalog/config/embedding/selected-ASIN inputs reproduced stable peer group
  `4f71a8c5-2764-508d-94f8-106869b97375`. Prefilter/rerank/final were 300 / 40 / 20, with 477 accessories excluded,
  79 unique peer reviews and 99 documents in the two small Chroma collections.
- A first audit caught a user-fact-style hypothesis and triggered one bounded Operations correction. The accepted
  plan had all seven launch-marketing fields, one Qwen model call, zero parse retries, and no user-fact hypothesis.
  Deterministic audit also distinguishes a real low-price/high-end contradiction from a single comparison sentence.
- ProductMarketAgent 18,964 ms and UserInsightAgent 13,091 ms overlapped. Accepted OperationsDecisionAgent 31,577 ms;
  EvidenceAuditAgent 5,475 ms; workflow 97,965 ms; total HTTP E2E 111,347 ms. Matching/review reads were 6,854/33 ms;
  SQLite 54 ms; RAG build/ingest/retrieve 8/2,331/659 ms; SQL statistics 2 ms.
- All HTTP read views, evidence detail, Markdown, JSON, report support, 33 SSE events and 32-event replay passed.
  Markdown contained no machine evidence IDs, peer-group UUID, ASIN narration, Demo/Scaffold wording, forbidden
  candidate-review attribution, English risk-flag keys, or user-fact hypothesis.
- Final deterministic gates: `pip check` clean, 194 passed and 3 opt-in skips, `compileall`, Ruff and Smoke Test all
  returned zero.
