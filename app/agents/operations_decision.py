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
)
from app.agents.structured_output import invoke_structured
from app.core.config import get_settings
from app.core.enums import AgentStatus, DataMode, DataOrigin, ImplementationStatus
from app.schemas.analysis import OperationPlan
from app.schemas.common import Conclusion, DataGap
from app.skills.operation_content import OperationContentSkill

NUMERIC_SOURCE_PATTERN = r"(?<![A-Za-z0-9_.-])\d+(?:\.\d+)?%?(?![A-Za-z0-9_.-])"
NUMERIC_CLAIM_PATTERN = r"(?<![A-Za-z0-9_.-])\d+(?:\.\d+)?%?"

OPERATIONS_SYSTEM_PROMPT = """
You are TradePilot OperationsDecisionAgent. The target is an unlisted new product with no sales or reviews.
All natural-language narrative content must be written in Simplified Chinese.
Keep JSON keys, enum values, brand names, product names, and units in their original form.
Put evidence_id and ASIN only in their dedicated machine fields; never place UUID, evidence_id, parent_asin, or ASIN
inside positioning, strategy fields, conclusions, data gaps, or next_steps.
Your primary deliverable is an actionable launch marketing strategy, not another product-description summary.
Do not state the exact number of peer products or reviews in user-facing prose. Translate descriptive labels and tone
words into Chinese; English is allowed only for immutable brand names, product names, official codes, and units.
Convert the supplied market and user analyses into a specific marketing objective, target segments, value
propositions, pricing strategy, channel strategy, messaging strategy, and evidence-bounded launch actions. Do not
merely repeat feature lists or peer-review findings. Explain how verified findings change positioning, messages,
channels, pricing, or launch gates. Use only the supplied new-product profile and the two evidence-grounded analyses.
Never turn a reasoned_hypothesis into a fact,
never attribute peer reviews to the new product, and never invent evidence IDs or numeric facts.
A reasoned_hypothesis must be derived only from new-product structure, parameters, or usage scenarios. It must not
claim that users "普遍", "高度关注", "反馈", or that reviews "显示/表明" anything; such user/review statements require
peer-review evidence and an evidence-summary conclusion type.
Do not set review-count, rating, conversion, discount, timing, or performance targets unless those exact numbers are
present in the supplied structured inputs. Prefer qualitative launch objectives when the user supplied no target.
When Product background includes tariff decision inputs, reflect their impact on landed cost, margin, pricing buffer,
launch gating, or broker-review requirements instead of treating them as passive reference material.
Return only JSON with status, positioning, marketing_objective, target_segments, value_propositions, pricing_strategy,
channel_strategy, messaging_strategy, launch_actions, conclusions, evidence_ids, data_gaps, and next_steps.
Every factual conclusion must use an evidence_id already present in the supplied analyses or Product background.
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
        normalization_attempt = 0

        def normalize(payload: dict[str, Any]) -> OperationPlan:
            nonlocal normalization_attempt
            normalization_attempt += 1
            return self._postprocess(
                payload,
                context,
                allow_strategy_objects=normalization_attempt > 1,
            )

        result = invoke_structured(
            prompt=self.prompt,
            model=model,
            values={
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
            },
            output_model=OperationPlan,
            normalize=normalize,
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

    def _postprocess(
        self,
        payload: dict[str, Any],
        context: OperationsDecisionAgentInput,
        *,
        allow_strategy_objects: bool = False,
    ) -> OperationPlan:
        payload = normalize_model_data_gaps(payload, field="operations_decision")
        background_ids = (
            [item.evidence_id for item in context.background_context.evidence]
            if context.background_context is not None
            else []
        )
        allowed_ids = set(
            context.product_market_analysis.evidence_ids
            + context.user_insight.evidence_ids
            + background_ids
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
        payload["positioning"] = self._normalize_positioning(payload.get("positioning", ""))
        payload["marketing_objective"] = self._normalize_positioning(
            payload.get("marketing_objective", "")
        )
        strategy_fields = (
            "target_segments",
            "value_propositions",
            "pricing_strategy",
            "channel_strategy",
            "messaging_strategy",
            "launch_actions",
        )
        for field in strategy_fields:
            payload[field] = self._normalize_strategy_list(
                payload.get(field, []),
                allow_objects=allow_strategy_objects,
            )
        content = self.content_skill.build(product=context.product, positioning=payload["positioning"])
        payload["next_steps"] = [*payload["next_steps"], *content.as_next_steps()]
        allowed_numbers = self._allowed_numbers(context)
        removed_unsupported_numbers = False
        if self._has_unsupported_numbers(payload["positioning"], allowed_numbers):
            removed_unsupported_numbers = True
            payload["positioning"] = "基于已验证的商品属性和同类市场证据建立差异化定位。"
        if self._has_unsupported_numbers(payload["marketing_objective"], allowed_numbers):
            removed_unsupported_numbers = True
            payload["marketing_objective"] = (
                "围绕已验证的目标客群与价值主张建立首发认知；具体量化目标需由用户确认。"
            )
        for field in strategy_fields:
            accepted_items = [
                item
                for item in payload[field]
                if not self._has_unsupported_numbers(item, allowed_numbers)
            ]
            removed_unsupported_numbers |= len(accepted_items) != len(payload[field])
            payload[field] = accepted_items
        accepted_conclusions = [
            conclusion
            for conclusion in payload["conclusions"]
            if not self._has_unsupported_numbers(
                conclusion.get("conclusion", ""), allowed_numbers
            )
        ]
        removed_unsupported_numbers |= len(accepted_conclusions) != len(payload["conclusions"])
        payload["conclusions"] = accepted_conclusions
        accepted_next_steps = [
            step
            for step in payload["next_steps"]
            if not self._has_unsupported_numbers(step, allowed_numbers)
        ]
        removed_unsupported_numbers |= len(accepted_next_steps) != len(payload["next_steps"])
        payload["next_steps"] = accepted_next_steps
        if removed_unsupported_numbers:
            payload["data_gaps"].append(
                {
                    "code": "unsupported_marketing_numeric_target",
                    "field": "operation_plan",
                    "reason": "模型提出了输入证据未支持的量化目标，已从面向用户的策略中移除。",
                    "required_for": "形成可执行的量化营销目标",
                }
            )
        return OperationPlan.model_validate(payload)

    @staticmethod
    def _allowed_numbers(context: OperationsDecisionAgentInput) -> set[str]:
        source = {"product": context.product.model_dump(mode="json")}
        if context.statistics is not None:
            source["statistics"] = context.statistics.model_dump(mode="json")
        if context.background_context is not None:
            source["background_context"] = context.background_context.model_dump(mode="json")
        values = set(
            re.findall(
                NUMERIC_SOURCE_PATTERN,
                json.dumps(source, ensure_ascii=False, default=str),
            )
        )
        product_claim_source = context.product.model_dump(
            mode="json",
            exclude={"product_id", "file_references", "data_gaps"},
        )
        values.update(
            re.findall(
                NUMERIC_CLAIM_PATTERN,
                json.dumps(product_claim_source, ensure_ascii=False, default=str),
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

        return re.sub(NUMERIC_CLAIM_PATTERN, replace, text)

    @staticmethod
    def _has_unsupported_numbers(value: object, allowed_numbers: set[str]) -> bool:
        return any(
            match.group(0) not in allowed_numbers
            for match in re.finditer(NUMERIC_CLAIM_PATTERN, str(value))
        )

    @staticmethod
    def _normalize_positioning(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("OperationPlan strategy summary fields must be strings")
        return value.strip()

    @staticmethod
    def _normalize_strategy_list(value: object, *, allow_objects: bool = False) -> list[str]:
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return [item.strip() for item in value if item.strip()]
        if not allow_objects:
            raise ValueError("OperationPlan strategy list fields must contain only strings")
        return list(dict.fromkeys(OperationsDecisionAgent._render_strategy_values(value)))

    @staticmethod
    def _render_strategy_values(value: object) -> list[str]:
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [
                rendered
                for item in value
                for rendered in OperationsDecisionAgent._render_strategy_values(item)
            ]
        if not isinstance(value, dict):
            return []
        rendered = OperationsDecisionAgent._render_strategy_item(value)
        if rendered:
            return [rendered]
        return [
            nested
            for key, item in value.items()
            if not OperationsDecisionAgent._is_machine_strategy_key(key)
            for nested in OperationsDecisionAgent._render_strategy_values(item)
        ]

    @staticmethod
    def _render_strategy_item(value: str | dict[str, Any]) -> str:
        if isinstance(value, str):
            return value.strip()
        title = next(
            (
                str(value[key]).strip()
                for key in ("segment_name", "proposition", "action", "name", "title")
                if value.get(key)
            ),
            "",
        )
        description = next(
            (
                str(value[key]).strip()
                for key in ("description", "rationale", "strategy", "message", "reason")
                if value.get(key)
            ),
            "",
        )
        has_chinese_title = any("\u4e00" <= character <= "\u9fff" for character in title)
        if description:
            return f"{title}：{description}" if title and has_chinese_title else description
        parts = [
            str(item).strip()
            for key, item in value.items()
            if not OperationsDecisionAgent._is_machine_strategy_key(key)
            and isinstance(item, (str, int, float))
            and str(item).strip()
        ]
        return "；".join(dict.fromkeys(parts))

    @staticmethod
    def _is_machine_strategy_key(key: str) -> bool:
        normalized = key.casefold()
        return (
            normalized in {"priority", "type", "confidence", "parent_asin", "asin"}
            or normalized.endswith("_id")
            or normalized.endswith("_ids")
        )

    @staticmethod
    def _compact_analysis(value: Any) -> str:
        payload = value.model_dump(mode="json")
        return str(
            {
                key: payload.get(key)
                for key in payload
                if key not in {"scaffold_note", "selected_parent_asins", "data_gaps"}
            }
        )

    def _run_deterministic(self, context: OperationsDecisionAgentInput) -> OperationPlan:
        core_evidence_ids = sorted(
            set(context.product_market_analysis.evidence_ids + context.user_insight.evidence_ids)
        )
        background_evidence_ids = (
            [item.evidence_id for item in context.background_context.evidence]
            if context.background_context is not None
            else []
        )
        evidence_ids = sorted(set([*core_evidence_ids, *background_evidence_ids]))
        data_gaps = self._merge_gaps(
            context.product.data_gaps,
            context.product_market_analysis.data_gaps,
            context.user_insight.data_gaps,
        )
        if not core_evidence_ids:
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
            if core_evidence_ids
            else "Treat this as a profile-led hypothesis until product and user evidence is supplied."
        )
        positioning = (
            f"Position {product.name} for {audience} in {market} around {value_focus}. {evidence_note}"
        )

        conclusions = [
            Conclusion(
                conclusion=positioning,
                conclusion_type="recommendation",
                confidence=0.72 if core_evidence_ids else 0.35,
                evidence_ids=core_evidence_ids,
                data_gaps=[] if core_evidence_ids else data_gaps,
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

        tariff_brief = ""
        tariff_actions: list[str] = []
        if context.background_context is not None and context.background_context.decision_inputs:
            tariff_brief = str(
                context.background_context.decision_inputs.get("agent_decision_brief")
                or context.background_context.decision_inputs.get("tariff_summary")
                or ""
            ).strip()
            tariff_actions = [
                str(item).strip()
                for item in context.background_context.decision_inputs.get("tariff_recommended_actions", [])
                if str(item).strip()
            ]
        if tariff_brief:
            conclusions.append(
                Conclusion(
                    conclusion=f"Tariff decision input: {tariff_brief}",
                    conclusion_type="recommendation",
                    confidence=0.8 if background_evidence_ids else 0.5,
                    evidence_ids=background_evidence_ids,
                )
            )

        content = self.content_skill.build(product=product, positioning=positioning)
        next_steps = [
            "ACTION: Validate the proposed positioning against current marketplace evidence before launch.",
            "ACTION: Confirm every product specification and compatibility statement before publishing.",
            "ACTION: Add structured competitor prices and review statistics before making numeric claims.",
            *[f"ACTION: {item}" for item in tariff_actions],
            *content.as_next_steps(),
        ]

        statuses = {
            context.product_market_analysis.status,
            context.user_insight.status,
        }
        if AgentStatus.FAILED in statuses:
            status = AgentStatus.FAILED
        elif core_evidence_ids:
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
