import json
from collections import Counter
from decimal import Decimal

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agents.contracts import EvidenceAuditAgentInput
from app.agents.evidence_audit import AUDIT_SYSTEM_PROMPT, EvidenceAuditAgent
from app.agents.operations_decision import OPERATIONS_SYSTEM_PROMPT, OperationsDecisionAgent
from app.agents.product_market import PRODUCT_MARKET_SYSTEM_PROMPT, ProductMarketAgent
from app.agents.user_insight import USER_INSIGHT_SYSTEM_PROMPT, UserInsightAgent
from app.core.enums import (
    AgentStatus,
    AuditStatus,
    DataMode,
    DataOrigin,
    ImplementationStatus,
    KnowledgeType,
    RetrievalScope,
)
from app.rag.contracts import KnowledgeDocument
from app.rag.in_memory import InMemoryKnowledgeStore
from app.schemas.analysis import OperationPlan
from app.schemas.common import Conclusion
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductCreate, ProductProfile
from app.statistics.contracts import StatisticsResult
from app.workflows.graph import TradePilotWorkflow
from app.workflows.state import TradePilotState


class PeerStatisticsProvider:
    def get_statistics(
        self,
        *,
        product: ProductProfile,
        peer_group_id: str | None = None,
    ) -> StatisticsResult:
        assert peer_group_id == "peer-group-1"
        return StatisticsResult(
            product_id=product.product_id,
            status=AgentStatus.SUCCEEDED,
            data_origin=DataOrigin.REAL,
            metrics={
                "peer_product_count": Decimal("12"),
                "priced_product_count": Decimal("12"),
                "min_price": Decimal("29.99"),
                "max_price": Decimal("49.99"),
                "avg_price": Decimal("39.99"),
                "median_price": Decimal("39.49"),
                "avg_rating": Decimal("4.3"),
                "total_rating_number": Decimal("6000"),
            },
            evidence_ids=["market-evidence"],
        )


def _model(name: str, payload: dict[str, object], calls: Counter[str]) -> RunnableLambda:
    def invoke(_value):  # type: ignore[no-untyped-def]
        calls[name] += 1
        return AIMessage(content=json.dumps(payload, ensure_ascii=False))

    return RunnableLambda(invoke)


def test_real_agent_prompts_require_simplified_chinese_narrative() -> None:
    requirement = "所有自然语言内容必须使用简体中文"

    assert requirement in PRODUCT_MARKET_SYSTEM_PROMPT
    assert requirement in USER_INSIGHT_SYSTEM_PROMPT
    assert requirement in OPERATIONS_SYSTEM_PROMPT
    assert requirement in AUDIT_SYSTEM_PROMPT


def test_audit_discards_model_missing_id_claim_refuted_by_supplied_evidence() -> None:
    calls: Counter[str] = Counter()
    evidence_id = "01b72ea2-cada-50fc-8140-b478a48ef472"
    unused_evidence_id = "9aab456d-f779-5307-bf52-3b2003f33b1f"
    audit_model = _model(
        "audit",
        {
            "status": "warning",
            "issues": [
                f"Evidence ID {evidence_id} is missing from the Evidence array.",
                f"Evidence ID {unused_evidence_id} exists but is not cited by the Plan; this may be data leakage.",
                "Two reasoned_hypothesis conclusions have empty evidence_ids despite explicit data gaps.",
                "The Plan peer_group_id matches the expected value.",
                "The reasoned_hypothesis is correctly labeled and adheres to the prelaunch rule.",
            ],
            "conflicting_evidence_ids": [],
            "unresolved_questions": [
                f"Please provide missing evidence {evidence_id}.",
                "Why are Statistics evidence_ids not included in Evidence when the plan does not cite them?",
                f"Why is unused evidence {unused_evidence_id} present if it is not cited?",
                "Why include reasoned_hypothesis conclusions with zero evidence IDs?",
                "The cited SQL evidence exists in the Evidence array. No conflict.",
            ],
            "manual_review_required": False,
        },
        calls,
    )
    product = ProductProfile(
        product_id="temporary-upload-id",
        data_origin=DataOrigin.USER,
        **ProductCreate(
            name="New Cat Fountain",
            category="Fountains",
            data_mode=DataMode.REAL,
        ).model_dump(),
    )
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.USER,
        implementation_status=ImplementationStatus.PRODUCTION,
        peer_group_id="peer-group-1",
        evidence_ids=[evidence_id],
        conclusions=[
            Conclusion(
                conclusion="同类市场商品结构化统计支持该价格观察。",
                conclusion_type="market_fact",
                confidence=0.8,
                evidence_ids=[evidence_id],
            ),
            Conclusion(
                conclusion="待验证假设：新商品水泵结构需要噪音测试。",
                conclusion_type="reasoned_hypothesis",
                confidence=0.4,
                data_gaps=[
                    {
                        "code": "claim_without_valid_evidence",
                        "field": "reasoned_hypothesis",
                        "reason": "Attribute-led hypothesis, not a market fact.",
                    }
                ],
            ),
        ],
    )
    evidence = EvidenceReference(
        evidence_id=evidence_id,
        evidence_type="sql_statistics",
        knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
        source_name="peer SQL statistics",
        excerpt="{}",
        data_origin=DataOrigin.REAL,
        metadata={"peer_group_id": "peer-group-1", "evidence_scope": "peer_group"},
    )
    unused_evidence = evidence.model_copy(update={"evidence_id": unused_evidence_id})

    audit = EvidenceAuditAgent(model=audit_model).run(  # type: ignore[arg-type]
        EvidenceAuditAgentInput(
            product=product,
            operation_plan=plan,
            evidence=[evidence, unused_evidence],
            peer_group_id="peer-group-1",
        )
    )

    assert calls == Counter({"audit": 1})
    assert not any(
        "model_advisory" in issue or evidence_id in issue or unused_evidence_id in issue
        for issue in audit.issues
    )
    assert audit.unresolved_questions == []


def test_all_four_real_lcel_agents_use_peer_safe_semantics() -> None:
    calls: Counter[str] = Counter()
    market_model = _model(
        "market",
        {
            "status": "complete",
            "product_summary": "新商品与真实同类市场商品比较。",
            "price_analysis": "同类市场价格为 29.99 至 49.99 USD，均价 39.99 USD。",
            "feature_baseline": ["循环供水", "可拆洗水箱"],
            "structure_and_scenarios": ["室内猫饮水场景"],
            "brand_positioning": ["同类品牌集中于便利维护定位"],
            "rating_analysis": "同类商品平均评分 4.3，评价数量合计 6000。",
            "homogenization_risks": ["基础循环供水同质化"],
            "differentiation_opportunities": ["可视水位与低噪验证"],
            "missing_parameters": ["运行噪音"],
            "prelaunch_validations": ["验证水泵噪音与清洗便利性"],
            "reasoned_hypotheses": ["水泵结构可能带来噪音风险"],
            "evidence_ids": ["market-evidence"],
            "conclusions": [
                {
                    "conclusion": "同类商品具有循环供水基线。",
                    "conclusion_type": "market_fact",
                    "confidence": 0.8,
                    "evidence_ids": ["market-evidence"],
                    "data_gaps": [],
                }
            ],
            "data_gaps": [],
        },
        calls,
    )
    insight_model = _model(
        "insight",
        {
            "status": "grounded",
            "insight_summary": "当前商品反馈集中在清洗和噪音。",
            "common_needs": ["便于清洗"],
            "positive_experiences": ["同类商品评论样本提到饮水便利"],
            "pain_points": ["维护步骤较多"],
            "purchase_factors": ["容量和噪音"],
            "feature_usage_maintenance_concerns": ["滤芯更换和水箱清洗"],
            "prelaunch_validations": ["验证拆洗路径"],
            "convertible_selling_points": ["易清洗结构"],
            "optimization_directions": ["减少维护步骤"],
            "sample_limitations": ["仅分析同类商品评论样本"],
            "reasoned_hypotheses": ["储水结构需要防漏测试"],
            "evidence_ids": ["review-evidence"],
            "conclusions": [
                {
                    "conclusion": "同类商品评论样本出现清洗关注。",
                    "conclusion_type": "user_insight",
                    "confidence": 0.7,
                    "evidence_ids": ["review-evidence"],
                    "data_gaps": [],
                }
            ],
            "data_gaps": [],
        },
        calls,
    )
    operations_model = _model(
        "operations",
        {
            "status": "ready_for_launch_with_conditions",
            "positioning": "面向养猫用户，以易清洗结构作为新商品上市前验证后的差异点。",
            "evidence_ids": ["market-evidence", "review-evidence"],
            "conclusions": [
                {
                    "conclusion": "优先验证易清洗结构。",
                    "evidence_ids": ["market-evidence", "review-evidence"],
                    "data_gaps": [],
                }
            ],
            "data_gaps": [],
            "next_steps": ["ACTION: 完成低于 18dB 的噪音测试后再形成上市卖点。"],
        },
        calls,
    )
    audit_model = _model(
        "audit",
        {
            "status": "rejected",
            "issues": [{"description": "Model-only advisory that deterministic checks did not confirm."}],
            "conflicting_evidence_ids": [],
            "unresolved_questions": [],
            "manual_review_required": True,
        },
        calls,
    )
    store = InMemoryKnowledgeStore()
    store.ingest(
        [
            KnowledgeDocument(
                document_id="market-evidence",
                product_id="peer-1",
                knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
                content="Peer fountain with removable reservoir.",
                source_name="real peer metadata",
                data_origin=DataOrigin.REAL,
                metadata={"peer_group_id": "peer-group-1", "evidence_scope": "peer_product"},
            ),
            KnowledgeDocument(
                document_id="review-evidence",
                product_id="peer-1",
                knowledge_type=KnowledgeType.REVIEW_INSIGHT,
                content="Cleaning and noise matter for this listed peer product.",
                source_name="real peer review",
                data_origin=DataOrigin.REAL,
                metadata={"peer_group_id": "peer-group-1", "evidence_scope": "peer_product"},
            ),
        ]
    )
    product = ProductProfile(
        product_id="new-product",
        data_origin=DataOrigin.USER,
        **ProductCreate(
            name="New Cat Fountain",
            category="Fountains",
            features=["visible water level"],
            target_audience=["cat owners"],
            data_mode=DataMode.REAL,
        ).model_dump(),
    )
    workflow = TradePilotWorkflow(
        knowledge_store=store,
        statistics_provider=PeerStatisticsProvider(),
        product_market_agent=ProductMarketAgent(model=market_model),  # type: ignore[arg-type]
        user_insight_agent=UserInsightAgent(model=insight_model),  # type: ignore[arg-type]
        operations_decision_agent=OperationsDecisionAgent(model=operations_model),  # type: ignore[arg-type]
        evidence_audit_agent=EvidenceAuditAgent(model=audit_model),  # type: ignore[arg-type]
    )
    initial = TradePilotState(
        task_id="task",
        run_id="run",
        session_id="session",
        thread_id="thread",
        data_mode=DataMode.REAL,
        product_profile=product,
        retrieval_scope=RetrievalScope.PEER_GROUP,
        peer_group_id="peer-group-1",
    )

    result = TradePilotState.model_validate(workflow.invoke(initial))

    assert calls == Counter({"market": 1, "insight": 1, "operations": 1, "audit": 1})
    assert result.product_market_analysis is not None
    assert result.product_market_analysis.price_analysis
    assert len(result.product_market_analysis.feature_baseline) >= 2
    assert result.product_market_analysis.structure_and_scenarios
    assert result.product_market_analysis.reasoned_hypotheses[0].startswith("待验证假设")
    assert result.user_insight is not None
    assert "当前商品反馈" not in result.user_insight.model_dump_json()
    assert result.user_insight.reasoned_hypotheses[0].startswith("待验证假设")
    assert result.operation_plan is not None
    assert result.operation_plan.implementation_status.value == "production"
    assert result.operation_plan.conclusions[0].conclusion_type == "recommendation"
    assert result.operation_plan.conclusions[0].confidence > 0
    assert "18dB" not in result.operation_plan.model_dump_json()
    assert "待验证数值" in result.operation_plan.model_dump_json()
    assert result.audit_result is not None
    assert result.audit_result.status is AuditStatus.WARNING
    assert result.audit_result.manual_review_required is False
    assert result.audit_result.implementation_status.value == "production"
