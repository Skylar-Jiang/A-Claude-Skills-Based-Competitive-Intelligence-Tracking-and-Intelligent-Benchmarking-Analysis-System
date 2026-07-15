from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel, RunnableSequence

from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import ProductMarketAgentInput
from app.agents.model_factory import create_analysis_model, parse_json_object
from app.core.enums import AgentStatus, DataOrigin
from app.rag.pipeline import RetrievalBundle, RetrievalPipeline, user_provided_evidence
from app.schemas.analysis import ProductMarketAnalysis
from app.schemas.common import Conclusion, DataGap
from app.schemas.evidence import EvidenceReference

PRODUCT_MARKET_SYSTEM_PROMPT = """
You are TradePilot ProductMarketAgent.
Use only the supplied ProductProfile, User Constraints, StatisticsResult, and EvidenceReference list.
Do not invent market size, sales, market share, ratings, prices, counts, ratios, or evidence IDs.
Exact numeric facts must come from StatisticsResult or user_provided product fields.
Every factual conclusion must cite existing evidence_ids, statistics result IDs, or user_provided.
If evidence is missing, use unknown, data_gaps, missing_evidence_types, or unverifiable_claims.
Do not claim competitor leadership, lower price, or category superiority without supplied competitor evidence.
Return only a JSON object matching ProductMarketAnalysis. Do not output text outside JSON.
"""


class ProductMarketAgent(BaseScaffoldAgent[ProductMarketAgentInput, ProductMarketAnalysis]):
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
                    "ProductProfile:\n{product}\n\n"
                    "StatisticsResult:\n{statistics}\n\n"
                    "Evidence:\n{evidence}\n",
                ),
            ]
        )
        self.chain: RunnableSequence = (
            RunnableLambda(self._validate_input)
            | RunnableParallel(
                {
                    "context": RunnableLambda(lambda context: context),
                    "retrieval": RunnableLambda(self._retrieve),
                }
            )
            | RunnableLambda(self._prepare_context)
            | RunnableLambda(self._run_analysis)
            | RunnableLambda(self._validate_output)
        )

    def _run_stub(self, context: ProductMarketAgentInput) -> ProductMarketAnalysis:
        return self._run_analysis(self._prepare_context({"context": context, "retrieval": None}))

    def _retrieve(self, context: ProductMarketAgentInput) -> RetrievalBundle | None:
        if self.retrieval_pipeline is None or context.product.data_origin is not DataOrigin.REAL:
            return None
        constraints = {**self.constraints, **context.user_constraints}
        return self.retrieval_pipeline.retrieve_product_evidence(
            context.product,
            constraints,
            deep=self.deep_retrieval,
        )

    def _prepare_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        context: ProductMarketAgentInput = payload["context"]
        bundle: RetrievalBundle | None = payload["retrieval"]
        evidence = list(context.evidence)
        if bundle is not None:
            evidence = [user_provided_evidence(context.product), *bundle.evidence]
        return {
            "context": context,
            "retrieval": bundle,
            "evidence": evidence,
            "retrieval_gaps": bundle.data_gaps("product_knowledge") if bundle else [],
            "retrieval_warnings": bundle.warnings if bundle else [],
            "missing_evidence_types": bundle.missing_evidence_types if bundle else [],
            "retrieval_errors": bundle.errors if bundle else [],
        }

    def _run_analysis(self, prepared: dict[str, Any]) -> ProductMarketAnalysis:
        context: ProductMarketAgentInput = prepared["context"]
        evidence: list[EvidenceReference] = prepared["evidence"]
        evidence_ids = [item.evidence_id for item in evidence]
        if context.product.data_origin is DataOrigin.REAL:
            model = self.model or create_analysis_model()
            message = (self.prompt | model).invoke(
                {
                    "product": context.product.model_dump_json(indent=2),
                    "statistics": context.statistics.model_dump_json(indent=2),
                    "evidence": self._format_evidence(evidence),
                }
            )
            return self._postprocess(parse_json_object(str(message.content)), prepared)
        return self._deterministic_analysis(prepared, evidence_ids)

    def _deterministic_analysis(self, prepared: dict[str, Any], evidence_ids: list[str]) -> ProductMarketAnalysis:
        context: ProductMarketAgentInput = prepared["context"]
        gaps = [*self._base_gaps(context), *prepared["retrieval_gaps"]]
        status = (
            AgentStatus.SUCCEEDED
            if evidence_ids and not prepared["retrieval_errors"]
            else AgentStatus.INSUFFICIENT_EVIDENCE
        )
        if not evidence_ids:
            gaps.insert(
                0,
                DataGap(
                    code="no_rag_evidence",
                    field="product_knowledge",
                    reason="No product knowledge evidence was supplied.",
                    required_for="product and market analysis",
                )
            )
        conclusions = [
            Conclusion(
                conclusion="Product analysis is grounded in supplied profile, statistics, and product evidence.",
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
            evidence_references=self._evidence_refs(prepared["evidence"]),
            data_gaps=gaps,
            missing_evidence_types=prepared["missing_evidence_types"],
            statistics_result_ids=self._statistics_ids(context),
            warnings=prepared["retrieval_warnings"],
            errors=prepared["retrieval_errors"],
            conclusions=conclusions,
            product_summary=self._summary(context),
            product_category=context.product.category,
            product_functions=context.product.features,
            key_parameters=[f"{key}: {value}" for key, value in context.product.attributes.items()],
            usage_scenarios=context.product.use_scenarios,
            target_users=context.product.target_audience,
            risks=context.product.known_risks,
        )

    def _postprocess(self, payload: dict[str, Any], prepared: dict[str, Any]) -> ProductMarketAnalysis:
        context: ProductMarketAgentInput = prepared["context"]
        evidence: list[EvidenceReference] = prepared["evidence"]
        allowed_ids = {item.evidence_id for item in evidence}
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
        gaps = [*self._base_gaps(context), *prepared["retrieval_gaps"]]
        if not evidence:
            payload["status"] = AgentStatus.INSUFFICIENT_EVIDENCE
        payload["data_gaps"] = [*payload.get("data_gaps", []), *[gap.model_dump() for gap in gaps]]
        payload["evidence_references"] = self._evidence_refs(evidence)
        payload["missing_evidence_types"] = [
            *payload.get("missing_evidence_types", []),
            *prepared["missing_evidence_types"],
        ]
        payload["statistics_result_ids"] = self._statistics_ids(context)
        payload["warnings"] = [*payload.get("warnings", []), *prepared["retrieval_warnings"]]
        payload["errors"] = [*payload.get("errors", []), *prepared["retrieval_errors"]]
        payload.setdefault("product_category", context.product.category)
        payload.setdefault("product_summary", self._summary(context))
        return ProductMarketAnalysis.model_validate(payload)

    @staticmethod
    def _format_evidence(evidence: list[EvidenceReference]) -> str:
        lines = []
        for item in evidence[:10]:
            lines.append(
                "\n".join(
                    [
                        f"evidence_id: {item.evidence_id}",
                        f"type: {item.evidence_type}",
                        f"source: {item.source_name}",
                        "vector_score: "
                        f"{item.metadata.get('vector_score', item.metadata.get('retrieval_score', 'unknown'))}",
                        f"rerank_score: {item.metadata.get('rerank_score', 'none')}",
                        f"excerpt: {item.excerpt[:1200]}",
                    ]
                )
            )
        return "\n\n".join(lines) or "[]"

    @staticmethod
    def _summary(context: ProductMarketAgentInput) -> str:
        parts = [
            f"Product: {context.product.name}",
            f"Category: {context.product.category}",
            f"Target market: {context.product.target_market or 'unknown'}",
        ]
        if context.statistics.metrics:
            metrics = ", ".join(f"{key}={value}" for key, value in sorted(context.statistics.metrics.items()))
            parts.append(f"Statistics: {metrics}")
        return "\n".join(parts)

    @staticmethod
    def _base_gaps(context: ProductMarketAgentInput) -> list[DataGap]:
        gaps = list(context.statistics.data_gaps)
        if context.statistics.status is AgentStatus.INSUFFICIENT_EVIDENCE:
            gaps.append(
                DataGap(
                    code="statistics_insufficient",
                    field="statistics",
                    reason=(
                        "StatisticsResult is insufficient; exact prices, counts, ratings, "
                        "and ratios remain unknown."
                    ),
                    required_for="numeric market analysis",
                )
            )
        return gaps

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
