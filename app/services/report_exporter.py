import html
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.enums import AuditStatus, DataOrigin
from app.schemas.common import DataGap, utc_now
from app.schemas.report import (
    DEMO_DISCLAIMER,
    REAL_DISCLAIMER,
    FinalReport,
    ReportSectionDescriptor,
)
from app.skills.operation_content import OperationContentSkill
from app.workflows.state import TradePilotState


class ReportExporter:
    REAL_GAP_FIELD_TITLES = {
        "peer_product_market": "同类市场商品",
        "peer_review_sample": "同类商品评论样本",
        "product_specifications": "商品参数",
        "product_features": "商品功能",
        "product_knowledge": "商品资料",
        "review_insight": "评论样本",
        "statistics": "统计数据",
        "peer_group": "同类商品组",
        "competitor_offers": "同类商品报价",
        "operation_plan": "运营决策",
        "evidence_ids": "证据引用",
    }
    SECTION_TITLES = {
        "executive_summary": "Executive summary",
        "product_profile": "Product profile",
        "product_market_analysis": "Product market analysis",
        "user_insight": "User insight",
        "operation_plan": "Operation plan",
        "content_playbook": "Content playbook",
        "tax_and_tariff_snapshot": "Tax and tariff snapshot",
        "tariff_selection_impact": "Tariff impact on selection",
        "audit_result": "Evidence audit",
        "data_limitations": "Data limitations",
        "evidence_index": "Evidence index",
        "next_actions": "Next actions",
        "new_product_overview": "新商品概况",
        "peer_market_product_analysis": "同类市场商品分析",
        "peer_market_user_insights": "同类市场用户洞察",
        "launch_marketing_strategy": "新商品上市营销策略",
        "feature_to_peer_concern_mapping": "商品特征与同类用户关注点的对应分析",
        "prelaunch_considerations": "新商品上市前注意事项",
        "data_supported_conclusions": "数据支持的结论",
        "reasoned_hypotheses": "基于商品属性的待验证假设",
        "data_limitations_and_evidence_index": "数据限制与证据索引",
    }

    def __init__(self, report_dir: Path, content_skill: OperationContentSkill | None = None) -> None:
        self.report_dir = report_dir
        self.content_skill = content_skill or OperationContentSkill.from_default()

    def export(self, state: TradePilotState) -> FinalReport:
        if state.audit_result is None:
            raise ValueError("audit result is required before report export")
        self.report_dir.mkdir(parents=True, exist_ok=True)
        report_id = str(uuid4())
        json_path = (self.report_dir / f"{report_id}.json").resolve()
        markdown_path = (self.report_dir / f"{report_id}.md").resolve()
        sections = self._sections(state)
        origin = state.audit_result.data_origin
        report = FinalReport(
            report_id=report_id,
            run_id=state.run_id,
            version=max(1, state.report_version + 1),
            audit_status=state.audit_result.status,
            data_origin=origin,
            implementation_status=state.audit_result.implementation_status,
            is_demo=origin is DataOrigin.DEMO,
            disclaimer=DEMO_DISCLAIMER if origin is DataOrigin.DEMO else REAL_DISCLAIMER,
            sections=sections,
            section_index=self._section_index(sections),
            markdown_path=str(markdown_path),
            json_path=str(json_path),
            created_at=utc_now(),
        )
        json_path.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        markdown_path.write_text(self._markdown_with_anchors(report), encoding="utf-8")
        return report

    @classmethod
    def _section_index(cls, sections: dict[str, Any]) -> dict[str, ReportSectionDescriptor]:
        return {
            key: ReportSectionDescriptor(
                section_id=key.replace("_", "-"),
                title=cls.SECTION_TITLES.get(key, key.replace("_", " ").title()),
            )
            for key in sections
        }

    @classmethod
    def _markdown_with_anchors(cls, report: FinalReport) -> str:
        markdown = cls._markdown(report)
        for descriptor in report.section_index.values():
            heading = f"## {descriptor.title}"
            if heading in markdown:
                markdown = markdown.replace(
                    heading,
                    f'<a id="{descriptor.section_id}"></a>\n\n{heading}',
                    1,
                )
        return markdown

    def _sections(self, state: TradePilotState) -> dict[str, Any]:
        plan = state.operation_plan
        audit = state.audit_result
        if audit is None:
            raise ValueError("audit result is required before report export")
        content = self.content_skill.extract(plan.next_steps) if plan else None
        limitations = self._collect_gaps(state)
        rendered_limitations = (
            [self._real_gap(gap) for gap in limitations]
            if audit.data_origin is not DataOrigin.DEMO
            else [gap.model_dump(mode="json") for gap in limitations]
        )
        actions = (
            [step.removeprefix("ACTION: ") for step in plan.next_steps if step.startswith("ACTION: ")]
            if plan
            else []
        )
        evidence_index = self._evidence_index(state)
        customs_broker_review_required = bool(
            state.background_context
            and state.background_context.decision_inputs.get("manual_review_required")
        )
        return {
            "executive_summary": {
                "product_name": state.product_profile.name,
                "target_market": state.target_market or state.product_profile.target_market,
                "positioning": plan.positioning if plan else "",
                "decision_status": plan.status.value if plan else None,
                "audit_status": audit.status.value,
                "manual_review_required": (
                    audit.manual_review_required or customs_broker_review_required
                ),
                "evidence_audit_manual_review_required": audit.manual_review_required,
                "customs_broker_review_required": customs_broker_review_required,
                "evidence_count": len(evidence_index),
                "limitation_count": len(limitations),
            },
            "product_profile": state.product_profile.model_dump(mode="json"),
            "product_market_analysis": self._dump(state.product_market_analysis),
            "user_insight": self._dump(state.user_insight),
            "operation_plan": self._dump(plan),
            "content_playbook": content.as_dict() if content else None,
            "tax_and_tariff_snapshot": self._tax_and_tariff_snapshot(state),
            "tariff_selection_impact": self._tariff_selection_impact(state),
            "audit_result": audit.model_dump(mode="json"),
            "data_limitations": rendered_limitations,
            "evidence_index": evidence_index,
            "next_actions": actions,
            "new_product_overview": {
                "product": state.product_profile.model_dump(mode="json"),
                "vision_analysis": state.vision_analysis,
                "peer_group_id": state.peer_group_id,
            },
            "peer_market_product_analysis": self._dump(state.product_market_analysis),
            "peer_market_user_insights": self._dump(state.user_insight),
            "launch_marketing_strategy": self._dump(plan),
            "feature_to_peer_concern_mapping": self._feature_concern_mapping(state),
            "prelaunch_considerations": self._prelaunch_considerations(state),
            "data_supported_conclusions": self._data_supported_conclusions(state),
            "reasoned_hypotheses": self._reasoned_hypotheses(state),
            "data_limitations_and_evidence_index": {
                "limitations": rendered_limitations,
                "match_limitations": state.match_limitations,
                "review_sample_scope": state.review_sample_scope,
                "evidence_index": evidence_index,
            },
        }

    @staticmethod
    def _tax_and_tariff_snapshot(state: TradePilotState) -> dict[str, object] | None:
        context = state.background_context
        if context is None:
            return None
        tariff_evidence = [
            item
            for item in context.evidence
            if item.context_type in {"tariff_rate", "import_duty", "customs_duty"}
        ]
        if not tariff_evidence and not context.data_gaps:
            return None
        return {
            "provider": context.provider,
            "market": context.query.market,
            "jurisdiction": context.query.jurisdiction,
            "effective_date": (
                context.query.effective_date.isoformat() if context.query.effective_date else None
            ),
            "query_date": context.query.query_date.isoformat(),
            "matched_context_types": sorted({item.context_type for item in tariff_evidence}),
            "decision_inputs": context.decision_inputs,
            "tariff_evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "context_type": item.context_type,
                    "summary": item.content,
                    "source_name": item.source_name,
                    "source_uri": item.source_uri,
                    "effective_date": item.effective_date.isoformat() if item.effective_date else None,
                    "jurisdiction": item.jurisdiction,
                    "confidence": item.confidence,
                }
                for item in tariff_evidence
            ],
            "data_gaps": [gap.model_dump(mode="json") for gap in context.data_gaps],
        }

    @staticmethod
    def _evidence_index(state: TradePilotState) -> list[dict[str, object]]:
        product_titles = {
            str(item.get("parent_asin")): str(item.get("title"))
            for item in state.selected_peer_products
            if item.get("parent_asin") and item.get("title")
        }
        product_titles.update({
            str(item.metadata.get("parent_asin")): item.source_name
            for item in state.rag_evidence
            if item.knowledge_type.value == "product_knowledge"
            and item.metadata.get("parent_asin")
        })
        result: list[dict[str, object]] = []
        for number, item in enumerate(state.rag_evidence, start=1):
            parent_asin = str(item.metadata.get("parent_asin") or "")
            if item.knowledge_type.value == "review_insight":
                source_title = product_titles.get(parent_asin) or item.source_name
                display_title = f"{source_title}用户评论"
                evidence_type_label = "同类商品真实评论"
            elif item.evidence_type == "product_background":
                display_title = item.source_name
                evidence_type_label = "商品背景真实资料"
            elif item.evidence_type == "sql_statistics":
                display_title = "同类市场商品统计"
                evidence_type_label = "同类商品组统计"
            else:
                display_title = item.source_name
                evidence_type_label = "同类商品真实资料"
            result.append(
                {
                    "display_number": number,
                    "display_label": f"证据{number}",
                    "display_title": display_title,
                    "evidence_type_label": evidence_type_label,
                    "support_summary": ReportExporter._evidence_support_summary(item),
                    "detail_path": (
                        f"/api/v1/analysis-runs/{state.run_id}/evidence/{item.evidence_id}"
                    ),
                    "evidence_id": item.evidence_id,
                    "knowledge_type": item.knowledge_type.value,
                    "source_name": item.source_name,
                    "source_uri": item.source_uri,
                    "excerpt": item.excerpt,
                    "data_origin": item.data_origin.value,
                    "metadata": item.metadata,
                }
            )
        return result

    @staticmethod
    def _evidence_support_summary(item: object) -> str:
        evidence_type = str(getattr(item, "evidence_type", ""))
        knowledge_type = getattr(getattr(item, "knowledge_type", None), "value", "")
        excerpt = " ".join(str(getattr(item, "excerpt", "") or "").split())
        if evidence_type == "product_background":
            return "美国关税候选归类及税率资料；正式进口前仍需人工复核。"
        if evidence_type == "sql_statistics":
            return "同类商品组的价格、评分和评价数量等真实结构化统计。"
        if knowledge_type == "review_insight":
            if any("\u4e00" <= character <= "\u9fff" for character in excerpt):
                return excerpt[:280]
            return "同类市场商品的真实用户评论；原始文本未改写，可通过下方链接查看。"
        if any("\u4e00" <= character <= "\u9fff" for character in excerpt):
            return excerpt[:280]
        return "同类市场商品的真实商品资料，包含名称、功能、参数等原始字段。"

    @staticmethod
    def _tariff_selection_impact(state: TradePilotState) -> dict[str, object] | None:
        context = state.background_context
        if context is None or not context.decision_inputs:
            return None
        decision_inputs = context.decision_inputs
        profiles = decision_inputs.get("tariff_profiles")
        if not profiles and not context.data_gaps:
            return None
        return {
            "summary": decision_inputs.get("tariff_summary") or "",
            "risk_flags": decision_inputs.get("tariff_risk_flags") or [],
            "manual_review_required": bool(decision_inputs.get("manual_review_required")),
            "selection_impact": decision_inputs.get("selection_impact") or [],
            "primary_tariff_profile": decision_inputs.get("primary_tariff_profile") or {},
        }

    @classmethod
    def _real_gap(cls, gap: DataGap) -> dict[str, str | None]:
        reason = gap.reason.strip()
        if not any("\u4e00" <= character <= "\u9fff" for character in reason):
            reason = "缺少形成可靠结论所需的数据或证据。"
        return {
            "code": gap.code,
            "field": cls.REAL_GAP_FIELD_TITLES.get(gap.field, "相关数据"),
            "reason": reason,
            "required_for": "形成更可靠的结论" if gap.required_for else None,
        }

    @staticmethod
    def _feature_concern_mapping(state: TradePilotState) -> list[dict[str, str]]:
        features = (
            state.product_market_analysis.product_functions
            if state.product_market_analysis and state.product_market_analysis.product_functions
            else state.product_profile.features
        )
        insight = state.user_insight
        concerns = (
            [*insight.common_needs, *insight.pain_points, *insight.feature_usage_maintenance_concerns]
            if insight
            else []
        )
        concerns = ReportExporter._customer_items(concerns)
        return [
            {
                "product_feature": feature,
                "peer_user_concern": concerns[index % len(concerns)] if concerns else "尚无对应评论证据",
                "interpretation": "属性与同类评论关注点的对应观察，不代表已经验证的因果关系。",
            }
            for index, feature in enumerate(features)
        ]

    @staticmethod
    def _prelaunch_considerations(state: TradePilotState) -> list[str]:
        values = [*state.match_limitations]
        if state.product_market_analysis:
            values.extend(state.product_market_analysis.prelaunch_validations)
            values.extend(f"缺失参数：{item}" for item in state.product_market_analysis.missing_parameters)
        if state.user_insight:
            values.extend(ReportExporter._customer_items(state.user_insight.prelaunch_validations))
        return list(dict.fromkeys(values))

    @staticmethod
    def _data_supported_conclusions(state: TradePilotState) -> list[dict[str, object]]:
        if state.operation_plan is None:
            return []
        return [
            conclusion.model_dump(mode="json")
            for conclusion in state.operation_plan.conclusions
            if conclusion.evidence_ids and conclusion.conclusion_type != "reasoned_hypothesis"
        ]

    @staticmethod
    def _reasoned_hypotheses(state: TradePilotState) -> list[str]:
        values: list[str] = []
        if state.product_market_analysis:
            values.extend(state.product_market_analysis.reasoned_hypotheses)
        if state.user_insight:
            values.extend(state.user_insight.reasoned_hypotheses)
        if state.operation_plan:
            values.extend(
                item.conclusion
                for item in state.operation_plan.conclusions
                if item.conclusion_type == "reasoned_hypothesis"
            )
        return list(dict.fromkeys(values))

    @staticmethod
    def _collect_gaps(state: TradePilotState) -> list[DataGap]:
        groups = [
            state.data_gaps,
            state.product_profile.data_gaps,
            state.product_market_analysis.data_gaps if state.product_market_analysis else [],
            state.user_insight.data_gaps if state.user_insight else [],
            state.operation_plan.data_gaps if state.operation_plan else [],
        ]
        result: list[DataGap] = []
        seen: set[tuple[str, str, str, str | None]] = set()
        for gap in (item for group in groups for item in group):
            key = (gap.code, gap.field, gap.reason, gap.required_for)
            if key not in seen:
                seen.add(key)
                result.append(gap)
        return result

    @staticmethod
    def _dump(value: object) -> dict[str, object] | None:
        return value.model_dump(mode="json") if value is not None else None  # type: ignore[union-attr]

    @staticmethod
    def _markdown(report: FinalReport) -> str:
        if not report.is_demo:
            return ReportExporter._real_markdown(report)
        sections = report.sections
        summary = sections["executive_summary"]
        plan = sections.get("operation_plan") or {}
        content = sections.get("content_playbook") or {}
        audit = sections.get("audit_result") or {}
        limitations = sections.get("data_limitations") or []
        evidence = sections.get("evidence_index") or []
        actions = sections.get("next_actions") or []
        tariff_snapshot = sections.get("tax_and_tariff_snapshot") or {}
        tariff_impact = sections.get("tariff_selection_impact") or {}

        lines = [
            "# TradePilot DEMO Operations Report",
            "",
            f"> {report.disclaimer}",
            "",
            f"- report_version: `{report.version}`",
            f"- data_origin: `{report.data_origin.value}`",
            "- implementation_status: `scaffold`",
            f"- audit_status: `{report.audit_status.value}`",
            "",
        ]
        if report.audit_status is AuditStatus.REJECTED or summary.get(
            "evidence_audit_manual_review_required"
        ):
            lines.extend(
                [
                    "## Manual review required",
                    "",
                    "The bounded correction did not clear every blocking issue. Do not publish the draft until "
                    "the listed audit findings are resolved.",
                    "",
                ]
            )

        lines.extend(
            [
                "## Executive summary",
                "",
                f"- Product: {summary.get('product_name') or 'Not supplied'}",
                f"- Target market: {summary.get('target_market') or 'Not supplied'}",
                f"- Decision status: `{summary.get('decision_status') or 'not_available'}`",
                f"- Evidence references: {summary.get('evidence_count', 0)}",
                f"- Recorded limitations: {summary.get('limitation_count', 0)}",
                "",
                str(summary.get("positioning") or "No positioning recommendation is available."),
                "",
                "## Key conclusions",
                "",
            ]
        )
        conclusions = plan.get("conclusions", [])
        if conclusions:
            for conclusion in conclusions:
                evidence_ids = conclusion.get("evidence_ids") or []
                suffix = f" [evidence: {', '.join(evidence_ids)}]" if evidence_ids else ""
                lines.append(f"- {conclusion.get('conclusion', '')}{suffix}")
        else:
            lines.append("- No structured conclusions are available.")

        lines.extend(["", "## Content playbook", ""])
        if content:
            lines.extend(["### Product title", "", str(content.get("title") or ""), ""])
            lines.extend(["### Selling-point bullets", ""])
            lines.extend(f"- {bullet}" for bullet in content.get("bullets", []))
            lines.extend(["", "### Product description", "", str(content.get("description") or ""), ""])
            lines.extend(["### Advertising keywords", ""])
            lines.append(", ".join(content.get("keywords", [])))
            lines.extend(["", "### Customer-service drafts", ""])
            for name, text in content.get("customer_service", {}).items():
                lines.extend([f"#### {name.replace('_', ' ').title()}", "", str(text), ""])
        else:
            lines.extend(["No content bundle was generated.", ""])

        lines.extend(["", "## Tax and tariff snapshot", ""])
        if tariff_snapshot:
            lines.append(f"- Provider: `{tariff_snapshot.get('provider') or 'not_available'}`")
            lines.append(f"- Market: {tariff_snapshot.get('market') or 'Not supplied'}")
            lines.append(f"- Jurisdiction: {tariff_snapshot.get('jurisdiction') or 'Not supplied'}")
            if tariff_snapshot.get("effective_date"):
                lines.append(f"- Effective date: {tariff_snapshot['effective_date']}")
            evidence_items = tariff_snapshot.get("tariff_evidence") or []
            if evidence_items:
                lines.append("")
                for item in evidence_items:
                    lines.append(
                        f"- `{item['evidence_id']}` - {item['summary']} ({item['source_name']})"
                    )
            gaps = tariff_snapshot.get("data_gaps") or []
            if gaps:
                lines.append("")
                lines.extend(f"- Data gap: {gap['field']} / {gap['reason']}" for gap in gaps)
        else:
            lines.append("- No tariff evidence was included in this report.")

        lines.extend(["", "## Tariff impact on selection", ""])
        if tariff_impact:
            if tariff_impact.get("summary"):
                lines.append(str(tariff_impact["summary"]))
                lines.append("")
            for item in tariff_impact.get("selection_impact") or []:
                lines.append(f"- {item}")
            risk_flags = tariff_impact.get("risk_flags") or []
            if risk_flags:
                lines.append("")
                lines.append(f"- Risk flags: {', '.join(risk_flags)}")
            lines.append(
                f"- Manual review required: `{str(bool(tariff_impact.get('manual_review_required'))).lower()}`"
            )
        else:
            lines.append("- No tariff decision input was available for selection impact analysis.")

        lines.extend(["## Evidence audit", "", f"Status: `{audit.get('status', 'not_available')}`", ""])
        issues = audit.get("issues") or []
        lines.extend(f"- {issue}" for issue in issues)
        if not issues:
            lines.append("- No blocking or warning issues were found.")

        lines.extend(["", "## Data limitations", ""])
        if limitations:
            lines.extend(f"- **{gap['field']}**: {gap['reason']}" for gap in limitations)
        else:
            lines.append("- No additional data gaps were recorded.")

        lines.extend(["", "## Evidence index", ""])
        if evidence:
            for item in evidence:
                lines.append(
                    f"- `{item['evidence_id']}` - {item['source_name']} "
                    f"({item['knowledge_type']}, {item['data_origin']}): {item['excerpt']}"
                )
        else:
            lines.append("- No evidence references were supplied.")

        lines.extend(["", "## Next actions", ""])
        lines.extend(f"{index}. {action}" for index, action in enumerate(actions, start=1))
        if not actions:
            lines.append("1. Resolve audit findings and add the missing evidence before publication.")
        lines.extend(
            [
                "",
                "## Scaffold boundary",
                "",
                "This report uses deterministic Demo rules. Real model execution, live-market validation, and "
                "production publishing remain outside the current scaffold.",
                "",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _real_markdown(report: FinalReport) -> str:
        sections = report.sections
        overview = sections["new_product_overview"]
        product = overview["product"]
        market = sections.get("peer_market_product_analysis") or {}
        insight = sections.get("peer_market_user_insights") or {}
        strategy = sections.get("launch_marketing_strategy") or {}
        mappings = sections.get("feature_to_peer_concern_mapping") or []
        considerations = sections.get("prelaunch_considerations") or []
        supported = sections.get("data_supported_conclusions") or []
        hypotheses = sections.get("reasoned_hypotheses") or []
        limitations = sections.get("data_limitations_and_evidence_index") or {}
        evidence = limitations.get("evidence_index") or []
        evidence_by_id = {item["evidence_id"]: item for item in evidence}
        tariff_snapshot = sections.get("tax_and_tariff_snapshot") or {}
        tariff_impact = sections.get("tariff_selection_impact") or {}
        customer_text = ReportExporter._customer_text
        lines = [
            "# TradePilot 新商品上市分析报告",
            "",
            f"> {report.disclaimer}",
            "",
            "## 新商品概况",
            "",
            f"- 商品名称：{customer_text(product.get('name', ''))}",
            f"- 商品类别：{customer_text(market.get('product_category') or product.get('category', ''))}",
            "- 分析范围：基于 Amazon 同类市场商品及其真实评论样本。",
            "- 本商品为待上市新商品，不包含自身销量、评分或评论。",
            "",
            "## 同类市场商品分析",
            "",
            customer_text(market.get("product_summary") or "暂无可审计的同类商品分析。"),
            "",
            customer_text(market.get("price_analysis") or "价格数据不足。"),
            "",
        ]
        for label, key in (
            ("功能和参数基线", "feature_baseline"),
            ("商品结构与使用场景", "structure_and_scenarios"),
            ("品牌与定位", "brand_positioning"),
            ("同质化问题", "homogenization_risks"),
            ("差异化机会", "differentiation_opportunities"),
        ):
            lines.extend([f"### {label}", ""])
            lines.extend(f"- {customer_text(item)}" for item in market.get(key, []))
            if not market.get(key):
                lines.append("- 数据不足。")
            lines.append("")
        lines.extend(
            [
                "## 同类市场用户洞察",
                "",
                customer_text(insight.get("insight_summary") or "暂无同类商品评论样本洞察。"),
                "",
            ]
        )
        for label, key in (
            ("同类评论样本中的用户需求", "common_needs"),
            ("评论样本中的正面体验", "positive_experiences"),
            ("评论样本中的痛点", "pain_points"),
            ("购买决策因素", "purchase_factors"),
            ("功能、使用和维护关注点", "feature_usage_maintenance_concerns"),
            ("可转化为卖点的需求", "convertible_selling_points"),
            ("产品优化方向", "optimization_directions"),
        ):
            lines.extend([f"### {label}", ""])
            insight_items = ReportExporter._customer_items(insight.get(key, []))
            lines.extend(f"- {customer_text(item)}" for item in insight_items)
            if not insight_items:
                lines.append("- 评论证据不足。")
            lines.append("")
        lines.extend(["## 新商品上市营销策略", ""])
        lines.extend(
            [
                "### 营销目标",
                "",
                customer_text(strategy.get("marketing_objective") or "证据不足，暂未形成明确营销目标。"),
                "",
                "### 市场定位",
                "",
                customer_text(strategy.get("positioning") or "证据不足，暂未形成市场定位。"),
                "",
            ]
        )
        for label, key in (
            ("目标客群", "target_segments"),
            ("核心价值主张", "value_propositions"),
            ("定价策略", "pricing_strategy"),
            ("渠道策略", "channel_strategy"),
            ("传播信息策略", "messaging_strategy"),
            ("上市执行动作", "launch_actions"),
        ):
            lines.extend([f"### {label}", ""])
            lines.extend(f"- {customer_text(item)}" for item in strategy.get(key, []))
            if not strategy.get(key):
                lines.append("- 证据或输入不足，暂不生成确定性策略。")
            lines.append("")
        lines.extend(["## 商品特征与同类用户关注点的对应分析", ""])
        for item in mappings:
            lines.append(
                f"- {customer_text(item['product_feature'])} ↔ "
                f"{customer_text(item['peer_user_concern'])}。{customer_text(item['interpretation'])}"
            )
        if not mappings:
            lines.append("- 暂无可对应的商品特征与评论关注点。")
        lines.extend(["", "## 新商品上市前注意事项", ""])
        lines.extend(f"- {customer_text(item)}" for item in considerations)
        if not considerations:
            lines.append("- 补充验证数据后再形成确定性结论。")
        lines.extend(["", "## 数据支持的结论", ""])
        for item in supported:
            citations = [
                evidence_by_id[evidence_id]
                for evidence_id in item.get("evidence_ids") or []
                if evidence_id in evidence_by_id
            ]
            suffix = " ".join(
                f"[{citation['display_label']}]({citation['detail_path']})" for citation in citations
            )
            lines.append(f"- {customer_text(item['conclusion'])} {suffix}".rstrip())
        if not supported:
            lines.append("- 暂无通过证据审校的数据结论。")
        lines.extend(["", "## 基于商品属性的待验证假设", ""])
        lines.extend(f"- {customer_text(item)}" for item in hypotheses)
        if not hypotheses:
            lines.append("- 暂无属性推导假设。")
        lines.extend(["", "## 美国税费快照", ""])
        if tariff_snapshot:
            lines.append(f"- 数据提供方：`{tariff_snapshot.get('provider') or '未提供'}`")
            lines.append(f"- 市场：{tariff_snapshot.get('market') or '未提供'}")
            lines.append(f"- 法域：{tariff_snapshot.get('jurisdiction') or '未提供'}")
            if tariff_snapshot.get("effective_date"):
                lines.append(f"- 生效日期：{tariff_snapshot['effective_date']}")
            tariff_summary = (tariff_snapshot.get("decision_inputs") or {}).get("tariff_summary")
            tariff_citations = [
                evidence_by_id[item["evidence_id"]]
                for item in tariff_snapshot.get("tariff_evidence") or []
                if item["evidence_id"] in evidence_by_id
            ]
            tariff_links = " ".join(
                f"[{item['display_label']}]({item['detail_path']})" for item in tariff_citations
            )
            if tariff_summary:
                lines.append(f"- {customer_text(tariff_summary)} {tariff_links}".rstrip())
            for gap in tariff_snapshot.get("data_gaps") or []:
                lines.append(f"- 数据缺口：{gap['field']}：{gap['reason']}")
            if not tariff_snapshot.get("tariff_evidence") and not tariff_snapshot.get("data_gaps"):
                lines.append("- 暂无可展示的税费证据。")
        else:
            lines.append("- 本报告未包含美国税费证据。")
        lines.extend(["", "## 美国税费对选品影响", ""])
        if tariff_impact:
            if tariff_impact.get("summary"):
                lines.append(str(tariff_impact["summary"]))
                lines.append("")
            for item in tariff_impact.get("selection_impact") or []:
                lines.append(f"- {item}")
            risk_flags = tariff_impact.get("risk_flags") or []
            if risk_flags:
                translated_flags = {
                    "broker_review_required": "需要报关归类复核",
                    "candidate_mapping_low_confidence": "候选归类置信度有限",
                    "additional_duty_present": "存在附加税信息",
                    "special_rate_text_present": "存在特殊税率说明",
                    "non_free_general_rate": "一般税率非 Free",
                }
                lines.append(
                    "- 风险标记："
                    + "、".join(translated_flags.get(flag, flag) for flag in risk_flags)
                )
            lines.append(
                f"- 是否需要人工复核：{'是' if tariff_impact.get('manual_review_required') else '否'}"
            )
        else:
            lines.append("- 当前没有可直接用于选品决策的税费摘要输入。")
        lines.extend(["", "## 数据限制与证据索引", ""])
        for item in limitations.get("match_limitations", []):
            lines.append(f"- 匹配限制：{item}")
        for item in limitations.get("limitations", []):
            lines.append(f"- {item['field']}：{item['reason']}")
        for item in evidence:
            metadata = item.get("metadata") or {}
            support_summary = customer_text(item.get("support_summary") or "")
            is_peer_evidence = metadata.get("evidence_scope") == "peer_product"
            source_label = "来源商品" if is_peer_evidence else "来源"
            source_value = customer_text(item["display_title"].removesuffix("用户评论"))
            source_row = metadata.get("source_row")
            lines.extend(
                [
                    f"### {item['display_label']}｜{customer_text(item['display_title'])}",
                    "",
                    f"- 证据类型：{item['evidence_type_label']}",
                    f"- 支持内容：{support_summary or '未提供摘要。'}",
                    f"- {source_label}：{source_value}",
                    (
                        f"- 原始位置：源数据第 {source_row} 行"
                        if source_row
                        else "- 原始位置：可通过下方证据详情查看。"
                    ),
                    f"- [查看原始证据]({item['detail_path']})",
                    "",
                ]
            )
        if not evidence:
            lines.append("- 无有效证据索引。")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _customer_text(value: object) -> str:
        """Hide machine identifiers in rendered prose while preserving JSON/link mappings."""
        text = " ".join(str(value).split())
        replacements = {
            "removable reservoir and visible water level": "可拆卸储水容器和可视水位",
            "removable reservoir": "可拆卸储水容器",
            "reservoir": "储水容器",
            "visible water level": "可视水位",
            "Professional, Caring, Modern": "专业、关怀、现代",
            "Professional, Reassuring, Modern": "专业、可信、现代",
        }
        for source, target in replacements.items():
            text = re.sub(re.escape(source), target, text, flags=re.IGNORECASE)
        text = re.sub(
            r"^基于\s*\d+\s*款同类商品共\s*\d+\s*条评论的统计分析[，,]\s*",
            "参考 Amazon 数据中的同类市场商品及其真实评论样本，",
            text,
        )
        text = re.sub(
            r"[（(]\s*(?:evidence_id|证据ID)\s*[:：]\s*[^)）]*[)）]",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bevidence_id\s*[:：]\s*[A-Za-z0-9_.:-]+",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"(?<![A-Z0-9])B0[A-Z0-9]{8}(?![A-Z0-9])", "同类商品样本", text)
        text = re.sub(
            r"(?:同类商品样本\s*[,，、]\s*)+同类商品样本",
            "多个同类商品样本",
            text,
        )
        text = text.replace("用户普遍关注", "同类商品评论样本中出现对")
        text = text.replace("所有竞品", "所检索的同类商品样本")
        text = text.replace("多数竞品", "所检索的多个同类商品样本")
        text = re.sub(r"[ \t]+([，。；：！？])", r"\1", text).strip()
        text = html.escape(text, quote=False)
        return re.sub(r"([\\`*_\[\]])", r"\\\1", text)

    @staticmethod
    def _customer_items(values: object) -> list[str]:
        if not isinstance(values, list):
            return []
        unsupported_markers = ("无直接引用", "no direct citation", "no direct evidence")
        return [
            str(item)
            for item in values
            if not any(marker in str(item).casefold() for marker in unsupported_markers)
        ]
