# Agent contract

Every Agent has its own Pydantic input/output, LCEL sequence, model-backed Real path, deterministic Demo compatibility
path, and LangGraph node.

| Agent | Real provider | Evidence scope | Output responsibility |
| --- | --- | --- | --- |
| ProductMarketAgent | DeepSeek | candidate profile, peer products, SQL statistics | price plus features, structure, positioning, ratings, homogenization, differentiation, missing parameters, validations |
| UserInsightAgent | DeepSeek | peer reviews and sample boundary | needs, positives, pains, purchase factors, use/maintenance concerns, validations, opportunities, limitations |
| OperationsDecisionAgent | Qwen | validated parallel outputs and existing evidence IDs | positioning, evidence-bound conclusions, launch actions |
| EvidenceAuditAgent | Qwen plus deterministic guards | plan, all carried evidence, SQL statistics, expected peer group | attribution, scope, accessory, numeric, hypothesis, ID, conflict, and risk checks |

Real outputs use `implementation_status=production`. Model JSON is parsed and normalized before Pydantic validation;
unknown evidence IDs are removed, invalid status prose is converted from the actual valid-evidence boundary, and
unsupported numeric values are replaced with an explicit pending-validation marker. Model audit findings are advisory;
deterministic checks alone decide blocking rejection and manual review.

ProductMarketAgent and UserInsightAgent receive the same `peer_group_id` and selected ASIN set and run in parallel.
No Agent may call the database or claim peer reviews belong to the candidate product.
