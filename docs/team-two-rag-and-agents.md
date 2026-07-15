# Team Two: RAG And Analysis Agents

## Scope

Team two owns the `product_knowledge` and `review_insight` evidence domains, the shared retrieval pipeline, and the
`ProductMarketAgent` / `UserInsightAgent` LCEL chains. This document describes the pre-index implementation freeze. It
does not claim the current local Chroma directory is fully indexed.

## Data Flow

`ProductProfile + user_constraints -> RetrievalPipeline -> EvidenceReference + StatisticsResult -> Agent LCEL -> schema output`

LangGraph orchestrates state and agent calls only. Query building, metadata filters, recall, deduplication, reranking,
evidence binding, and sufficiency checks live in `app.rag.pipeline`.

## Retrieval Pipeline

The pipeline runs in this order:

1. Deterministic query builder.
2. Metadata filter construction with `data_origin=real` and `is_demo=false`.
3. Chroma vector recall.
4. Filter relaxation when strict filters return nothing, while retaining real/demo markers.
5. Vector score threshold.
6. Stable deduplication by `evidence_id`, `document_id`, `review_id`, and `content_hash`.
7. Source diversification with `RAG_MAX_PER_SOURCE`.
8. Conditional reranker.
9. Stable EvidenceReference binding with `RAG-PRODUCT-` or `RAG-REVIEW-` prefixes.
10. Deterministic evidence sufficiency check.

`RetrievalBundle` records fetched, accepted, rejected, duplicate counts, filters, executed queries, rerank status,
warnings, errors, missing evidence types, and latency.

## Query Builder

Product queries use category, description, features, materials, scenarios, target users, target market, target price,
and constraints. They no longer use only `product.name`.

Review queries cover positive experience, durability complaints, size or fit, cleaning, odor, installation, pet
acceptance, value for money, safety, and customer expectations.

The builders are deterministic and omit empty values.

## Metadata Filters

Product filters support `product_id`, `parent_asin`, `asin`, `category`, `marketplace`, `target_market`, `language`,
`data_origin`, and `is_demo`.

Review filters additionally support `rating`, `rating_min`, `rating_max`, and `verified_purchase`.

Rating ranges use Chroma scalar range syntax. If a strict filter returns no results, the pipeline can relax optional
filters and records `metadata_filter_relaxed`.

## Reranker

The main retrieval pipeline can call `Qwen/Qwen3-Reranker-0.6B`. Defaults are conservative:

- `RERANK_ENABLED=false`
- `RERANK_REQUIRED=false`
- `RERANK_POLICY=conditional`
- `RERANK_PRODUCT_ENABLED=false`
- `RERANK_REVIEW_ENABLED=true`
- `RERANK_MIN_CANDIDATES=8`
- `RERANK_MAX_CANDIDATES=20`

Vector score remains in `vector_score`; reranker score is stored separately in `rerank_score`. Evidence IDs are not
changed by reranking. When reranking is unavailable and not required, the bundle records fallback details.

## Agent LCEL

Both analysis agents use:

`input validation -> RunnableParallel(context, retrieval) -> context preparation -> prompt/model or deterministic path -> postprocess -> Pydantic validation`

`ProductMarketAgent` consumes product evidence, user-provided product profile evidence, and `StatisticsResult`. It
validates evidence IDs, records retrieval warnings/errors, carries statistics result IDs, and fills product-market
fields such as category, functions, parameters, scenarios, target users, risks, strengths, weaknesses, and suggestions
when the model provides them.

`UserInsightAgent` consumes review evidence and `StatisticsResult`. It checks positive/negative coverage, prevents
unsupported aggregate language, validates evidence IDs, and records missing evidence and warnings.

## Statistics Boundary

Exact prices, ratings, counts, ratios, averages, and percentages must come from `StatisticsResult` or deterministic
tools. RAG evidence supports text facts and explanations only. If `StatisticsResult.status=insufficient_evidence`, the
agents add statistics data gaps and do not estimate exact values.

## LangGraph Boundary

For REAL runs, `graph.py` no longer runs `store.retrieve(query=product.name)`. It normalizes product input, calls the
statistics provider, and invokes the two agents. The agents own retrieval through the injected shared
`RetrievalPipeline`. Demo runs keep the old in-memory evidence compatibility path so existing scaffold API contracts
and persistence tests continue to pass.

## Indexing Commands

Read-only pre-index checks:

```powershell
py -3.12 -m app.rag.cli validate --source data/filtered
py -3.12 -m app.rag.cli doctor
py -3.12 -m app.rag.cli plan-index --source data/filtered
py -3.12 -m app.rag.cli status
```

Indexing commands remain available but must not be run during pre-index validation:

```powershell
py -3.12 -m app.rag.cli index --source data/filtered
py -3.12 -m app.rag.cli index --source data/filtered --rebuild
```

## Evaluation

The committed evaluation dataset has 400 deterministic gold queries:

- 200 `product_knowledge`
- 200 `review_insight`

The latest committed reports compare vector-only and reranked retrieval. They are not a substitute for re-running
evaluation after the full index is built.

## Tests

Default tests do not call external model services and do not modify the production Chroma directory. Real smoke tests
are gated by environment variables.

```powershell
py -3.12 -m pytest -q
py -3.12 -m ruff check app tests scripts
py -3.12 -m compileall -q app tests scripts
```

## Known Limits Before Full Index

The current local Chroma state is partial. Full-index evaluation must be rerun after indexing all filtered records.
Gold query quality still benefits from human spot checks. Reranker latency is high and should stay conditional by
default.

## Unlisted-product peer-group path

The production unlisted-product analysis path is intentionally separate from the full-index workflow above:

1. Build `CandidateProductSignature` from candidate text, parameters, scenarios, target species/users, target price,
   and a verified vision summary when available.
2. Query the prepared catalog FTS using title/description/features/details and candidate hints. Category and price are
   auxiliary signals; no mandatory global category label is predicted or queried.
3. Rule-filter at most 300 candidates, embed only that bounded set, rerank at most 40, and accept only complete products
   meeting `config/peer_matching.yaml`. Never fill from below threshold; fewer than 10 yields
   `insufficient_peer_products`.
4. Seek selected reviews through the offset-only lookup, persist the small candidate/peer subset, and upsert the two
   small runtime Chroma collections.
5. Retrieve with `scope=peer_group`, then pass product evidence and review evidence separately to the two parallel
   analysis Agents.

The stable `peer_group_id` binds normalized candidate content (excluding temporary `product_id`), catalog source
signature, full matcher config/version, embedding model, and sorted accepted ASINs. It is an analysis-group identifier,
not a category label. This path must not invoke full-index CLI builds or modify an index being built elsewhere.
