# RAG Index Spec

Machine-readable spec: `config/rag_index_spec.json`.

## Frozen Version

- index_version: `tradepilot-pet-supplies-qwen3-embedding-v2`
- embedding_model: `Qwen/Qwen3-Embedding-0.6B`
- product_collection: `product_knowledge`
- review_collection: `review_insight`
- product_document_template_version: `product-template-v2`
- review_document_template_version: `review-template-v1`
- chunk_config_version: `rag-chunk-v1`
- metadata_schema_version: `metadata-v2`
- stable_id_version: `uuid5-source-parent-chunk-v1`
- content_hash_version: `sha256-v1`
- normalizer_version: `unicode-html-whitespace-v1`
- importer_version: `filtered-jsonl-adapter-v2`
- data_adapter_version: `pet-supplies-filtered-v1`

## Required Metadata

Every indexed chunk must include scalar Chroma metadata for:

`document_id`, `chunk_id`, `parent_id`, `chunk_index`, `content_hash`, `source_file`, `source_locator`,
`source_row`, `knowledge_type`, `data_origin`, `is_demo`, `product_id`, and `parent_asin`.

Product records additionally preserve category, brand/store, price, rating, rating number, title, and product
parameters when available.

Review records additionally preserve `review_id`, `asin`, `rating`, `review_date`, `verified_purchase`,
`helpful_vote`, and `review_title` when available.

## ID And Hash Rules

Stable IDs use UUID5 over source identity, parent identity, chunk index, and content hash. Content hashes use SHA-256
over cleaned chunk text. Evidence IDs in the runtime pipeline add stable prefixes:

- `RAG-PRODUCT-<chunk-id>`
- `RAG-REVIEW-<chunk-id>`

## Rebuild Triggers

Full rebuild is required when any of these change:

- embedding model
- embedding dimension
- collection name
- chunk config version
- document template version
- stable ID version
- content hash version
- breaking metadata schema

Incremental update is allowed for new source rows, changed source row content with the same hash algorithm, and
non-breaking metadata additions.

## Pre-Index Checks

These commands are read-only and do not embed or mutate production Chroma:

```powershell
py -3.12 -m app.rag.cli doctor
py -3.12 -m app.rag.cli plan-index --source data/filtered
py -3.12 -m app.rag.cli status
```

`doctor` compares runtime settings, Chroma collection metadata, and `config/rag_index_spec.json`.

`plan-index` scans source files and estimates product/review rows and chunks. It does not call embedding APIs and does
not write Chroma.
