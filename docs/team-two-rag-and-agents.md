# Team Two: RAG And Analysis Agents

## Architecture

Team two owns the evidence layer for `ProductMarketAgent` and `UserInsightAgent`.
The workflow remains:

`ProductProfile + RAG Evidence + StatisticsResult -> ProductMarketAgent / UserInsightAgent -> ProductMarketAnalysis / UserInsight`

The LangGraph topology and shared Pydantic contracts are unchanged. Demo mode keeps offline deterministic behavior for
tests. Real mode requires model configuration and `RAG_USE_CHROMA=true`; otherwise it returns an explicit service error
instead of falling back to Demo.

## Data Flow

1. `python -m app.rag.cli validate --source data/filtered` profiles source files.
2. `python -m app.rag.cli index --source data/filtered` converts rows into `KnowledgeDocument` chunks.
3. Chroma stores two isolated collections: `product_knowledge` and `review_insight`.
4. Workflow retrieval creates `EvidenceReference` records with source file, source row, content hash, query, collection,
   and retrieval score.
5. The two analysis agents validate model output and remove any evidence ID that was not supplied in the prompt.

## data/filtered Mapping

Actual files detected:

| File | Records | Collection | Key Fields |
| --- | ---: | --- | --- |
| `meta_pet_supplies_prefiltered.jsonl` | 161,540 | `product_knowledge` | `parent_asin`, `title`, `features`, `description`, `price`, `average_rating`, `rating_number`, `categories`, `details` |
| `pet_supplies_reviews_prefiltered.jsonl` | 594,175 | `review_insight` | `parent_asin`, `asin`, `user_id`, `timestamp`, `rating`, `title`, `text`, `verified_purchase`, `helpful_vote` |

`parent_asin` is mapped to the stable TradePilot `product_id` with the same UUID5 rule used by the pet-supplies import
script.

## Chunking

Product records become structured text sections: title, category path, brand/store, price, rating summary, feature
bullets, description, and product parameters. Product chunks are paragraph-aware and avoid splitting parameter labels
from values.

Reviews keep one user's review as one document unless it is too long, in which case it is split by paragraph. Reviews
are never merged across users.

## Metadata

Every chunk carries scalar Chroma metadata:

`document_id`, `chunk_id`, `parent_id`, `chunk_index`, `content_hash`, `source_file`, `source_locator`, `source_row`,
`knowledge_type`, `data_origin=real`, `is_demo=false`, `product_id`, `parent_asin`, `asin`, `product_name`,
`category`, `brand`, `marketplace`, `target_market`, `language`, and collection-specific fields such as `rating`,
`review_id`, `review_title`, `verified_purchase`, `listed_price`, and `currency`.

## Environment

Required for Real mode:

```powershell
$env:OPENAI_BASE_URL="https://api.siliconflow.com/v1"
$env:OPENAI_API_KEY="<local secret>"
$env:MODEL_ANALYSIS="deepseek-ai/DeepSeek-V4-Pro"
$env:MODEL_FAST="deepseek-ai/DeepSeek-V4-Pro"
$env:EMBEDDING_MODEL="BAAI/bge-m3"
$env:RERANK_MODEL="BAAI/bge-reranker-v2-m3"
$env:RAG_USE_CHROMA="true"
```

Optional tuning: `MODEL_TEMPERATURE`, `MODEL_TIMEOUT_SECONDS`, `MODEL_MAX_RETRIES`, `RAG_FETCH_K`, `RAG_TOP_K`,
`RAG_SCORE_THRESHOLD`, `RAG_BATCH_SIZE`, `RAG_CHUNK_SIZE`, and `RAG_CHUNK_OVERLAP`.

## Commands

```powershell
py -3.12 -m app.rag.cli validate --source data/filtered
py -3.12 -m app.rag.cli index --source data/filtered
py -3.12 -m app.rag.cli index --source data/filtered --rebuild
py -3.12 -m app.rag.cli status
py -3.12 -m app.rag.cli query --collection product_knowledge --product-id <product_id> --query "main functions and risks"
py -3.12 -m app.rag.cli evaluate --output-dir data/reports/rag_eval
```

For offline development and CI, add `--offline-embeddings` to use deterministic local embeddings without network calls.

## Incremental Updates

Chunk IDs are stable UUID5 values derived from source identity, chunk index, and content hash. Re-indexing performs
Chroma upserts and skips unchanged chunks when `content_hash` matches. `--rebuild` clears both collections first.
A file lock under the Chroma directory prevents two index jobs from running at the same time.

## Agent Behavior

`ProductMarketAgent` uses product evidence plus `StatisticsResult`. It may summarize functions, parameters, scenarios,
advantages, risks, and market fit. Exact price, rating, count, and ratio claims must come from `StatisticsResult` or
user-provided product fields.

`UserInsightAgent` uses review evidence plus `StatisticsResult`. It may identify sample-level motivations, scenarios,
positive concerns, pain points, and improvement requests. It cannot turn a single review into a market-wide trend.

Both agents use strict prompts, parse JSON, validate with existing Pydantic schemas, remove invented evidence IDs, and
return `insufficient_evidence` with `data_gaps` when evidence is missing.

## Evaluation

The deterministic evaluator builds sanity queries from indexed documents and reports Hit@1, Hit@3, Hit@5, MRR, empty
retrieval rate, duplicate result rate, metadata filter accuracy, average latency, and P95 latency. Sample run on the
local test index:

| Collection | Hit@1 | Hit@3 | Hit@5 | MRR | Empty | Duplicate | Filter Accuracy | Avg ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `product_knowledge` | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 | 109.3 | 177.7 |
| `review_insight` | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 1.000 | 3.8 | 5.4 |

## Boundaries

Team one owns SQL statistics and the `StatisticsResult` values. Team two consumes those values and does not derive exact
numeric market facts from RAG excerpts. Team three consumes `ProductMarketAnalysis` and `UserInsight`; it should not
expect hidden fields outside the existing schemas.

## Known Data Gaps

The filtered source has no explicit marketplace column, so the adapter marks records as `amazon_us`. Review language is
not provided and is currently marked `en` for this filtered corpus. Reranker configuration is present, but the current
implementation uses vector ranking plus deterministic deduplication unless a future reranker client is added.
