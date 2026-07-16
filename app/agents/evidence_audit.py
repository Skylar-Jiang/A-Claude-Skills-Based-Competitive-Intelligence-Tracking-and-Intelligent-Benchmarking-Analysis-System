from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.agents.base import BaseScaffoldAgent
from app.agents.contracts import EvidenceAuditAgentInput
from app.agents.model_factory import create_audit_model, parse_json_object
from app.core.enums import AgentStatus, AuditStatus, DataMode, DataOrigin, ImplementationStatus
from app.schemas.analysis import AuditResult
from app.schemas.common import Conclusion
from app.skills.operation_content import OperationContentSkill

FACTUAL_CONCLUSION_TYPES = {
    "evidence_grounded",
    "evidence_summary",
    "market_fact",
    "product_fact",
    "user_insight",
}

CONFLICT_PAIRS = (
    (("low price", "low-price", "budget", "低价"), ("premium", "high-end", "高端")),
    (("durable", "耐用"), ("fragile", "易碎")),
    (("compact", "便携", "小巧"), ("bulky", "笨重", "大体积")),
    (("safe for", "安全适用"), ("unsafe", "不安全")),
)
PEER_ATTRIBUTION_FORBIDDEN = (
    "当前商品用户反馈",
    "当前商品反馈",
    "该商品用户普遍认为",
    "当前商品差评",
)
AUDIT_SYSTEM_PROMPT = """
You are TradePilot EvidenceAuditAgent. Audit an unlisted new-product plan against supplied peer evidence and structured
statistics. Check peer-review attribution, peer_group_id, accessories, numeric sources, reasoned-hypothesis labeling,
and whether every evidence_id exists. Never create facts or evidence. Return JSON only with status, issues,
conflicting_evidence_ids, unresolved_questions, and manual_review_required.
所有自然语言内容必须使用简体中文，包括问题、风险和未解决事项。
JSON 键名、枚举值、evidence_id、ASIN、品牌名、商品名和单位保持原值；不要输出英文句子。
The Evidence array is authoritative for Plan evidence IDs. Statistics.evidence_ids are upstream provenance references;
do not report their absence from the Evidence array unless the Plan itself cites one.
The Evidence array is the available audit scope, so valid evidence may remain unused by the final Plan. Do not treat
unused or uncited supplied evidence as leakage, incomplete filtering, or an audit issue.
An explicitly labeled reasoned_hypothesis may have no evidence_id when it carries a data gap; it is a prelaunch item
to validate, not a factual conclusion. Do not flag that expected structure as unsupported evidence.
Put only violations, risks, or unresolved defects in issues/questions; do not emit passing confirmations such as
"matches expected", "correctly labeled", "exists", or "no conflict" as findings.
"""


class EvidenceAuditAgent(BaseScaffoldAgent[EvidenceAuditAgentInput, AuditResult]):
    """Audit evidence binding, claim safety, conflicts, and content-policy compliance."""

    input_model = EvidenceAuditAgentInput
    output_model = AuditResult

    def __init__(
        self,
        content_skill: OperationContentSkill | None = None,
        model: BaseChatModel | None = None,
    ) -> None:
        self.content_skill = content_skill or OperationContentSkill.from_default()
        self.model = model
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", AUDIT_SYSTEM_PROMPT),
                (
                    "human",
                    "Product:\n{product}\n\nPlan:\n{plan}\n\nEvidence:\n{evidence}\n\n"
                    "Product background:\n{background}\n\nStatistics:\n{statistics}\n"
                    "Expected peer_group_id: {peer_group_id}",
                ),
            ]
        )
        super().__init__()

    def _run_stub(self, context: EvidenceAuditAgentInput) -> AuditResult:
        deterministic = self._run_deterministic(context)
        if context.product.data_mode is not DataMode.REAL and context.product.data_origin is not DataOrigin.REAL:
            return deterministic
        model = self.model or create_audit_model()
        message = (self.prompt | model).invoke(
            {
                "product": context.product.model_dump_json(indent=2),
                "plan": context.operation_plan.model_dump_json(indent=2),
                "evidence": json.dumps(
                    [
                        {
                            "evidence_id": item.evidence_id,
                            "evidence_type": item.evidence_type,
                            "knowledge_type": item.knowledge_type.value,
                            "source_name": item.source_name,
                            "peer_group_id": item.metadata.get("peer_group_id"),
                            "parent_asin": item.metadata.get("parent_asin"),
                            "evidence_scope": item.metadata.get("evidence_scope"),
                            "is_accessory": item.metadata.get("is_accessory", False),
                        }
                        for item in context.evidence
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                "statistics": context.statistics.model_dump_json(indent=2) if context.statistics else "null",
                "background": (
                    context.background_context.model_dump_json(indent=2)
                    if context.background_context
                    else "null"
                ),
                "peer_group_id": context.peer_group_id or "not supplied",
            }
        )
        payload: dict[str, Any] = parse_json_object(str(message.content))
        valid_evidence_ids = {item.evidence_id for item in context.evidence}
        declared_evidence_ids = set(context.operation_plan.evidence_ids)
        evidence_less_hypotheses = [
            conclusion
            for conclusion in context.operation_plan.conclusions
            if conclusion.conclusion_type == "reasoned_hypothesis" and not conclusion.evidence_ids
        ]
        valid_evidence_less_hypotheses = bool(evidence_less_hypotheses) and all(
            conclusion.data_gaps and conclusion.conclusion.startswith("待验证假设")
            for conclusion in evidence_less_hypotheses
        )
        model_issues = [
            self._model_advisory(item)
            for item in payload.get("issues", [])
            if not self._refuted_model_finding(
                item,
                valid_evidence_ids,
                declared_evidence_ids,
                valid_evidence_less_hypotheses=valid_evidence_less_hypotheses,
            )
        ]
        model_conflicts = [str(item) for item in payload.get("conflicting_evidence_ids", [])]
        model_questions = [
            str(item)
            for item in payload.get("unresolved_questions", [])
            if not self._refuted_model_finding(
                item,
                valid_evidence_ids,
                declared_evidence_ids,
                valid_evidence_less_hypotheses=valid_evidence_less_hypotheses,
            )
        ]
        issues = self._unique([*deterministic.issues, *model_issues])
        status = deterministic.status
        if issues and status is AuditStatus.PASS:
            status = AuditStatus.WARNING
        return AuditResult(
            status=status,
            data_origin=context.operation_plan.data_origin,
            implementation_status=ImplementationStatus.PRODUCTION,
            issues=issues,
            conflicting_evidence_ids=self._unique(
                [*deterministic.conflicting_evidence_ids, *model_conflicts]
            ),
            unresolved_questions=self._unique(
                [*deterministic.unresolved_questions, *model_questions]
            ),
            manual_review_required=deterministic.manual_review_required,
        )

    def _run_deterministic(self, context: EvidenceAuditAgentInput) -> AuditResult:
        plan = context.operation_plan
        blocking: list[str] = []
        warnings: list[str] = []
        unresolved: list[str] = []
        conflicting_evidence_ids: list[str] = []

        if plan.data_origin is not context.product.data_origin:
            blocking.append(
                "data_origin_mismatch: Regenerate the plan using only data from the current product mode; "
                f"product={context.product.data_origin.value}, plan={plan.data_origin.value}."
            )
        expected_implementation = (
            ImplementationStatus.PRODUCTION
            if context.product.data_mode is DataMode.REAL or context.product.data_origin is DataOrigin.REAL
            else ImplementationStatus.SCAFFOLD
        )
        if plan.implementation_status is not expected_implementation:
            blocking.append(
                f"implementation_status_invalid: Expected {expected_implementation.value} output for this run."
            )
        if plan.status is AgentStatus.FAILED:
            blocking.append("operation_plan_failed: Resolve the decision Agent failure before report export.")

        declared_evidence = set(plan.evidence_ids)
        if len(declared_evidence) != len(plan.evidence_ids):
            warnings.append("duplicate_evidence_ids: De-duplicate operation_plan.evidence_ids.")

        if context.evidence:
            evidence_by_id = {item.evidence_id: item for item in context.evidence}
            unknown_plan_ids = sorted(declared_evidence.difference(evidence_by_id))
            if unknown_plan_ids:
                conflicting_evidence_ids.extend(unknown_plan_ids)
                blocking.append(
                    "unknown_evidence_ids: The plan references evidence that does not exist: "
                    + ", ".join(unknown_plan_ids)
                )
            for evidence_id in sorted(declared_evidence.intersection(evidence_by_id)):
                evidence = evidence_by_id[evidence_id]
                evidence_group = str(evidence.metadata.get("peer_group_id") or "")
                if context.peer_group_id and evidence_group != context.peer_group_id:
                    blocking.append(
                        f"wrong_peer_group: Evidence {evidence_id} belongs to {evidence_group or 'no group'}, "
                        f"not {context.peer_group_id}."
                    )
                if bool(evidence.metadata.get("is_accessory")):
                    blocking.append(
                        f"accessory_evidence: Evidence {evidence_id} belongs to an accessory, not a complete product."
                    )

        market_scope = plan.analysis_scopes.get("product_market_agent", {})
        insight_scope = plan.analysis_scopes.get("user_insight_agent", {})
        if market_scope and insight_scope:
            if market_scope.get("peer_group_id") != insight_scope.get("peer_group_id"):
                blocking.append("agent_peer_group_mismatch: The parallel Agents used different peer_group_id values.")
            market_asins = set(market_scope.get("selected_parent_asins") or [])
            insight_asins = set(insight_scope.get("selected_parent_asins") or [])
            if market_asins != insight_asins:
                blocking.append(
                    "agent_product_scope_mismatch: The parallel Agents used different selected_parent_asins."
                )

        for index, conclusion in enumerate(plan.conclusions):
            unknown_ids = sorted(set(conclusion.evidence_ids).difference(declared_evidence))
            if unknown_ids:
                conflicting_evidence_ids.extend(unknown_ids)
                blocking.append(
                    f"conclusion[{index}].evidence_ids: {', '.join(unknown_ids)} are not declared by the plan; "
                    "bind available evidence or remove the unsupported references."
                )
            if (
                conclusion.conclusion_type in FACTUAL_CONCLUSION_TYPES
                and not conclusion.evidence_ids
                and not conclusion.data_gaps
            ):
                blocking.append(
                    f"conclusion[{index}].unsupported_fact: Bind evidence or downgrade the claim to a "
                    "recommendation with an explicit data gap."
                )
            if (
                conclusion.conclusion_type == "recommendation"
                and not conclusion.evidence_ids
                and not conclusion.data_gaps
            ):
                warnings.append(
                    f"conclusion[{index}].uncaveated_recommendation: Add supporting evidence or an explicit "
                    "limitation."
                )

        content = self.content_skill.extract(plan.next_steps)
        for issue in self.content_skill.audit(content):
            message = f"{issue.code}: {issue.message}"
            (blocking if issue.blocking else warnings).append(message)

        plan_text = self._plan_text(context).casefold()
        for phrase in PEER_ATTRIBUTION_FORBIDDEN:
            if phrase.casefold() in plan_text:
                blocking.append(
                    f"peer_review_misattribution: Replace {phrase!r} with explicit peer-market terminology."
                )
        for claim in self.content_skill.config.rules.forbidden_claims:
            if claim.casefold() in plan_text:
                blocking.append(
                    "forbidden_plan_claim: Remove the unsupported or prohibited expression "
                    f"{claim!r} from positioning, conclusions, or next actions."
                )

        numeric_issues = self._unverified_numeric_claims(context)
        blocking.extend(numeric_issues)

        conflict_messages, conflict_ids = self._semantic_conflicts(plan.conclusions, plan.positioning)
        blocking.extend(conflict_messages)
        conflicting_evidence_ids.extend(conflict_ids)

        risk_issues = self._risk_conflicts(context)
        blocking.extend(risk_issues)

        for index, conclusion in enumerate(plan.conclusions):
            if conclusion.conclusion_type == "reasoned_hypothesis" and "待验证假设" not in conclusion.conclusion:
                blocking.append(
                    f"conclusion[{index}].unlabeled_hypothesis: Prefix the attribute-based inference with 待验证假设."
                )

        if context.product.target_market and context.product.target_market.casefold() not in plan_text:
            warnings.append(
                "target_market_missing: Include the user-selected target market in positioning or next actions."
            )

        if context.background_context is not None:
            for item in context.background_context.evidence:
                if not item.source_name or not item.source_uri:
                    blocking.append(
                        f"background_provenance_missing: Background evidence {item.evidence_id} has no source."
                    )
                if not item.jurisdiction:
                    warnings.append(
                        f"background_jurisdiction_missing: Background evidence {item.evidence_id} has no jurisdiction."
                    )
                if item.effective_date is None:
                    warnings.append(
                        "background_effective_date_missing: Background evidence "
                        f"{item.evidence_id} has no effective date."
                    )

        for gap in plan.data_gaps:
            unresolved.append(f"{gap.field}: {gap.reason}")

        blocking = self._unique(blocking)
        warnings = self._unique(warnings)
        unresolved = self._unique(unresolved)
        conflicting_evidence_ids = self._unique(conflicting_evidence_ids)
        if blocking:
            status = AuditStatus.REJECTED
        elif warnings:
            status = AuditStatus.WARNING
        else:
            status = AuditStatus.PASS
        return AuditResult(
            status=status,
            data_origin=plan.data_origin,
            issues=[*blocking, *warnings],
            conflicting_evidence_ids=conflicting_evidence_ids,
            unresolved_questions=unresolved,
            manual_review_required=bool(blocking),
        )

    def _unverified_numeric_claims(self, context: EvidenceAuditAgentInput) -> list[str]:
        allowed_payload: dict[str, object] = {"product": context.product.model_dump(mode="json")}
        if context.statistics is not None:
            allowed_payload["statistics"] = context.statistics.model_dump(mode="json")
        allowed_text = json.dumps(allowed_payload, ensure_ascii=False, default=str)
        allowed_numbers = set(re.findall(r"(?<![\w-])\d+(?:\.\d+)?%?(?![\w-])", allowed_text))
        for value in list(allowed_numbers):
            try:
                rounded = Decimal(value.removesuffix("%")).quantize(Decimal("0.01"))
            except InvalidOperation:
                continue
            allowed_numbers.add(format(rounded, "f").rstrip("0").rstrip("."))
        issues: list[str] = []
        for label, text, conclusion_type in self._claim_texts(context):
            if conclusion_type == "user_input":
                continue
            for value in re.findall(r"(?<![\w-])\d+(?:\.\d+)?%?", text):
                if value not in allowed_numbers:
                    issues.append(
                        f"{label}.unverified_numeric_claim: Remove {value!r} or bind it to validated structured "
                        "statistics/user input."
                    )
        return issues

    @staticmethod
    def _model_advisory(value: object) -> str:
        if isinstance(value, dict):
            message = value.get("description") or value.get("message") or json.dumps(value, ensure_ascii=False)
        else:
            message = str(value)
        return f"model_advisory: {message}"

    @staticmethod
    def _refuted_model_finding(
        value: object,
        valid_evidence_ids: set[str],
        declared_evidence_ids: set[str],
        *,
        valid_evidence_less_hypotheses: bool,
    ) -> bool:
        if isinstance(value, dict):
            text = str(value.get("description") or value.get("message") or value)
        else:
            text = str(value)
        normalized = text.casefold()
        uuid_references = set(
            re.findall(
                r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                normalized,
            )
        )
        normalized_valid_ids = {item.casefold() for item in valid_evidence_ids}
        positive_confirmation = any(
            phrase in normalized
            for phrase in ("matches the expected", "matches expected", "correctly labeled", "no conflict")
        )
        if positive_confirmation:
            return True
        hypothesis_evidence_claim = "reasoned_hypothesis" in normalized and any(
            phrase in normalized for phrase in ("empty evidence", "zero evidence", "no evidence", "lack evidence")
        )
        if hypothesis_evidence_claim and valid_evidence_less_hypotheses:
            return True
        unused_evidence_claim = any(
            phrase in normalized
            for phrase in ("not cited", "unused evidence", "not referenced by the plan", "未引用")
        )
        if unused_evidence_claim and uuid_references and uuid_references.issubset(normalized_valid_ids):
            return True
        missing_claim = any(
            phrase in normalized
            for phrase in ("missing", "not present", "not included", "absent", "不存在", "缺失")
        )
        if not missing_claim:
            return False
        if uuid_references and uuid_references.issubset(normalized_valid_ids):
            return True
        statistics_provenance_claim = "statistics" in normalized and (
            "evidence_ids" in normalized or "evidence ids" in normalized
        )
        cites_declared_plan_id = any(evidence_id.casefold() in normalized for evidence_id in declared_evidence_ids)
        return statistics_provenance_claim and not cites_declared_plan_id

    @staticmethod
    def _semantic_conflicts(
        conclusions: list[Conclusion], positioning: str
    ) -> tuple[list[str], list[str]]:
        records = [("positioning", positioning, [])]
        records.extend(
            (f"conclusion[{index}]", conclusion.conclusion, conclusion.evidence_ids)
            for index, conclusion in enumerate(conclusions)
        )
        messages: list[str] = []
        evidence_ids: list[str] = []
        for left_terms, right_terms in CONFLICT_PAIRS:
            left_records = [record for record in records if any(term in record[1].casefold() for term in left_terms)]
            right_records = [record for record in records if any(term in record[1].casefold() for term in right_terms)]
            if left_records and right_records:
                left_labels = ", ".join(record[0] for record in left_records)
                right_labels = ", ".join(record[0] for record in right_records)
                messages.append(
                    "semantic_conflict: Resolve opposing positioning claims between "
                    f"{left_labels} and {right_labels}; keep one interpretation and cite its evidence."
                )
                evidence_ids.extend(
                    evidence_id
                    for record in [*left_records, *right_records]
                    for evidence_id in record[2]
                )
        return messages, evidence_ids

    def _risk_conflicts(self, context: EvidenceAuditAgentInput) -> list[str]:
        text = self._plan_text(context).casefold()
        issues: list[str] = []
        for risk in context.product.known_risks:
            normalized = risk.casefold().strip()
            if normalized and (f"no {normalized}" in text or f"{normalized}-free" in text):
                issues.append(
                    f"known_risk_conflict: The plan denies the declared risk {risk!r}; replace the denial with "
                    "a verified limitation or mitigation."
                )
        return issues

    @staticmethod
    def _claim_texts(
        context: EvidenceAuditAgentInput,
    ) -> list[tuple[str, str, str | None]]:
        plan = context.operation_plan
        values: list[tuple[str, str, str | None]] = [("positioning", plan.positioning, None)]
        values.extend(
            (f"conclusion[{index}]", conclusion.conclusion, conclusion.conclusion_type)
            for index, conclusion in enumerate(plan.conclusions)
        )
        values.extend((f"next_steps[{index}]", step, None) for index, step in enumerate(plan.next_steps))
        return values

    def _plan_text(self, context: EvidenceAuditAgentInput) -> str:
        return "\n".join(text for _, text, _ in self._claim_texts(context))

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
