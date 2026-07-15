from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableSequence

from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import ProductMarketAgentInput
from app.agents.model_factory import create_analysis_model, parse_json_object
from app.core.enums import AgentStatus, DataOrigin
from app.schemas.analysis import ProductMarketAnalysis
from app.schemas.common import Conclusion, DataGap
from app.schemas.evidence import EvidenceReference

PRODUCT_MARKET_SYSTEM_PROMPT = """
You are TradePilot ProductMarketAgent.
Use only the supplied ProductProfile, StatisticsResult, and EvidenceReference list.
Do not invent market size, sales, ratings, prices, ratios, or evidence IDs.
Exact numeric facts must come from StatisticsResult or user provided product fields.
Every factual conclusion must cite existing evidence_ids. If evidence is missing, use unknown and data_gaps.
Return only a JSON object matching this schema shape:
{{"status":"succeeded|insufficient_evidence","data_origin":"real|demo|user","product_summary":"...","conclusions":[{{"conclusion":"...","conclusion_type":"...","confidence":0.0,"evidence_ids":["..."],"data_gaps":[]}}],"evidence_ids":["..."],"data_gaps":[]}}
"""


class ProductMarketAgent(BaseScaffoldAgent[ProductMarketAgentInput, ProductMarketAnalysis]):
    """Evidence-grounded product and market analysis agent."""

    input_model = ProductMarketAgentInput
    output_model = ProductMarketAnalysis

    def __init__(self, model: BaseChatModel | None = None) -> None:
        self.model = model
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PRODUCT_MARKET_SYSTEM_PROMPT),
                (
                    "human",
                    "ProductProfile:\n{product}\n\nStatisticsResult:\n{statistics}\n\nEvidence:\n{evidence}\n",
                ),
            ]
        )
        self.chain: RunnableSequence = (
            RunnableLambda(self._validate_input)
            | RunnableLambda(self._run_analysis)
            | RunnableLambda(self._validate_output)
        )

    def _run_analysis(self, context: ProductMarketAgentInput) -> ProductMarketAnalysis:
        evidence_ids = [item.evidence_id for item in context.evidence]
        if context.product.data_origin is DataOrigin.REAL:
            model = self.model or create_analysis_model()
            payload = self._prompt_payload(context)
            message = (self.prompt | model).invoke(payload)
            parsed = parse_json_object(str(message.content))
            return self._postprocess(parsed, context)
        return self._deterministic_analysis(context, evidence_ids)

    def _run_stub(self, context: ProductMarketAgentInput) -> ProductMarketAnalysis:
        return self._run_analysis(context)

    def _deterministic_analysis(
        self,
        context: ProductMarketAgentInput,
        evidence_ids: list[str],
    ) -> ProductMarketAnalysis:
        gaps: list[DataGap] = []
        status = AgentStatus.SUCCEEDED if evidence_ids else AgentStatus.INSUFFICIENT_EVIDENCE
        if not evidence_ids:
            gaps.append(
                DataGap(
                    code="no_rag_evidence",
                    field="product_knowledge",
                    reason="No product knowledge evidence was supplied.",
                    required_for="product and market analysis",
                )
            )
        gaps.extend(self._base_gaps(context))
        summary_parts = [
            f"Product: {context.product.name}",
            f"Category: {context.product.category}",
            f"Target market: {context.product.target_market or 'unknown'}",
        ]
        if context.product.features:
            summary_parts.append("Known features: " + "; ".join(context.product.features[:5]))
        if context.statistics.metrics:
            metrics = ", ".join(f"{key}={value}" for key, value in sorted(context.statistics.metrics.items()))
            summary_parts.append(f"Statistics: {metrics}")
        conclusions = [
            Conclusion(
                conclusion=(
                    "Product analysis is grounded in the provided product profile, "
                    "statistics, and retrieved product evidence."
                ),
                conclusion_type="product_market_scope",
                confidence=0.75 if evidence_ids else 0.35,
                evidence_ids=evidence_ids[:5],
                data_gaps=[] if evidence_ids else gaps,
            )
        ]
        return ProductMarketAnalysis(
            status=status,
            data_origin=context.product.data_origin,
            evidence_ids=evidence_ids,
            data_gaps=gaps,
            conclusions=conclusions,
            product_summary="\n".join(summary_parts),
        )

    def _prompt_payload(self, context: ProductMarketAgentInput) -> dict[str, str]:
        return {
            "product": context.product.model_dump_json(indent=2),
            "statistics": context.statistics.model_dump_json(indent=2),
            "evidence": self._format_evidence(context.evidence),
        }

    @staticmethod
    def _format_evidence(evidence: list[EvidenceReference]) -> str:
        lines = []
        for item in evidence[:10]:
            lines.append(
                "\n".join(
                    [
                        f"evidence_id: {item.evidence_id}",
                        f"source: {item.source_name}",
                        f"score: {item.metadata.get('retrieval_score', 'unknown')}",
                        f"excerpt: {item.excerpt[:1200]}",
                    ]
                )
            )
        return "\n\n".join(lines) or "[]"

    def _postprocess(self, payload: dict[str, Any], context: ProductMarketAgentInput) -> ProductMarketAnalysis:
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
                    code="no_product_knowledge_evidence",
                    field="product_knowledge",
                    reason="No valid product knowledge evidence was available.",
                    required_for="product and market analysis",
                )
            )
            payload["status"] = AgentStatus.INSUFFICIENT_EVIDENCE
        payload["data_gaps"] = [*payload.get("data_gaps", []), *[gap.model_dump() for gap in gaps]]
        return ProductMarketAnalysis.model_validate(payload)

    @staticmethod
    def _base_gaps(context: ProductMarketAgentInput) -> list[DataGap]:
        gaps = list(context.statistics.data_gaps)
        if context.statistics.status is AgentStatus.INSUFFICIENT_EVIDENCE:
            gaps.append(
                DataGap(
                    code="statistics_insufficient",
                    field="statistics",
                    reason=(
                        "StatisticsResult is insufficient; exact prices, counts, "
                        "ratings, and ratios remain unknown."
                    ),
                    required_for="numeric market analysis",
                )
            )
        return gaps
