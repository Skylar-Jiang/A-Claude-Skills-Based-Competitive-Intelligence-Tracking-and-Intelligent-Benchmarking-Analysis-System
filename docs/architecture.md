# Architecture

The only backend package is `app/`, and `app/main.py` is the only FastAPI entry point. Transport
calls services, services call repository ports and the workflow, and Agents never receive a database
session.

```mermaid
flowchart LR
    API["FastAPI /api/v1"] --> S["Services"]
    S --> DB["Repository ports / SQLAlchemy / SQLite"]
    S --> G["LangGraph StateGraph"]
    G --> N["InputValidator -> ProductNormalizer"]
    N --> ST["StatisticsProvider"]
    ST --> PM["ProductMarketAgent LCEL + RetrievalPipeline"]
    ST --> UI["UserInsightAgent LCEL + RetrievalPipeline"]
    PM --> OD["OperationsDecisionAgent"]
    UI --> OD
    OD --> EA["EvidenceAuditAgent"]
    EA -->|"at most one retry"| OD
    EA --> PE["PersistAndExport"]
    PE --> DB
    PE --> R["Demo JSON / Markdown"]
```

The two knowledge domains are `product_knowledge` and `review_insight`. Demo tests use an in-memory
store. Real mode uses `ChromaKnowledgeStore` through the shared `RetrievalPipeline`, which owns query
building, metadata filters, recall, deduplication, reranking, evidence binding, and sufficiency checks.

The composition root injects a `KnowledgeStore` factory and a session-scoped `StatisticsProvider`
factory. Domain seed entry points resolve a configured `DomainAdapter` through
`config/domain_profiles/`; no Agent receives a database session.
