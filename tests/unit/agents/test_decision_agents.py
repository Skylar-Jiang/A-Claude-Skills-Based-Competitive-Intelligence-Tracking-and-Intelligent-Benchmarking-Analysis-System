from decimal import Decimal

from langchain_core.runnables import RunnableSequence

from app.agents.contracts import EvidenceAuditAgentInput, OperationsDecisionAgentInput
from app.agents.evidence_audit import EvidenceAuditAgent
from app.agents.operations_decision import OperationsDecisionAgent
from app.core.enums import AgentStatus, AuditStatus, DataOrigin
from app.schemas.analysis import AuditResult, OperationPlan, ProductMarketAnalysis, UserInsight
from app.schemas.common import Conclusion
from app.schemas.product import ProductProfile
from app.skills.operation_content import OperationContentSkill
from app.statistics.contracts import StatisticsResult
from tests.builders import build_market_analysis, build_user_insight


def test_decision_agents_expose_typed_demo_scaffold_outputs(demo_product: ProductProfile) -> None:
    operations_agent = OperationsDecisionAgent()
    audit_agent = EvidenceAuditAgent()

    assert isinstance(operations_agent.chain, RunnableSequence)
    assert isinstance(audit_agent.chain, RunnableSequence)

    plan = operations_agent.run(
        OperationsDecisionAgentInput(
            product=demo_product,
            product_market_analysis=build_market_analysis(),
            user_insight=build_user_insight(),
        )
    )
    audit = audit_agent.run(EvidenceAuditAgentInput(product=demo_product, operation_plan=plan))

    assert isinstance(plan, OperationPlan)
    assert isinstance(audit, AuditResult)
    assert audit.status is AuditStatus.PASS
    for output in (plan, audit):
        assert output.data_origin is DataOrigin.DEMO
        assert output.implementation_status.value == "scaffold"


def test_decision_agent_generates_versioned_content_and_evidence_bound_plan(
    demo_product: ProductProfile,
) -> None:
    product = demo_product.model_copy(
        update={
            "features": ["compact storage"],
            "use_scenarios": ["dorm rooms"],
            "target_market": "United States",
            "target_audience": ["college students"],
        }
    )
    market = ProductMarketAnalysis(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        evidence_ids=["market-1"],
    )
    insight = UserInsight(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        evidence_ids=["review-1", "market-1"],
    )

    plan = OperationsDecisionAgent().run(
        OperationsDecisionAgentInput(
            product=product,
            product_market_analysis=market,
            user_insight=insight,
        )
    )
    content = OperationContentSkill.from_default().extract(plan.next_steps)
    audit = EvidenceAuditAgent().run(EvidenceAuditAgentInput(product=product, operation_plan=plan))

    assert plan.status is AgentStatus.SUCCEEDED
    assert plan.evidence_ids == ["market-1", "review-1"]
    assert "college students" in plan.positioning
    assert "United States" in plan.positioning
    assert content is not None
    assert len(content.bullets) == 5
    assert set(content.customer_service) == {"compatibility", "issue", "returns", "shipping"}
    assert audit.status is AuditStatus.PASS


def test_audit_rejects_orphan_evidence_unverified_numbers_and_forbidden_claims(
    demo_product: ProductProfile,
) -> None:
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        evidence_ids=["market-1"],
        positioning="Guaranteed 42% sales growth.",
        conclusions=[
            Conclusion(
                conclusion="Sales will grow 42%.",
                conclusion_type="evidence_grounded",
                confidence=0.9,
                evidence_ids=["missing-1"],
            )
        ],
    )

    audit = EvidenceAuditAgent().run(
        EvidenceAuditAgentInput(product=demo_product, operation_plan=plan)
    )

    assert audit.status is AuditStatus.REJECTED
    assert audit.manual_review_required is True
    assert "missing-1" in audit.conflicting_evidence_ids
    assert any("bind available evidence" in issue for issue in audit.issues)
    assert any("42%" in issue for issue in audit.issues)
    assert any("Guaranteed" in issue or "guaranteed" in issue for issue in audit.issues)


def test_audit_detects_semantic_positioning_conflict(demo_product: ProductProfile) -> None:
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        evidence_ids=["price-1", "position-1"],
        conclusions=[
            Conclusion(
                conclusion="Use a low-price budget position.",
                conclusion_type="evidence_grounded",
                confidence=0.8,
                evidence_ids=["price-1"],
            ),
            Conclusion(
                conclusion="Use a premium high-end position.",
                conclusion_type="evidence_grounded",
                confidence=0.8,
                evidence_ids=["position-1"],
            ),
        ],
    )

    audit = EvidenceAuditAgent().run(
        EvidenceAuditAgentInput(product=demo_product, operation_plan=plan)
    )

    assert audit.status is AuditStatus.REJECTED
    assert audit.conflicting_evidence_ids == ["price-1", "position-1"]
    assert any("semantic_conflict" in issue for issue in audit.issues)


def test_audit_rejects_mismatched_parallel_peer_scopes_and_peer_review_misattribution(
    demo_product: ProductProfile,
) -> None:
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        positioning="当前商品反馈显示需要改善清洗。",
        peer_group_id="group-a",
        selected_parent_asins=["PEER-A"],
        analysis_scopes={
            "product_market_agent": {
                "peer_group_id": "group-a",
                "selected_parent_asins": ["PEER-A"],
            },
            "user_insight_agent": {
                "peer_group_id": "group-b",
                "selected_parent_asins": ["PEER-B"],
            },
        },
        conclusions=[
            Conclusion(
                conclusion="水泵结构可能带来噪音。",
                conclusion_type="reasoned_hypothesis",
                confidence=0.4,
            )
        ],
    )

    audit = EvidenceAuditAgent().run(
        EvidenceAuditAgentInput(product=demo_product, operation_plan=plan)
    )

    assert audit.status is AuditStatus.REJECTED
    assert any("agent_peer_group_mismatch" in issue for issue in audit.issues)
    assert any("agent_product_scope_mismatch" in issue for issue in audit.issues)
    assert any("peer_review_misattribution" in issue for issue in audit.issues)
    assert any("unlabeled_hypothesis" in issue for issue in audit.issues)


def test_audit_accepts_two_decimal_rounding_of_structured_statistics(
    demo_product: ProductProfile,
) -> None:
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        positioning="Use the validated peer average of 30.76 for price comparison.",
        conclusions=[
            Conclusion(
                conclusion="The rounded peer average is 30.76.",
                conclusion_type="market_fact",
                confidence=0.9,
                evidence_ids=["sql-statistics"],
            )
        ],
        evidence_ids=["sql-statistics"],
    )
    statistics = StatisticsResult(
        product_id=demo_product.product_id,
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        metrics={"avg_price": Decimal("30.7555")},
        evidence_ids=["sql-statistics"],
    )

    audit = EvidenceAuditAgent().run(
        EvidenceAuditAgentInput(
            product=demo_product,
            operation_plan=plan,
            statistics=statistics,
        )
    )

    assert not any("30.76" in issue for issue in audit.issues)
