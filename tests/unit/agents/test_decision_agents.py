from datetime import date
from decimal import Decimal

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableSequence

from app.agents.contracts import EvidenceAuditAgentInput, OperationsDecisionAgentInput
from app.agents.evidence_audit import EvidenceAuditAgent
from app.agents.operations_decision import OperationsDecisionAgent
from app.background.contracts import BackgroundEvidence, BackgroundQuery, BackgroundResult
from app.core.enums import AgentStatus, AuditStatus, DataOrigin, KnowledgeType
from app.schemas.analysis import AuditResult, OperationPlan, ProductMarketAnalysis, UserInsight
from app.schemas.common import Conclusion, DataGap
from app.schemas.evidence import EvidenceReference
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


def test_decision_agent_adds_tariff_inputs_to_plan_without_changing_status_basis(
    demo_product: ProductProfile,
) -> None:
    market = ProductMarketAnalysis(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        evidence_ids=["market-1"],
    )
    insight = UserInsight(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        evidence_ids=["review-1"],
    )
    background = BackgroundResult(
        provider="us-tariff-provider",
        query=BackgroundQuery(
            product_name=demo_product.name,
            product_type=demo_product.category,
            market="United States",
            jurisdiction="US",
            context_types=["tariff_rate"],
            effective_date=date(2026, 7, 1),
            query_date=date(2026, 7, 15),
        ),
        evidence=[
            BackgroundEvidence(
                evidence_id="us-hts-8421210000-2026-01-01",
                context_type="tariff_rate",
                content="General duty rate: Free. Additional duty text: 25%.",
                source_name="USITC Harmonized Tariff Schedule",
                source_uri="https://hts.usitc.gov/export",
                effective_date=date(2026, 1, 1),
                jurisdiction="US",
                confidence=0.74,
            )
        ],
        decision_inputs={
            "agent_decision_brief": "美国税费输入显示该候选税号存在附加税，需回算 landed cost 与毛利。",
            "tariff_recommended_actions": [
                "把附加税情景加入 landed cost 与毛利测算，重新校验定价缓冲。",
                "在打样或首单前完成 customs broker / 报关行 HTS 归类复核。",
            ],
        },
    )

    plan = OperationsDecisionAgent().run(
        OperationsDecisionAgentInput(
            product=demo_product,
            product_market_analysis=market,
            user_insight=insight,
            background_context=background,
        )
    )

    assert plan.status is AgentStatus.SUCCEEDED
    assert "us-hts-8421210000-2026-01-01" in plan.evidence_ids
    assert any("Tariff decision input:" in item.conclusion for item in plan.conclusions)
    assert any("landed cost" in step for step in plan.next_steps)


def test_audit_allows_hts_code_from_background_context_without_numeric_false_positive(
    demo_product: ProductProfile,
) -> None:
    background = BackgroundResult(
        provider="us-tariff-provider",
        query=BackgroundQuery(
            product_name=demo_product.name,
            product_type=demo_product.category,
            market="United States",
            jurisdiction="US",
            context_types=["tariff_rate"],
            effective_date=date(2026, 7, 1),
            query_date=date(2026, 7, 15),
        ),
        evidence=[
            BackgroundEvidence(
                evidence_id="us-hts-8421210000-2026-01-01",
                context_type="tariff_rate",
                content="Configured Phase 1 HS mapping matched 'Fountains' to candidate HTS 8421210000.",
                source_name="USITC Harmonized Tariff Schedule",
                source_uri="https://hts.usitc.gov/export",
                effective_date=date(2026, 1, 1),
                jurisdiction="US",
                confidence=0.74,
            )
        ],
        decision_inputs={
            "agent_decision_brief": "美国税费输入显示 Fountains 当前候选 HTS 为 8421210000，一般税率为 Free。",
        },
    )
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        evidence_ids=["market-1", "us-hts-8421210000-2026-01-01"],
        conclusions=[
            Conclusion(
                conclusion=(
                    "Tariff decision input: 美国税费输入显示 Fountains 当前候选 HTS 为 "
                    "8421210000，一般税率为 Free。"
                ),
                conclusion_type="recommendation",
                confidence=0.8,
                evidence_ids=["us-hts-8421210000-2026-01-01"],
            )
        ],
    )
    evidence = [
        EvidenceReference(
            evidence_id="market-1",
            evidence_type="sql_statistics",
            knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
            source_name="peer SQL statistics",
            excerpt="{}",
            data_origin=DataOrigin.DEMO,
            is_demo=True,
            metadata={},
        ),
        EvidenceReference(
            evidence_id="us-hts-8421210000-2026-01-01",
            evidence_type="product_background",
            knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
            source_name="USITC Harmonized Tariff Schedule",
            excerpt="Configured Phase 1 HS mapping matched 'Fountains' to candidate HTS 8421210000.",
            data_origin=DataOrigin.REAL,
            is_demo=False,
            metadata={"source_type": "product_background_provider"},
        ),
    ]

    audit = EvidenceAuditAgent().run(
        EvidenceAuditAgentInput(
            product=demo_product,
            operation_plan=plan,
            evidence=evidence,
            background_context=background,
        )
    )

    assert not any("8421210000" in issue for issue in audit.issues)


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


def test_audit_allows_one_claim_to_contrast_premium_positioning_with_low_price_competition(
    demo_product: ProductProfile,
) -> None:
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        positioning="面向中高端品质市场。",
        conclusions=[
            Conclusion(
                conclusion="依靠差异化支撑中高端溢价，避免与低价产品直接竞争。",
                conclusion_type="recommendation",
                confidence=0.8,
                evidence_ids=["market-1"],
            )
        ],
        evidence_ids=["market-1"],
    )

    audit = EvidenceAuditAgent().run(
        EvidenceAuditAgentInput(product=demo_product, operation_plan=plan)
    )

    assert not any("semantic_conflict" in issue for issue in audit.issues)


def test_model_missing_evidence_advisory_is_refuted_for_valid_non_uuid_id() -> None:
    assert EvidenceAuditAgent._refuted_model_finding(
        "证据 ID 'us-hts-8421210000-2026-01-01' 在 Evidence 数组中不存在。",
        {"us-hts-8421210000-2026-01-01"},
        {"us-hts-8421210000-2026-01-01"},
        valid_evidence_less_hypotheses=False,
    )


def test_audit_rejects_mismatched_parallel_peer_scopes_and_peer_review_misattribution(
    demo_product: ProductProfile,
) -> None:
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        positioning="当前商品反馈显示需要改进清洗。",
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


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("marketing_objective", "当前商品反馈显示应强化易清洗卖点。"),
        ("target_segments", ["当前商品反馈显示适合忙碌养宠家庭。"]),
        ("value_propositions", ["当前商品反馈显示清洗更轻松。"]),
        ("pricing_strategy", ["当前商品反馈显示可采用溢价策略。"]),
        ("channel_strategy", ["当前商品反馈显示应优先投放短视频。"]),
        ("messaging_strategy", ["当前商品反馈显示应强调低噪音。"]),
        ("launch_actions", ["当前商品反馈显示应立即上市。"]),
    ],
)
def test_audit_checks_peer_review_misattribution_in_every_marketing_strategy_field(
    demo_product: ProductProfile,
    field_name: str,
    field_value: str | list[str],
) -> None:
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        **{field_name: field_value},
    )

    audit = EvidenceAuditAgent().run(
        EvidenceAuditAgentInput(product=demo_product, operation_plan=plan)
    )

    assert audit.status is AuditStatus.REJECTED
    assert any("peer_review_misattribution" in issue for issue in audit.issues)


def test_audit_rejects_user_fact_disguised_as_reasoned_hypothesis(
    demo_product: ProductProfile,
) -> None:
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        conclusions=[
            Conclusion(
                conclusion="待验证假设（非用户评论结论）：用户高度关注泵噪音。",
                conclusion_type="reasoned_hypothesis",
                confidence=0.4,
                data_gaps=[
                    DataGap(
                        code="insufficient_evidence",
                        field="peer_review_sample",
                        reason="缺少支持该用户结论的评论证据。",
                    )
                ],
            )
        ],
    )

    audit = EvidenceAuditAgent().run(
        EvidenceAuditAgentInput(product=demo_product, operation_plan=plan)
    )

    assert audit.status is AuditStatus.REJECTED
    assert any("hypothesis_contains_user_fact" in issue for issue in audit.issues)


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


def test_numeric_guard_preserves_valid_decimal_before_chinese_unit() -> None:
    value = OperationsDecisionAgent._sanitize_numeric_text(
        "目标售价299.99美元，市场均价453.37美元。",
        {"299.99", "453.37"},
    )

    assert value == "目标售价299.99美元，市场均价453.37美元。"
    assert OperationsDecisionAgent._sanitize_numeric_text("噪音低于18dB。", set()) == "噪音低于待验证数值dB。"


def test_audit_accepts_capacity_number_from_product_text(demo_product: ProductProfile) -> None:
    product = demo_product.model_copy(update={"name": "3L Cordless Pet Fountain"})
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=product.data_origin,
        positioning="突出3L储水容量。",
    )

    audit = EvidenceAuditAgent().run(
        EvidenceAuditAgentInput(product=product, operation_plan=plan)
    )

    assert not any("unverified_numeric_claim" in issue for issue in audit.issues)


def test_operations_agent_retries_when_positioning_has_wrong_schema(
    demo_product: ProductProfile,
) -> None:
    product = demo_product.model_copy(update={"data_origin": DataOrigin.REAL})
    market = ProductMarketAnalysis(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.REAL,
        evidence_ids=["market-1"],
    )
    insight = UserInsight(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.REAL,
        evidence_ids=["review-1"],
    )
    model = FakeListChatModel(
        responses=[
            '{"positioning":{"summary":"错误结构"},"evidence_ids":["market-1"],'
            '"conclusions":[],"data_gaps":[],"next_steps":[]}',
            '{"positioning":"面向目标用户的证据约束上市定位","evidence_ids":["market-1"],'
            '"conclusions":[],"data_gaps":[],"next_steps":[]}',
        ]
    )

    plan = OperationsDecisionAgent(model=model).run(
        OperationsDecisionAgentInput(
            product=product,
            product_market_analysis=market,
            user_insight=insight,
        )
    )

    assert plan.positioning == "面向目标用户的证据约束上市定位"
    assert plan.model_call_count == 2
    assert plan.parse_retry_count == 1


def test_operations_agent_retries_when_strategy_list_contains_objects(
    demo_product: ProductProfile,
) -> None:
    product = demo_product.model_copy(update={"data_origin": DataOrigin.REAL})
    market = ProductMarketAnalysis(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.REAL,
        evidence_ids=["market-1"],
    )
    insight = UserInsight(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.REAL,
        evidence_ids=["review-1"],
    )
    model = FakeListChatModel(
        responses=[
            '{"positioning":"证据约束定位","target_segments":[{"segment_name":"养宠家庭"}],'
            '"evidence_ids":["market-1"],"conclusions":[],"data_gaps":[],"next_steps":[]}',
            '{"positioning":"证据约束定位","target_segments":["养宠家庭"],'
            '"evidence_ids":["market-1"],"conclusions":[],"data_gaps":[],"next_steps":[]}',
        ]
    )

    plan = OperationsDecisionAgent(model=model).run(
        OperationsDecisionAgentInput(
            product=product,
            product_market_analysis=market,
            user_insight=insight,
        )
    )

    assert plan.target_segments == ["养宠家庭"]
    assert plan.model_call_count == 2
    assert plan.parse_retry_count == 1


def test_operations_agent_flattens_strategy_objects_only_after_bounded_retry(
    demo_product: ProductProfile,
) -> None:
    product = demo_product.model_copy(update={"data_origin": DataOrigin.REAL})
    response = (
        '{"positioning":"证据约束定位",'
        '"target_segments":{"primary":[{"segment_name":"养宠家庭",'
        '"description":"重视清洗便利性","priority":"High",'
        '"evidence_ids":["market-1"]}],"secondary":null},'
        '"evidence_ids":["market-1"],"conclusions":[],"data_gaps":[],"next_steps":[]}'
    )
    model = FakeListChatModel(responses=[response, response])

    plan = OperationsDecisionAgent(model=model).run(
        OperationsDecisionAgentInput(
            product=product,
            product_market_analysis=ProductMarketAnalysis(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.REAL,
                evidence_ids=["market-1"],
            ),
            user_insight=UserInsight(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.REAL,
                evidence_ids=["review-1"],
            ),
        )
    )

    assert plan.target_segments == ["养宠家庭：重视清洗便利性"]
    assert plan.model_call_count == 2
    assert plan.parse_retry_count == 1
    assert "market-1" not in plan.target_segments[0]
    assert "priority" not in plan.target_segments[0]


def test_operations_numeric_guard_preserves_product_capacity(
    demo_product: ProductProfile,
) -> None:
    product = demo_product.model_copy(
        update={"name": "3L Cordless Pet Fountain", "data_origin": DataOrigin.REAL}
    )
    context = OperationsDecisionAgentInput(
        product=product,
        product_market_analysis=ProductMarketAnalysis(
            status=AgentStatus.SUCCEEDED,
            data_origin=DataOrigin.REAL,
            evidence_ids=["market-1"],
        ),
        user_insight=UserInsight(
            status=AgentStatus.SUCCEEDED,
            data_origin=DataOrigin.REAL,
            evidence_ids=["review-1"],
        ),
    )

    allowed = OperationsDecisionAgent._allowed_numbers(context)

    assert "3" in allowed
    assert OperationsDecisionAgent._sanitize_numeric_text("突出3L容量。", allowed) == "突出3L容量。"


def test_operations_agent_drops_unsupported_quantified_marketing_targets(
    demo_product: ProductProfile,
) -> None:
    product = demo_product.model_copy(update={"data_origin": DataOrigin.REAL})
    model = FakeListChatModel(
        responses=[
            '{"positioning":"围绕易清洁体验建立差异化定位。",'
            '"marketing_objective":"上市首月获取50条评价并维持4.8分。",'
            '"launch_actions":["获取50条首发评价","完成清洗便利性测试"],'
            '"evidence_ids":["market-1"],"conclusions":[],"data_gaps":[],"next_steps":[]}'
        ]
    )

    plan = OperationsDecisionAgent(model=model).run(
        OperationsDecisionAgentInput(
            product=product,
            product_market_analysis=ProductMarketAnalysis(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.REAL,
                evidence_ids=["market-1"],
            ),
            user_insight=UserInsight(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.REAL,
                evidence_ids=["review-1"],
            ),
        )
    )

    assert plan.marketing_objective == (
        "围绕已验证的目标客群与价值主张建立首发认知；具体量化目标需由用户确认。"
    )
    assert plan.launch_actions == ["完成清洗便利性测试"]
    assert "待验证数值" not in plan.model_dump_json()


def test_operations_agent_preserves_structured_launch_marketing_strategy(
    demo_product: ProductProfile,
) -> None:
    product = demo_product.model_copy(update={"data_origin": DataOrigin.REAL})
    market = ProductMarketAnalysis(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.REAL,
        evidence_ids=["market-1"],
    )
    insight = UserInsight(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.REAL,
        evidence_ids=["review-1"],
    )
    model = FakeListChatModel(
        responses=[
            '{"positioning":"面向重视易清洁的养宠家庭，突出可拆洗差异化。",'
            '"marketing_objective":"以可验证的易清洁体验建立首发认知。",'
            '"target_segments":["重视日常维护效率的养宠家庭"],'
            '"value_propositions":["把可拆洗结构转化为降低维护负担的核心价值"],'
            '"pricing_strategy":["以同类价格带和目标成本共同校验首发价"],'
            '"channel_strategy":["优先在可展示清洗过程的内容渠道验证转化"],'
            '"messaging_strategy":["用清洗步骤演示支持易维护卖点"],'
            '"launch_actions":["完成清洗便利性测试后再发布对应卖点"],'
            '"evidence_ids":["market-1","review-1"],"conclusions":[],'
            '"data_gaps":[],"next_steps":[]}'
        ]
    )

    plan = OperationsDecisionAgent(model=model).run(
        OperationsDecisionAgentInput(
            product=product,
            product_market_analysis=market,
            user_insight=insight,
        )
    )

    assert plan.marketing_objective.startswith("以可验证的易清洁体验")
    assert plan.target_segments == ["重视日常维护效率的养宠家庭"]
    assert plan.value_propositions
    assert plan.pricing_strategy
    assert plan.channel_strategy
    assert plan.messaging_strategy
    assert plan.launch_actions


def test_operations_agent_preserves_tariff_numbers_from_background_context(
    demo_product: ProductProfile,
) -> None:
    product = demo_product.model_copy(update={"data_origin": DataOrigin.REAL})
    market = ProductMarketAnalysis(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.REAL,
        evidence_ids=["market-1"],
    )
    insight = UserInsight(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.REAL,
        evidence_ids=["review-1"],
    )
    background = BackgroundResult(
        provider="us-tariff-provider",
        query=BackgroundQuery(
            product_name=product.name,
            product_type=product.category,
            market="United States",
            jurisdiction="US",
            context_types=["tariff_rate"],
            effective_date=date(2026, 7, 1),
            query_date=date(2026, 7, 15),
        ),
        evidence=[
            BackgroundEvidence(
                evidence_id="us-hts-8421210000-2026-01-01",
                context_type="tariff_rate",
                content="Configured Phase 1 HS mapping matched 'Fountains' to candidate HTS 8421210000.",
                source_name="USITC Harmonized Tariff Schedule",
                source_uri="https://hts.usitc.gov/export",
                effective_date=date(2026, 1, 1),
                jurisdiction="US",
                confidence=0.74,
            )
        ],
        decision_inputs={
            "tariff_summary": "Fountains 当前候选 HTS 为 8421210000；一般税率为 Free；置信度 0.74。",
            "primary_tariff_profile": {
                "hs_code": "8421210000",
                "general_rate": "Free",
                "confidence": 0.74,
            },
        },
    )
    model = FakeListChatModel(
        responses=[
            '{"positioning":"围绕 HTS 8421210000 的低基础关税路径规划上市。",'
            '"evidence_ids":["market-1","us-hts-8421210000-2026-01-01"],'
            '"conclusions":[{"conclusion":"候选 HTS 8421210000 当前一般税率为 Free，置信度 0.74。",'
            '"conclusion_type":"recommendation","confidence":0.8,'
            '"evidence_ids":["us-hts-8421210000-2026-01-01"],"data_gaps":[]}],'
            '"data_gaps":[],"next_steps":[]}'
        ]
    )

    plan = OperationsDecisionAgent(model=model).run(
        OperationsDecisionAgentInput(
            product=product,
            product_market_analysis=market,
            user_insight=insight,
            background_context=background,
        )
    )

    assert "8421210000" in plan.positioning
    assert "待验证数值" not in plan.positioning
    assert any("8421210000" in item.conclusion for item in plan.conclusions)
    assert any("0.74" in item.conclusion for item in plan.conclusions)
