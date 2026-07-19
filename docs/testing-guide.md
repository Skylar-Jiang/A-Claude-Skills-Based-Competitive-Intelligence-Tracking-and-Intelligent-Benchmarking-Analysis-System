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

Full-catalog terminal-type inventory is a separate offline audit. It assigns every prepared catalog row a
source-derived type flag without embedding or rewriting the catalog:

```powershell
python scripts\audit_catalog_product_types.py
```

The command writes ignored `data/demo/cache/product_type_flags.sqlite` and
`data/demo/validation/terminal_product_type_inventory.json`. A repeated run reuses the flag cache when the catalog
source signature and schema are unchanged. `__unresolved__` is a valid audit result for missing category data; a type
flag does not imply that reviews exist and is not permission to fabricate or quota-fill a peer group.
Cache reuse also requires the explicit classifier version to match; the regression suite verifies that changing it
rebuilds only `product_type_flags.sqlite`.

Peer boundary tests verify candidate products have no own reviews, accessory exclusion, quality-gated peer selection,
`parent_asin` review association, peer-group retrieval, evidence scope, Agent terminology, hypothesis labeling, actual
fan-out overlap, cache idempotency, and absence of full-corpus embedding. Semantic audit tests additionally cover
different/missing categories, same-main-category negative examples, no global label dependency, stable IDs across
temporary `product_id` values, invalidation by catalog/config/selected-ASIN changes, threshold metadata, and an
under-10 result that is deliberately not filled.

Engineering-gate tests also verify environment-specific dotenv precedence and path validation, safe HTTP request
logging, bounded Pydantic parse retries, provider-error non-retry behavior, token-usage aggregation, Chroma MMR
diversification and external-reranker trace metadata.

Real final acceptance additionally requires:

1. Run `scripts/prepare_peer_data.py` cold, then hot, and record both cache timings.
   If the source JSONL files are Git LFS pointers, run `git lfs pull` before preparing caches. Real API requests now
   reject missing LFS content, missing/stale caches, and missing Embedding credentials before a run is queued.
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
   cases reuse both caches, have no orphan reviews, and contain no configured accessory-only products. Inspect selected
   titles as well as counts; a numeric quota alone is not a semantic-quality assertion.
9. Run `python scripts/real_http_e2e.py`; it verifies async polling, SSE replay, the six frontend read views, report
   Markdown/JSON, report support, peer evidence scope, four Agents, and actual ProductMarket/UserInsight overlap.

Report only actual zero exit codes. Real provider retries/failures must remain visible and must never trigger a
Demo/Mock fallback.
