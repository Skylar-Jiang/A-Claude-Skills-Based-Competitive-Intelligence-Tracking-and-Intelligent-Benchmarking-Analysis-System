from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import ProductMarketAgentInput
from app.core.enums import AgentStatus, DataOrigin
from app.schemas.analysis import ProductMarketAnalysis
from app.schemas.common import DataGap


class ProductMarketAgent(BaseScaffoldAgent[ProductMarketAgentInput, ProductMarketAnalysis]):
    """Scaffold only; real market analysis is intentionally deferred to teammate two."""

    input_model = ProductMarketAgentInput
    output_model = ProductMarketAnalysis

    def _run_stub(self, context: ProductMarketAgentInput) -> ProductMarketAnalysis:
        evidence_ids = [item.evidence_id for item in context.evidence]
        gaps = []
        status = AgentStatus.SUCCEEDED
        if not evidence_ids:
            status = AgentStatus.INSUFFICIENT_EVIDENCE
            gaps.append(
                DataGap(
                    code="no_rag_evidence",
                    field="product_knowledge",
                    reason="No product knowledge evidence was supplied to the scaffold agent.",
                    required_for="real product and market analysis",
                )
            )
        # TODO(team-two): replace this deterministic result with evidence-grounded analysis.
        return ProductMarketAnalysis(
            status=status,
            data_origin=DataOrigin.DEMO,
            evidence_ids=evidence_ids,
            data_gaps=gaps,
            product_summary="DEMO scaffold executed; product and market analysis is not implemented.",
        )
