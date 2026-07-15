# Testing guide

Normal tests are deterministic and must not call providers. Integration tests create tiny source JSONL files, SQLite
caches, and Chroma collections under pytest temporary directories. Opt-in tests cover local real data/models.

Required clean-repository gates:

```powershell
python -m pip check
python -m pytest -q
python -m compileall -q app tests scripts
python -m ruff check app tests scripts
python scripts\smoke_test.py
```

Peer boundary tests verify candidate products have no own reviews, accessory exclusion, quality-gated peer selection,
`parent_asin` review association, peer-group retrieval, evidence scope, Agent terminology, hypothesis labeling, actual
fan-out overlap, cache idempotency, and absence of full-corpus embedding. Semantic audit tests additionally cover
different/missing categories, same-main-category negative examples, no global label dependency, stable IDs across
temporary `product_id` values, invalidation by catalog/config/selected-ASIN changes, threshold metadata, and an
under-10 result that is deliberately not filled.

Real final acceptance additionally requires:

1. Run `scripts/prepare_peer_data.py` cold, then hot, and record both cache timings.
2. Run a `data_mode=real` HTTP request against uvicorn, using a client with `trust_env=False` if a workstation proxy
   interferes with provider TLS.
3. Assert run `status=succeeded`, four persisted Agent outputs, `parallel_agent_overlap=true`, only threshold-qualified
   peers (even if fewer than 10), peer-review evidence only, and no manual review.
4. Read metadata, SSE, Markdown, structured report, and exported JSON endpoints.
5. Assert the Real Markdown contains all required peer-market sections and contains none of the forbidden candidate
   review attributions or Demo/Scaffold explanation.
6. When a reliable candidate image is uploaded, assert the recorded model is a verified Qwen vision model. If no
   reliable candidate image exists, assert vision is skipped rather than substituting a peer image.
7. Assert metadata contains matcher/embedding versions, rule/semantic thresholds, cache/matching/review timings,
   runtime SQLite persistence, RAG build/ingest/retrieval, SQL statistics, all Agent durations, and workflow duration.
8. Run `python scripts/smoke_multi_product_matching.py` with real credentials and confirm all ten terminal-product
   cases reuse both caches, have no orphan reviews, and contain no configured accessory-only products.
9. Run `python scripts/real_http_e2e.py`; it verifies async polling, SSE replay, the six frontend read views, report
   Markdown/JSON, report support, peer evidence scope, four Agents, and actual ProductMarket/UserInsight overlap.

Report only actual zero exit codes. Real provider retries/failures must remain visible and must never trigger a
Demo/Mock fallback.
