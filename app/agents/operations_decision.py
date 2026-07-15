import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import OperationsDecisionAgentInput
from app.agents.model_factory import (
    create_operations_model,
    normalize_evidence_ids,
    normalize_model_data_gaps,
    normalize_text_list,
    parse_json_object,
)
from app.core.enums import AgentStatus, DataMode, DataOrigin, ImplementationStatus
from app.schemas.analysis import OperationPlan
from app.schemas.common import Conclusion, DataGap
from app.skills.operation_content import OperationContentSkill

OPERATIONS_SYSTEM_PROMPT = """
You are TradePilot OperationsDecisionAgent. The target is an unlisted new product with no sales or reviews.
Use only the supplied new-product profile and the two evidence-grounded analyses. Never turn a待验证假设 into a fact,
never attribute peer reviews to the new product, and never invent evidence IDs or numeric facts.
Return only JSON with status, positioning, conclusions, evidence_ids, data_gaps, and next_steps.
Every factual conclusion must use an evidence_id already present in the supplied analyses.
Use 同类市场商品, 同类商品评论样本, 同类用户常见关注点, and 新商品上市前需验证事项.
Each conclusion must be {{"conclusion":"...","conclusion_type":"recommendation|evidence_summary|reasoned_hypothesis",
"confidence":0.0,"evidence_ids":[],"data_gaps":[]}}.
"""


class OperationsDecisionAgent(BaseScaffoldAgent[OperationsDecisionAgentInput, OperationPlan]):
    """Build an evidence-aware plan and policy-checked content playbook."""

    input_model = OperationsDecisionAgentInput
    output_model = OperationPlan

    def __init__(
        self,
        content_skill: OperationContentSkill | None = None,
        model: BaseChatModel | None = None,
    ) -> None:
        self.content_skill = content_skill or OperationContentSkill.from_default()
        self.model = model
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", OPERATIONS_SYSTEM_PROMPT),
                (
                    "human",
                    "New product:\n{product}\n\nPeer scope:\n{peer_scope}\n\nUser constraints:\n{constraints}\n\n"
                    "Product background:\n{background}\n\nStatistics:\n{statistics}\n\n"
                    "Peer market analysis:\n{market}\n\nPeer user insight:\n{insight}",
                ),
            ]
        )
        super().__init__()

    def _run_stub(self, context: OperationsDecisionAgentInput) -> OperationPlan:
        if context.product.data_mode is DataMode.REAL or context.product.data_origin is DataOrigin.REAL:
            return self._run_model(context)
        return self._run_deterministic(context)

    def _run_model(self, context: OperationsDecisionAgentInput) -> OperationPlan:
        model = self.model or create_operations_model()
        message = (self.prompt | model).invoke(
            {
                "product": context.product.model_dump_json(indent=2),
                "peer_scope": str(
                    {
                        "peer_group_id": context.peer_group_id,
                        "selected_parent_asins": context.selected_parent_asins,
                    }
                ),
                "constraints": str(context.user_constraints),
                "background": (
                    context.background_context.model_dump_json(indent=2)
                    if context.background_context
                    else "null"
                ),
                "statistics": context.statistics.model_dump_json(indent=2) if context.statistics else "null",
                "market": self._compact_analysis(context.product_market_analysis),
                "insight": self._compact_analysis(context.user_insight),
            }
        )
        payload: dict[str, Any] = parse_json_object(str(message.content))
        payload = normalize_model_data_gaps(payload, field="operations_decision")
        allowed_ids = set(
            context.product_market_analysis.evidence_ids + context.user_insight.evidence_ids
        )
        payload["data_origin"] = context.product.data_origin
        payload["peer_group_id"] = context.peer_group_id
        payload["selected_parent_asins"] = context.selected_parent_asins
        payload["analysis_scopes"] = self._analysis_scopes(context)
        payload["implementation_status"] = ImplementationStatus.PRODUCTION
        payload["scaffold_note"] = ""
        payload["evidence_ids"] = sorted(
            set(normalize_evidence_ids(payload.get("evidence_ids", []), allowed_ids=allowed_ids))
        )
        conclusions = []
        for conclusion in payload.get("conclusions", []) if isinstance(payload.get("conclusions"), list) else []:
            if not isinstance(conclusion, dict):
                continue
            if not str(conclusion.get("conclusion", "")).strip():
                continue
            conclusion["evidence_ids"] = normalize_evidence_ids(
                conclusion.get("evidence_ids", []), allowed_ids=allowed_ids
            )
            conclusion.setdefault("conclusion_type", "recommendation")
            conclusion.setdefault("confidence", 0.65 if conclusion["evidence_ids"] else 0.35)
            if conclusion["conclusion_type"] == "reasoned_hypothesis" and not str(
                conclusion.get("conclusion", "")
            ).startswith("待验证假设"):
                conclusion["conclusion"] = (
                    "待验证假设（非用户评论结论、非市场统计事实）："
                    + str(conclusion.get("conclusion", ""))
                )
            if not conclusion["evidence_ids"] and not conclusion.get("data_gaps"):
                conclusion["data_gaps"] = [
                    {
                        "code": "decision_evidence_missing",
                        "field": "operation_plan",
                        "reason": "The recommendation has no valid supplied evidence_id.",
                        "required_for": "evidence-grounded launch decision",
                    }
                ]
            conclusions.append(conclusion)
        payload["conclusions"] = conclusions
        payload["status"] = (
            AgentStatus.SUCCEEDED if payload["evidence_ids"] else AgentStatus.INSUFFICIENT_EVIDENCE
        )
        payload.setdefault("data_gaps", [])
        payload["next_steps"] = normalize_text_list(payload.get("next_steps", []))
        payload.setdefault("positioning", "")
        content = self.content_skill.build(product=context.product, positioning=payload["positioning"])
        payload["next_steps"] = [*payload["next_steps"], *content.as_next_steps()]
        allowed_numbers = self._allowed_numbers(context)
        payload["positioning"] = self._sanitize_numeric_text(payload["positioning"], allowed_numbers)
        for conclusion in payload["conclusions"]:
            conclusion["conclusion"] = self._sanitize_numeric_text(
                conclusion.get("conclusion", ""), allowed_numbers
            )
        payload["next_steps"] = [
            self._sanitize_numeric_text(step, allowed_numbers) for step in payload["next_steps"]
        ]
        return OperationPlan.model_validate(payload)

    @staticmethod
    def _allowed_numbers(context: OperationsDecisionAgentInput) -> set[str]:
        source = {"product": context.product.model_dump(mode="json")}
        if context.statistics is not None:
            source["statistics"] = context.statistics.model_dump(mode="json")
        values = set(
            re.findall(
                r"(?<![\w-])\d+(?:\.\d+)?%?(?![\w-])",
                json.dumps(source, ensure_ascii=False, default=str),
            )
        )
        for value in list(values):
            try:
                rounded = Decimal(value.removesuffix("%")).quantize(Decimal("0.01"))
            except InvalidOperation:
                continue
            values.add(format(rounded, "f").rstrip("0").rstrip("."))
        return values

    @staticmethod
    def _sanitize_numeric_text(value: object, allowed_numbers: set[str]) -> str:
        text = str(value)

        def replace(match: re.Match[str]) -> str:
            number = match.group(0)
            return number if number in allowed_numbers else "待验证数值"

        return re.sub(r"(?<![\w-])\d+(?:\.\d+)?%?", replace, text)

    @staticmethod
    def _compact_analysis(value: Any) -> str:
        payload = value.model_dump(mode="json")
        return str(
            {
                key: payload.get(key)
                for key in payload
                if key
                not in {
                    "scaffold_note",
                    "selected_parent_asins",
                    "data_gaps",
                }
            }
        )

    def _run_deterministic(self, context: OperationsDecisionAgentInput) -> OperationPlan:
        evidence_ids = sorted(
            set(context.product_market_analysis.evidence_ids + context.user_insight.evidence_ids)
        )
        data_gaps = self._merge_gaps(
            context.product.data_gaps,
            context.product_market_analysis.data_gaps,
            context.user_insight.data_gaps,
        )
        if not evidence_ids:
            data_gaps = self._merge_gaps(
                data_gaps,
                [
                    DataGap(
                        code="decision_evidence_missing",
                        field="operation_plan",
                        reason="No product-market or user-insight evidence is available for the decision.",
                        required_for="evidence-grounded positioning and marketing claims",
                    )
                ],
            )

        product = context.product
        market = product.target_market or "the selected target market"
        audience = product.target_audience[0] if product.target_audience else "the intended buyer segment"
        value_focus = product.features[0] if product.features else "verified product attributes"
        evidence_note = (
            "Use the cited product and user evidence as the validation boundary."
            if evidence_ids
            else "Treat this as a profile-led hypothesis until product and user evidence is supplied."
        )
        positioning = (
            f"Position {product.name} for {audience} in {market} around {value_focus}. {evidence_note}"
        )

        conclusions = [
            Conclusion(
                conclusion=positioning,
                conclusion_type="recommendation",
                confidence=0.72 if evidence_ids else 0.35,
                evidence_ids=evidence_ids,
                data_gaps=[] if evidence_ids else data_gaps,
            )
        ]
        if product.target_market:
            conclusions.append(
                Conclusion(
                    conclusion=f"The user-selected target market is {product.target_market}.",
                    conclusion_type="user_input",
                    confidence=1.0,
                )
            )
        if product.target_price is not None:
            currency = f" {product.target_currency}" if product.target_currency else ""
            conclusions.append(
                Conclusion(
                    conclusion=f"The user target price is {product.target_price}{currency}.",
                    conclusion_type="user_input",
                    confidence=1.0,
                )
            )
        if data_gaps:
            conclusions.append(
                Conclusion(
                    conclusion=(
                        "Market, pricing, and audience claims remain limited to the supplied profile and cited "
                        "evidence; unresolved gaps must be shown in the final report."
                    ),
                    conclusion_type="data_limitation",
                    confidence=1.0,
                    data_gaps=data_gaps,
                )
            )

        content = self.content_skill.build(product=product, positioning=positioning)
        next_steps = [
            "ACTION: Validate the proposed positioning against current marketplace evidence before launch.",
            "ACTION: Confirm every product specification and compatibility statement before publishing.",
            "ACTION: Add structured competitor prices and review statistics before making numeric claims.",
            *content.as_next_steps(),
        ]

        statuses = {
            context.product_market_analysis.status,
            context.user_insight.status,
        }
        if AgentStatus.FAILED in statuses:
            status = AgentStatus.FAILED
        elif evidence_ids:
            status = AgentStatus.SUCCEEDED
        else:
            status = AgentStatus.INSUFFICIENT_EVIDENCE

        return OperationPlan(
            status=status,
            data_origin=product.data_origin,
            conclusions=conclusions,
            evidence_ids=evidence_ids,
            data_gaps=data_gaps,
            positioning=positioning,
            next_steps=next_steps,
            peer_group_id=context.peer_group_id,
            selected_parent_asins=context.selected_parent_asins,
            analysis_scopes=self._analysis_scopes(context),
            scaffold_note=(
                "Deterministic Demo operations rules v1 are active; model-backed optimization and real market "
                "execution remain outside the scaffold boundary."
            ),
        )

    @staticmethod
    def _analysis_scopes(context: OperationsDecisionAgentInput) -> dict[str, object]:
        return {
            "product_market_agent": {
                "peer_group_id": context.product_market_analysis.peer_group_id,
                "selected_parent_asins": context.product_market_analysis.selected_parent_asins,
            },
            "user_insight_agent": {
                "peer_group_id": context.user_insight.peer_group_id,
                "selected_parent_asins": context.user_insight.selected_parent_asins,
            },
        }

    @staticmethod
    def _merge_gaps(*groups: list[DataGap]) -> list[DataGap]:
        result: list[DataGap] = []
        seen: set[tuple[str, str, str, str | None]] = set()
        for gap in (item for group in groups for item in group):
            key = (gap.code, gap.field, gap.reason, gap.required_for)
            if key not in seen:
                seen.add(key)
                result.append(gap)
        return result
