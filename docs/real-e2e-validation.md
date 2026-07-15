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
