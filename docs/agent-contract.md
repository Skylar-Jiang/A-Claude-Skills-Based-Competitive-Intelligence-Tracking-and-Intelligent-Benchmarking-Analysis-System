# Agent contract

Every Agent has its own input model, output model, file, LCEL `RunnableSequence`, and LangGraph node.
All inputs and outputs are validated by Pydantic v2.

| Agent | Output | Current behavior | Future owner |
| --- | --- | --- | --- |
| ProductMarketAgent | `ProductMarketAnalysis` | Deterministic Demo scaffold or `insufficient_evidence` | Teammate two |
| UserInsightAgent | `UserInsight` | Deterministic Demo scaffold or `insufficient_evidence` | Teammate two |
| OperationsDecisionAgent | `OperationPlan` | Binds existing IDs and emits no business rules | Teammate three |
| EvidenceAuditAgent | `AuditResult` | Checks Demo/Scaffold markers only | Teammate three |

All four outputs include `data_origin=demo` and `implementation_status=scaffold`. No complete Prompt,
sentiment logic, market statistics, decision rules, marketing copy, or semantic audit exists here.
Agent contracts and the StateGraph field boundaries are the stable extension points.
