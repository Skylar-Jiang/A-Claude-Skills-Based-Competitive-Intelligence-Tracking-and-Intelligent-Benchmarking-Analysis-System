from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel, RunnableSequence

from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import UserInsightAgentInput
from app.agents.model_factory import create_analysis_model, parse_json_object
from app.core.enums import AgentStatus, DataOrigin
from app.rag.pipeline import RetrievalBundle, RetrievalPipeline
from app.schemas.analysis import UserInsight
from app.schemas.common import Conclusion, DataGap
from app.schemas.evidence import EvidenceReference

USER_INSIGHT_SYSTEM_PROMPT = """
You are TradePilot UserInsightAgent.
Use only supplied review EvidenceReference records, ProductProfile, user input, and StatisticsResult.
Do not describe an individual review as a market-wide trend.
"high frequency", "majority", ratios, average rating, and review counts require StatisticsResult support.
Without statistics, use "appears in the retrieved sample" or "some reviews mention".
Do not infer sensitive identity attributes unless explicitly present in evidence.
Every factual conclusion must cite existing evidence_ids; never invent evidence IDs or user quotes.
Return only a JSON object matching UserInsight. Do not output text outside JSON.
"""


class UserInsightAgent(BaseScaffoldAgent[UserInsightAgentInput, UserInsight]):
    input_model = UserInsightAgentInput
    output_model = UserInsight

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
                ("system", USER_INSIGHT_SYSTEM_PROMPT),
                (
                    "human",
                    "ProductProfile:\n{product}\n\n"
                    "StatisticsResult:\n{statistics}\n\n"
                    "Review Evidence:\n{evidence}\n",
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

    def _run_stub(self, context: UserInsightAgentInput) -> UserInsight:
        return self._run_analysis(self._prepare_context({"context": context, "retrieval": None}))

    def _retrieve(self, context: UserInsightAgentInput) -> RetrievalBundle | None:
        if self.retrieval_pipeline is None or context.product.data_origin is not DataOrigin.REAL:
            return None
        constraints = {**self.constraints, **context.user_constraints}
        return self.retrieval_pipeline.retrieve_review_evidence(
            context.product,
            constraints,
            deep=self.deep_retrieval,
        )

    def _prepare_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        context: UserInsightAgentInput = payload["context"]
        bundle: RetrievalBundle | None = payload["retrieval"]
        evidence = bundle.evidence if bundle is not None else list(context.evidence)
        return {
            "context": context,
            "retrieval": bundle,
            "evidence": evidence,
            "retrieval_gaps": bundle.data_gaps("review_insight") if bundle else [],
            "retrieval_warnings": bundle.warnings if bundle else [],
            "missing_evidence_types": bundle.missing_evidence_types if bundle else [],
            "retrieval_errors": bundle.errors if bundle else [],
        }

    def _run_analysis(self, prepared: dict[str, Any]) -> UserInsight:
        context: UserInsightAgentInput = prepared["context"]
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

    def _deterministic_analysis(self, prepared: dict[str, Any], evidence_ids: list[str]) -> UserInsight:
        context: UserInsightAgentInput = prepared["context"]
        evidence: list[EvidenceReference] = prepared["evidence"]
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
                    code="no_review_evidence",
                    field="review_insight",
                    reason="No review insight evidence was supplied.",
                    required_for="user insight analysis",
                )
            )
        positive = [item for item in evidence if float(item.metadata.get("rating", 0) or 0) >= 4]
        negative = [item for item in evidence if 0 < float(item.metadata.get("rating", 0) or 0) <= 2]
        warnings = [*prepared["retrieval_warnings"]]
        if evidence and (not positive or not negative):
            warnings.append("review_sentiment_coverage_limited")
        conclusions = [
            Conclusion(
                conclusion="User insight is limited to supplied statistics and retrieved review evidence.",
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
            evidence_references=self._evidence_refs(evidence),
            data_gaps=gaps,
            missing_evidence_types=prepared["missing_evidence_types"],
            statistics_result_ids=self._statistics_ids(context),
            warnings=warnings,
            errors=prepared["retrieval_errors"],
            conclusions=conclusions,
            insight_summary=(
                f"Retrieved review sample size: {len(evidence)}. "
                f"Positive sample evidence: {len(positive)}; negative sample evidence: {len(negative)}. "
                "Aggregate claims require StatisticsResult metrics."
            ),
        )

    def _postprocess(self, payload: dict[str, Any], prepared: dict[str, Any]) -> UserInsight:
        context: UserInsightAgentInput = prepared["context"]
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
        payload["warnings"] = [
            *payload.get("warnings", []),
            *prepared["retrieval_warnings"],
            *self._statistical_language_warnings(payload, context),
        ]
        payload["errors"] = [*payload.get("errors", []), *prepared["retrieval_errors"]]
        payload.setdefault("insight_summary", "Review insight generated from supplied evidence.")
        return UserInsight.model_validate(payload)

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
                        "vector_score: "
                        f"{item.metadata.get('vector_score', item.metadata.get('retrieval_score', 'unknown'))}",
                        f"rerank_score: {item.metadata.get('rerank_score', 'none')}",
                        f"source: {item.source_name}",
                        f"excerpt: {item.excerpt[:1200]}",
                    ]
                )
            )
        return "\n\n".join(lines) or "[]"

    @staticmethod
    def _base_gaps(context: UserInsightAgentInput) -> list[DataGap]:
        gaps = list(context.statistics.data_gaps)
        if context.statistics.status is AgentStatus.INSUFFICIENT_EVIDENCE:
            gaps.append(
                DataGap(
                    code="statistics_insufficient",
                    field="statistics",
                    reason=(
                        "StatisticsResult is insufficient; aggregate counts, ratings, "
                        "and proportions remain unknown."
                    ),
                    required_for="quantified user insight",
                )
            )
        return gaps

    @staticmethod
    def _statistics_ids(context: UserInsightAgentInput) -> list[str]:
        return [item for item in [context.statistics.result_id, *context.statistics.evidence_ids] if item]

    @staticmethod
    def _statistical_language_warnings(payload: dict[str, Any], context: UserInsightAgentInput) -> list[str]:
        if context.statistics.metrics:
            return []
        text = " ".join(
            str(value)
            for key, value in payload.items()
            if key in {"insight_summary", "conclusions", "pain_points", "frequent_keywords"}
        ).lower()
        restricted = (
            "majority",
            "most users",
            "high frequency",
            "percentage",
            "average rating",
            "占比",
            "多数",
            "高频",
        )
        return ["unsupported_aggregate_language_detected"] if any(token in text for token in restricted) else []

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
