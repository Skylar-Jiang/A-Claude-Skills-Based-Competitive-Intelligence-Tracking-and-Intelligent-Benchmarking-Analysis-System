from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableSequence

from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import UserInsightAgentInput
from app.agents.model_factory import (
    create_analysis_model,
    normalize_evidence_ids,
    normalize_model_data_gaps,
    normalize_text_list,
)
from app.agents.structured_output import invoke_structured
from app.core.config import get_settings
from app.core.enums import AgentStatus, DataMode, DataOrigin, ImplementationStatus
from app.rag.pipeline import RetrievalPipeline, user_provided_evidence
from app.schemas.analysis import UserInsight
from app.schemas.common import Conclusion, DataGap
from app.schemas.evidence import EvidenceReference

USER_INSIGHT_SYSTEM_PROMPT = """
You are TradePilot UserInsightAgent.
所有自然语言内容必须使用简体中文，包括摘要、分析、列表项、结论和数据缺口说明。
JSON 键名、枚举值、品牌名、商品名、单位和不可变的原始引文保持原值；不要输出英文句子。
evidence_id、UUID、parent_asin 和 ASIN 仅放入专用机器字段，不得写入面向用户的摘要、列表项或结论。
The ProductProfile is an unlisted new product with no reviews. Use only supplied reviews of listed peer products,
user input, ProductProfile, and StatisticsResult. Always call them 同类商品评论样本 or 同类市场用户洞察.
Never say 当前商品反馈, 该商品用户普遍认为, 当前商品差评, or imply that peer reviews belong to the new product.
Do not describe an individual review as a market-wide trend.
"high frequency", "majority", ratios, average rating, and counts require StatisticsResult support.
If statistics are missing, say "appears in the retrieved sample" instead of making aggregate claims.
Do not infer sensitive identity attributes not explicitly present in reviews.
Every factual conclusion must cite existing evidence_ids; never invent evidence IDs.
Do not append evidence IDs or citation notes inside narrative list items. If a factual list item has no direct supplied
review evidence, omit it instead of writing 无直接引用 or relying on general knowledge. Do not state the exact number
of peer products or reviews in user-facing prose; say Amazon 同类市场商品及其真实评论样本. Translate descriptive
labels such as tone or feature explanations into Chinese; English is allowed only for immutable names and units.
Cover common needs, positive experiences, pain points, purchase factors, feature/use/maintenance concerns,
pre-launch validation items, needs convertible to selling points, optimization directions, and sample limitations.
Attribute-only hypotheses must begin with "待验证假设" and must not be stated as review or market facts.
Return only a JSON object matching this schema shape:
{{"status":"succeeded|insufficient_evidence","insight_summary":"...","common_needs":[],"positive_experiences":[],"pain_points":[],"purchase_factors":[],"feature_usage_maintenance_concerns":[],"prelaunch_validations":[],"convertible_selling_points":[],"optimization_directions":[],"sample_limitations":[],"reasoned_hypotheses":[],"conclusions":[{{"conclusion":"...","conclusion_type":"user_insight|recommendation|reasoned_hypothesis","confidence":0.0,"evidence_ids":["..."],"data_gaps":[]}}],"evidence_ids":["..."],"data_gaps":[]}}
"""


class UserInsightAgent(BaseScaffoldAgent[UserInsightAgentInput, UserInsight]):
    """Evidence-grounded user review insight agent."""

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
                    "ProductProfile:\n{product}\n\nPeerGroupContext:\n{peer_context}\n\n"
                    "StatisticsResult:\n{statistics}\n\nReview Evidence:\n{evidence}\n",
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
        self, context: UserInsightAgentInput
    ) -> UserInsightAgentInput:
        if (
            self.retrieval_pipeline is None
            or context.peer_group_id
            or context.evidence
            or context.product.data_origin is not DataOrigin.REAL
        ):
            return context
        bundle = self.retrieval_pipeline.retrieve_review_evidence(
            context.product,
            {**self.constraints, **context.user_constraints},
            deep=self.deep_retrieval,
        )
        return context.model_copy(
            update={"evidence": [user_provided_evidence(context.product), *bundle.evidence]}
        )

    def _run_analysis(self, context: UserInsightAgentInput) -> UserInsight:
        evidence_ids = [item.evidence_id for item in context.evidence]
        if context.product.data_mode is DataMode.REAL or context.product.data_origin is DataOrigin.REAL:
            model = self.model or create_analysis_model()
            result = invoke_structured(
                prompt=self.prompt,
                model=model,
                values={
                    "product": context.product.model_dump_json(indent=2),
                    "peer_context": str(
                        {
                            "peer_group_id": context.peer_group_id,
                            "selected_parent_asins": context.selected_parent_asins,
                            "selected_peer_product_count": len(context.selected_peer_products),
                        }
                    ),
                    "statistics": context.statistics.model_dump_json(indent=2),
                    "evidence": self._format_evidence(context.evidence),
                },
                output_model=UserInsight,
                normalize=lambda payload: self._postprocess(payload, context),
                max_parse_retries=get_settings().model_parse_max_retries,
            )
            return result.value.model_copy(
                update={
                    "model_call_count": result.model_call_count,
                    "parse_retry_count": result.parse_retry_count,
                    "token_usage": result.token_usage,
                    "structured_output_parser": result.parser_name,
                }
            )
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
            peer_group_id=context.peer_group_id,
            selected_parent_asins=context.selected_parent_asins,
            evidence_ids=evidence_ids,
            evidence_references=self._evidence_refs(context.evidence),
            statistics_result_ids=self._statistics_ids(context),
            data_gaps=gaps,
            conclusions=conclusions,
            insight_summary=summary,
        )

    @staticmethod
    def _format_evidence(evidence: list[EvidenceReference]) -> str:
        lines = []
        for item in evidence[:8]:
            lines.append(
                "\n".join(
                    [
                        f"evidence_id: {item.evidence_id}",
                        f"rating: {item.metadata.get('rating', 'unknown')}",
                        f"verified_purchase: {item.metadata.get('verified_purchase', 'unknown')}",
                        f"source: {item.source_name}",
                        f"excerpt: {item.excerpt[:600]}",
                    ]
                )
            )
        return "\n\n".join(lines) or "[]"

    def _postprocess(self, payload: dict[str, Any], context: UserInsightAgentInput) -> UserInsight:
        payload = self._peer_safe_payload(payload)
        payload = normalize_model_data_gaps(payload, field="peer_review_sample")
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
                "conclusion_type", "user_insight" if conclusion["evidence_ids"] else "recommendation"
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
            "common_needs",
            "positive_experiences",
            "pain_points",
            "purchase_factors",
            "feature_usage_maintenance_concerns",
            "prelaunch_validations",
            "convertible_selling_points",
            "optimization_directions",
            "sample_limitations",
            "reasoned_hypotheses",
        ):
            payload[field] = normalize_text_list(payload.get(field, []))
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
        payload["evidence_references"] = self._evidence_refs(context.evidence)
        payload["statistics_result_ids"] = self._statistics_ids(context)
        payload["reasoned_hypotheses"] = [
            item if str(item).startswith("待验证假设") else f"待验证假设（非用户评论结论、非市场统计事实）：{item}"
            for item in payload.get("reasoned_hypotheses", [])
        ]
        return UserInsight.model_validate(payload)

    @staticmethod
    def _statistics_ids(context: UserInsightAgentInput) -> list[str]:
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

    @classmethod
    def _peer_safe_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: cls._peer_safe_payload(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._peer_safe_payload(item) for item in value]
        if not isinstance(value, str):
            return value
        replacements = {
            "当前商品用户反馈": "同类商品评论样本",
            "当前商品反馈": "同类商品评论样本",
            "该商品用户普遍认为": "同类商品评论样本中出现",
            "当前商品差评": "同类商品低评分评论样本",
        }
        for unsafe, safe in replacements.items():
            value = value.replace(unsafe, safe)
        return value

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
