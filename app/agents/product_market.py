from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableSequence

from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import ProductMarketAgentInput
from app.agents.model_factory import (
    create_analysis_model,
    normalize_evidence_ids,
    normalize_model_data_gaps,
    normalize_text_list,
    parse_json_object,
)
from app.core.enums import AgentStatus, DataMode, DataOrigin, ImplementationStatus
from app.rag.pipeline import RetrievalPipeline, user_provided_evidence
from app.schemas.analysis import ProductMarketAnalysis
from app.schemas.common import Conclusion, DataGap
from app.schemas.evidence import EvidenceReference

PRODUCT_MARKET_SYSTEM_PROMPT = """
You are TradePilot ProductMarketAgent.
Use only the supplied ProductProfile, StatisticsResult, and EvidenceReference list.
Do not invent market size, sales, ratings, prices, ratios, or evidence IDs.
Exact numeric facts must come from StatisticsResult or user provided product fields.
Every factual conclusion must cite existing evidence_ids. If evidence is missing, use unknown and data_gaps.
The ProductProfile is an unlisted new product. Evidence describes listed peer products, never the new product's own
sales, ratings, or reviews. Cover price, feature/parameter baseline, structure/use scenarios, brand positioning,
ratings and rating counts, homogenization, differentiation, missing parameters, and pre-launch validation risks.
Attribute-only hypotheses must begin with "待验证假设" and must not be stated as review or market facts.
Return only a JSON object matching this schema shape:
{{"status":"succeeded|insufficient_evidence","product_summary":"...","price_analysis":"...","feature_baseline":[],"structure_and_scenarios":[],"brand_positioning":[],"rating_analysis":"...","homogenization_risks":[],"differentiation_opportunities":[],"missing_parameters":[],"prelaunch_validations":[],"reasoned_hypotheses":[],"conclusions":[{{"conclusion":"...","conclusion_type":"market_fact|product_fact|recommendation|reasoned_hypothesis","confidence":0.0,"evidence_ids":["..."],"data_gaps":[]}}],"evidence_ids":["..."],"data_gaps":[]}}
"""


class ProductMarketAgent(BaseScaffoldAgent[ProductMarketAgentInput, ProductMarketAnalysis]):
    """Evidence-grounded product and market analysis agent."""

    input_model = ProductMarketAgentInput
    output_model = ProductMarketAnalysis

    def __init__(
        self,
        model: BaseChatModel | None = None,
        *,
        retrieval_pipeline: RetrievalPipeline | None = None,
        constraints: dict[str, Any] | None = None,
        deep_retrieval: bool = False,
    ) -> None:
        self.model = model
        self.retrieval_pipeline = retrieval_pipeline
        self.constraints = constraints or {}
        self.deep_retrieval = deep_retrieval
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PRODUCT_MARKET_SYSTEM_PROMPT),
                (
                    "human",
                    "ProductProfile:\n{product}\n\nPeerGroupContext:\n{peer_context}\n\n"
                    "ProductBackgroundContext:\n{background}\n\nStatisticsResult:\n{statistics}\n\n"
                    "Evidence:\n{evidence}\n",
                ),
            ]
        )
        self.chain: RunnableSequence = (
            RunnableLambda(self._validate_input)
            | RunnableLambda(self._with_optional_exact_product_retrieval)
            | RunnableLambda(self._run_analysis)
            | RunnableLambda(self._validate_output)
        )

    def _with_optional_exact_product_retrieval(
        self, context: ProductMarketAgentInput
    ) -> ProductMarketAgentInput:
        if (
            self.retrieval_pipeline is None
            or context.peer_group_id
            or context.evidence
            or context.product.data_origin is not DataOrigin.REAL
        ):
            return context
        bundle = self.retrieval_pipeline.retrieve_product_evidence(
            context.product,
            {**self.constraints, **context.user_constraints},
            deep=self.deep_retrieval,
        )
        return context.model_copy(
            update={"evidence": [user_provided_evidence(context.product), *bundle.evidence]}
        )

    def _run_analysis(self, context: ProductMarketAgentInput) -> ProductMarketAnalysis:
        evidence_ids = [item.evidence_id for item in context.evidence]
        if context.product.data_mode is DataMode.REAL or context.product.data_origin is DataOrigin.REAL:
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
            peer_group_id=context.peer_group_id,
            selected_parent_asins=context.selected_parent_asins,
            evidence_ids=evidence_ids,
            evidence_references=self._evidence_refs(context.evidence),
            statistics_result_ids=self._statistics_ids(context),
            data_gaps=gaps,
            conclusions=conclusions,
            product_summary="\n".join(summary_parts),
        )

    def _prompt_payload(self, context: ProductMarketAgentInput) -> dict[str, str]:
        return {
            "product": context.product.model_dump_json(indent=2),
            "peer_context": self._peer_context(context),
            "background": (
                context.background_context.model_dump_json(indent=2)
                if context.background_context
                else "null"
            ),
            "statistics": context.statistics.model_dump_json(indent=2),
            "evidence": self._format_evidence(context.evidence),
        }

    @staticmethod
    def _peer_context(context: ProductMarketAgentInput) -> str:
        peers = [
            {
                key: peer.get(key)
                for key in (
                    "peer_product_id",
                    "parent_asin",
                    "match_score",
                    "title",
                    "features",
                    "price",
                    "average_rating",
                    "rating_number",
                )
            }
            for peer in context.selected_peer_products
        ]
        return str(
            {
                "peer_group_id": context.peer_group_id,
                "selected_parent_asins": context.selected_parent_asins,
                "selected_peer_products": peers,
            }
        )

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
                        f"excerpt: {item.excerpt[:800]}",
                    ]
                )
            )
        return "\n\n".join(lines) or "[]"

    def _postprocess(self, payload: dict[str, Any], context: ProductMarketAgentInput) -> ProductMarketAnalysis:
        payload = normalize_model_data_gaps(payload, field="peer_product_market")
        allowed_ids = {item.evidence_id for item in context.evidence}
        payload["data_origin"] = context.product.data_origin
        payload["peer_group_id"] = context.peer_group_id
        payload["selected_parent_asins"] = context.selected_parent_asins
        payload["implementation_status"] = ImplementationStatus.PRODUCTION
        payload["scaffold_note"] = ""
        payload["evidence_ids"] = normalize_evidence_ids(
            payload.get("evidence_ids", []), allowed_ids=allowed_ids
        )
        payload["status"] = (
            AgentStatus.SUCCEEDED if payload["evidence_ids"] else AgentStatus.INSUFFICIENT_EVIDENCE
        )
        cleaned_conclusions = []
        for conclusion in payload.get("conclusions", []) if isinstance(payload.get("conclusions"), list) else []:
            if not isinstance(conclusion, dict):
                continue
            if not str(conclusion.get("conclusion", "")).strip():
                continue
            conclusion["evidence_ids"] = normalize_evidence_ids(
                conclusion.get("evidence_ids", []), allowed_ids=allowed_ids
            )
            conclusion.setdefault(
                "conclusion_type", "evidence_summary" if conclusion["evidence_ids"] else "recommendation"
            )
            conclusion.setdefault("confidence", 0.65 if conclusion["evidence_ids"] else 0.35)
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
        for field in (
            "feature_baseline",
            "structure_and_scenarios",
            "brand_positioning",
            "homogenization_risks",
            "differentiation_opportunities",
            "missing_parameters",
            "prelaunch_validations",
            "reasoned_hypotheses",
        ):
            payload[field] = normalize_text_list(payload.get(field, []))
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
        payload["evidence_references"] = self._evidence_refs(context.evidence)
        payload["statistics_result_ids"] = self._statistics_ids(context)
        payload["reasoned_hypotheses"] = [
            item if str(item).startswith("待验证假设") else f"待验证假设（非用户评论结论、非市场统计事实）：{item}"
            for item in payload.get("reasoned_hypotheses", [])
        ]
        return ProductMarketAnalysis.model_validate(payload)

    @staticmethod
    def _statistics_ids(context: ProductMarketAgentInput) -> list[str]:
        return [item for item in [context.statistics.result_id, *context.statistics.evidence_ids] if item]

    @staticmethod
    def _evidence_refs(evidence: list[EvidenceReference]) -> list[dict[str, Any]]:
        return [
            {
                "evidence_id": item.evidence_id,
                "evidence_type": item.evidence_type,
                "source_name": item.source_name,
                "source_file": item.metadata.get("source_file"),
                "source_locator": item.metadata.get("source_locator"),
                "collection": item.metadata.get("collection"),
                "content_hash": item.metadata.get("content_hash"),
                "vector_score": item.metadata.get("vector_score", item.metadata.get("retrieval_score")),
                "rerank_score": item.metadata.get("rerank_score"),
                "query": item.metadata.get("query"),
            }
            for item in evidence
        ]

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
