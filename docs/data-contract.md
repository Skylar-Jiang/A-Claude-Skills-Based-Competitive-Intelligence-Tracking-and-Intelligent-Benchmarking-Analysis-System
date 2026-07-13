# Data contract

SQLAlchemy creates eleven baseline tables: `products`, `product_files`, `competitor_offers`,
`reviews`, `knowledge_sources`, `analysis_runs`, `agent_outputs`, `evidence_references`, `reports`,
`conversations`, and `messages`. Domain-specific product fields belong in `attributes_json` or
`metadata_json`; the scaffold intentionally has no domain migrations or analytical SQL.

Mode and origin are independent and explicit:

| Value | Meaning |
| --- | --- |
| `demo` | Bundled deterministic fixtures, always visibly marked |
| `mock` | Test/simulation boundary; analysis is not implemented in this phase |
| `real` | Real external/model execution; never falls back |
| `user` | User-supplied source origin, used for Real product profiles |

Exact prices, ratings, counts, and ratios may only enter conclusions from user input, SQL,
Repository, or a future StatisticsTool. RAG excerpts are evidence text, not a numeric authority.
