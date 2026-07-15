# File structure

```text
app/
  agents/          Four LCEL Agents, provider factories, prompts, validation and evidence audit
  api/v1/          Formal FastAPI router, metadata/SSE/report endpoints
  background/      Optional traceable product-background provider contract and registry
  domain/          Candidate signature, peer matching, product catalog, review lookup, offline/online boundary
  rag/             exact_product/peer_group contracts, Chroma/memory stores, embeddings
  schemas/         Pydantic product, evidence, vision, Agent, report and API models
  services/        Product, peer group, vision, async dispatcher, report support and conversation services
  statistics/      Statistics contract plus real pet-supplies peer-group provider
  workflows/       TradePilotState and the fan-out/fan-in LangGraph
config/
  peer_matching.yaml
data/filtered/      Git LFS real source JSONL files
data/demo/          Ignored caches, runtime SQLite/Chroma, uploads and reports
docs/               Architecture, contracts, operation, testing and handover
migrations/         Alembic schema history
scripts/            DB, explicit peer preparation, legacy exact subset and smoke commands
tests/              Unit, integration, contract, real-data and opt-in real-model checks
```

`app/demo_subset.py` and the `exact_product` retrieval scope remain for backward compatibility. The Real unlisted
product main chain uses `app/domain/peer_data.py`, `PeerGroupService`, and `peer_group` retrieval.
`scripts/smoke_multi_product_matching.py` validates ten terminal-product types without building a global classifier;
`scripts/real_http_e2e.py` exercises the deployed HTTP contract and real providers.
