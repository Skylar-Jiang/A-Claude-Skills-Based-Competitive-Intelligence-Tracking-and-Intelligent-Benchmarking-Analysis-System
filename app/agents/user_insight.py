from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import UserInsightAgentInput
from app.core.enums import AgentStatus, DataOrigin
from app.schemas.analysis import UserInsight
from app.schemas.common import DataGap


class UserInsightAgent(BaseScaffoldAgent[UserInsightAgentInput, UserInsight]):
    """Scaffold only; real review insight is intentionally deferred to teammate two."""

    input_model = UserInsightAgentInput
    output_model = UserInsight

    def _run_stub(self, context: UserInsightAgentInput) -> UserInsight:
        evidence_ids = [item.evidence_id for item in context.evidence]
        gaps = []
        status = AgentStatus.SUCCEEDED
        if not evidence_ids:
            status = AgentStatus.INSUFFICIENT_EVIDENCE
            gaps.append(
                DataGap(
                    code="no_rag_evidence",
                    field="review_insight",
                    reason="No review evidence was supplied to the scaffold agent.",
                    required_for="real user insight analysis",
                )
            )
        # TODO(team-two): add review retrieval and validated insight generation.
        return UserInsight(
            status=status,
            data_origin=DataOrigin.DEMO,
            evidence_ids=evidence_ids,
            data_gaps=gaps,
            insight_summary="DEMO scaffold executed; user insight analysis is not implemented.",
        )
