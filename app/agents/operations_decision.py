from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import OperationsDecisionAgentInput
from app.core.enums import AgentStatus, DataOrigin
from app.schemas.analysis import OperationPlan


class OperationsDecisionAgent(BaseScaffoldAgent[OperationsDecisionAgentInput, OperationPlan]):
    """Scaffold only; operational decision rules are deferred to teammate three."""

    input_model = OperationsDecisionAgentInput
    output_model = OperationPlan

    def _run_stub(self, context: OperationsDecisionAgentInput) -> OperationPlan:
        evidence_ids = sorted(
            set(context.product_market_analysis.evidence_ids + context.user_insight.evidence_ids)
        )
        # TODO(team-three): implement decision logic without changing this contract.
        return OperationPlan(
            status=AgentStatus.SUCCEEDED,
            data_origin=DataOrigin.DEMO,
            evidence_ids=evidence_ids,
            positioning="DEMO scaffold only; operational positioning is not implemented.",
            next_steps=["Hand off to teammate three for real decision logic."],
        )
