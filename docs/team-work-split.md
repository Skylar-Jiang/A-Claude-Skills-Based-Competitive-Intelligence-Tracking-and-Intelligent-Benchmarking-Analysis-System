# Team work split

## Teammate one: domain data and statistics

Own real domain selection, `DomainAdapter` implementations, import/cleaning scripts, SQL statistics,
and source provenance. Start at `app/adapters/base.py`, `app/adapters/domains/`, database models and
repository protocols. Do not bypass the mode/origin fields.

## Teammate two: analysis Agents and RAG

Own ProductMarketAgent, UserInsightAgent, the `product_knowledge` and `review_insight` corpora,
retrieval quality, evidence-grounded structured outputs, and later model chains. Start at
`app/agents/product_market.py`, `app/agents/user_insight.py`, and `app/rag/`.

## Teammate three: decisions, audit, content, reports, frontend

Own OperationsDecisionAgent, EvidenceAuditAgent, bounded correction detail, OperationContentSkill,
report refinement, and the later frontend. Start at `app/agents/operations_decision.py`,
`app/agents/evidence_audit.py`, `app/skills/operation_content/`, and `app/services/report_exporter.py`.

This refactor deliberately did not complete any of those business implementations.
