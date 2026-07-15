from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableSequence

from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import UserInsightAgentInput
from app.agents.model_factory import create_analysis_model, parse_json_object
from app.core.enums import AgentStatus, DataOrigin
from app.schemas.analysis import UserInsight
from app.schemas.common import Conclusion, DataGap
from app.schemas.evidence import EvidenceReference

USER_INSIGHT_SYSTEM_PROMPT = """
You are TradePilot UserInsightAgent.
Use only supplied review evidence, user input, ProductProfile, and StatisticsResult.
Do not describe an individual review as a market-wide trend.
"high frequency", "majority", ratios, average rating, and counts require StatisticsResult support.
If statistics are missing, say "appears in the retrieved sample" instead of making aggregate claims.
Do not infer sensitive identity attributes not explicitly present in reviews.
Every factual conclusion must cite existing evidence_ids; never invent evidence IDs.
Return only a JSON object matching this schema shape:
{{"status":"succeeded|insufficient_evidence","data_origin":"real|demo|user","insight_summary":"...","conclusions":[{{"conclusion":"...","conclusion_type":"...","confidence":0.0,"evidence_ids":["..."],"data_gaps":[]}}],"evidence_ids":["..."],"data_gaps":[]}}
"""


class UserInsightAgent(BaseScaffoldAgent[UserInsightAgentInput, UserInsight]):
    """Evidence-grounded user review insight agent."""

    input_model = UserInsightAgentInput
    output_model = UserInsight

    def __init__(self, model: BaseChatModel | None = None) -> None:
        self.model = model
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", USER_INSIGHT_SYSTEM_PROMPT),
                (
                    "human",
                    "ProductProfile:\n{product}\n\nStatisticsResult:\n{statistics}\n\nReview Evidence:\n{evidence}\n",
                ),
            ]
        )
        self.chain: RunnableSequence = (
            RunnableLambda(self._validate_input)
            | RunnableLambda(self._run_analysis)
            | RunnableLambda(self._validate_output)
        )

    def _run_analysis(self, context: UserInsightAgentInput) -> UserInsight:
        evidence_ids = [item.evidence_id for item in context.evidence]
        if context.product.data_origin is DataOrigin.REAL:
            model = self.model or create_analysis_model()
            message = (self.prompt | model).invoke(
                {
                    "product": context.product.model_dump_json(indent=2),
                    "statistics": context.statistics.model_dump_json(indent=2),
                    "evidence": self._format_evidence(context.evidence),
                }
            )
            return self._postprocess(parse_json_object(str(message.content)), context)
        return self._deterministic_analysis(context, evidence_ids)

    def _run_stub(self, context: UserInsightAgentInput) -> UserInsight:
        return self._run_analysis(context)

    def _deterministic_analysis(self, context: UserInsightAgentInput, evidence_ids: list[str]) -> UserInsight:
        gaps: list[DataGap] = []
        status = AgentStatus.SUCCEEDED if evidence_ids else AgentStatus.INSUFFICIENT_EVIDENCE
        if not evidence_ids:
            gaps.append(
                DataGap(
                    code="no_review_evidence",
                    field="review_insight",
                    reason="No review insight evidence was supplied.",
                    required_for="user insight analysis",
                )
            )
        gaps.extend(self._base_gaps(context))
        positive = [item for item in context.evidence if float(item.metadata.get("rating", 0) or 0) >= 4]
        negative = [item for item in context.evidence if 0 < float(item.metadata.get("rating", 0) or 0) <= 2]
        if context.evidence and (not positive or not negative):
            gaps.append(
                DataGap(
                    code="review_sentiment_coverage_limited",
                    field="review_insight",
                    reason="Retrieved review sample does not include both positive and negative low-rating evidence.",
                    required_for="balanced pain-point and benefit analysis",
                )
            )
        summary = (
            f"Retrieved review sample size: {len(context.evidence)}. "
            f"Positive sample evidence: {len(positive)}; negative sample evidence: {len(negative)}. "
            "Aggregate claims require StatisticsResult metrics."
        )
        conclusions = [
            Conclusion(
                conclusion="User insight is limited to the retrieved review sample and supplied statistics.",
                conclusion_type="review_sample_scope",
                confidence=0.72 if evidence_ids else 0.3,
                evidence_ids=evidence_ids[:5],
                data_gaps=[] if evidence_ids else gaps,
            )
        ]
        return UserInsight(
            status=status,
            data_origin=context.product.data_origin,
            evidence_ids=evidence_ids,
            data_gaps=gaps,
            conclusions=conclusions,
            insight_summary=summary,
        )

    @staticmethod
    def _format_evidence(evidence: list[EvidenceReference]) -> str:
        lines = []
        for item in evidence[:12]:
            lines.append(
                "\n".join(
                    [
                        f"evidence_id: {item.evidence_id}",
                        f"rating: {item.metadata.get('rating', 'unknown')}",
                        f"verified_purchase: {item.metadata.get('verified_purchase', 'unknown')}",
                        f"source: {item.source_name}",
                        f"excerpt: {item.excerpt[:1200]}",
                    ]
                )
            )
        return "\n\n".join(lines) or "[]"

    def _postprocess(self, payload: dict[str, Any], context: UserInsightAgentInput) -> UserInsight:
        allowed_ids = {item.evidence_id for item in context.evidence}
        payload["data_origin"] = context.product.data_origin
        payload["evidence_ids"] = [item for item in payload.get("evidence_ids", []) if item in allowed_ids]
        payload["status"] = payload.get("status") or (
            AgentStatus.SUCCEEDED if payload["evidence_ids"] else AgentStatus.INSUFFICIENT_EVIDENCE
        )
        cleaned_conclusions = []
        for conclusion in payload.get("conclusions", []):
            if not isinstance(conclusion, dict):
                continue
            conclusion["evidence_ids"] = [item for item in conclusion.get("evidence_ids", []) if item in allowed_ids]
            if not conclusion["evidence_ids"]:
                conclusion.setdefault("data_gaps", []).append(
                    {
                        "code": "claim_without_valid_evidence",
                        "field": "evidence_ids",
                        "reason": "The model returned no valid supplied evidence_id for this conclusion.",
                        "required_for": "fact validation",
                    }
                )
            cleaned_conclusions.append(conclusion)
        payload["conclusions"] = cleaned_conclusions
        gaps = self._base_gaps(context)
        if not context.evidence:
            gaps.append(
                DataGap(
                    code="no_review_evidence",
                    field="review_insight",
                    reason="No valid review evidence was available.",
                    required_for="user insight analysis",
                )
            )
            payload["status"] = AgentStatus.INSUFFICIENT_EVIDENCE
        payload["data_gaps"] = [*payload.get("data_gaps", []), *[gap.model_dump() for gap in gaps]]
        return UserInsight.model_validate(payload)

    @staticmethod
    def _base_gaps(context: UserInsightAgentInput) -> list[DataGap]:
        gaps = list(context.statistics.data_gaps)
        if context.statistics.status is AgentStatus.INSUFFICIENT_EVIDENCE:
            gaps.append(
                DataGap(
                    code="statistics_insufficient",
                    field="statistics",
                    reason=(
                        "StatisticsResult is insufficient; aggregate review counts, "
                        "ratings, and proportions remain unknown."
                    ),
                    required_for="quantified user insight",
                )
            )
        return gaps
