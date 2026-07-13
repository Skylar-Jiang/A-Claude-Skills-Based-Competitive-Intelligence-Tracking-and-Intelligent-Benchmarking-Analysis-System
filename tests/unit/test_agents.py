from langchain_core.runnables import RunnableSequence

from app.agents.contracts import (
    EvidenceAuditAgentInput,
    OperationsDecisionAgentInput,
    ProductMarketAgentInput,
    UserInsightAgentInput,
)
from app.agents.evidence_audit import EvidenceAuditAgent
from app.agents.operations_decision import OperationsDecisionAgent
from app.agents.product_market import ProductMarketAgent
from app.agents.user_insight import UserInsightAgent
from app.core.enums import AgentStatus, AuditStatus, DataMode, DataOrigin
from app.schemas.analysis import AuditResult, OperationPlan, ProductMarketAnalysis, UserInsight
from app.schemas.product import ProductCreate, ProductProfile


def demo_product() -> ProductProfile:
    return ProductProfile(
        product_id="product-1",
        data_origin=DataOrigin.DEMO,
        **ProductCreate(
            name="DEMO Portable Organizer",
            category="demo-generic",
            data_mode=DataMode.DEMO,
        ).model_dump(),
    )


def test_each_agent_exposes_a_real_lcel_sequence_and_typed_demo_output() -> None:
    product_agent = ProductMarketAgent()
    insight_agent = UserInsightAgent()
    operations_agent = OperationsDecisionAgent()
    audit_agent = EvidenceAuditAgent()

    assert all(
        isinstance(agent.chain, RunnableSequence)
        for agent in (product_agent, insight_agent, operations_agent, audit_agent)
    )

    market = product_agent.run(ProductMarketAgentInput(product=demo_product(), evidence=[]))
    insight = insight_agent.run(UserInsightAgentInput(product=demo_product(), evidence=[]))
    plan = operations_agent.run(
        OperationsDecisionAgentInput(
            product=demo_product(), product_market_analysis=market, user_insight=insight
        )
    )
    audit = audit_agent.run(EvidenceAuditAgentInput(product=demo_product(), operation_plan=plan))

    assert isinstance(market, ProductMarketAnalysis)
    assert isinstance(insight, UserInsight)
    assert isinstance(plan, OperationPlan)
    assert isinstance(audit, AuditResult)
    assert market.status is AgentStatus.INSUFFICIENT_EVIDENCE
    assert insight.status is AgentStatus.INSUFFICIENT_EVIDENCE
    assert audit.status is AuditStatus.PASS
    for output in (market, insight, plan, audit):
        assert output.data_origin is DataOrigin.DEMO
        assert output.implementation_status.value == "scaffold"


def test_agent_inputs_are_validated_by_pydantic() -> None:
    agent = ProductMarketAgent()

    output = agent.chain.invoke({"product": demo_product().model_dump(), "evidence": []})

    assert isinstance(output, ProductMarketAnalysis)
    assert output.data_gaps[0].code == "no_rag_evidence"
