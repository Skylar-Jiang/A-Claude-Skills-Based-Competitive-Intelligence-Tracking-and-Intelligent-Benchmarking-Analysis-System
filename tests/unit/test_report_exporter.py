import json
from pathlib import Path

from app.agents.contracts import EvidenceAuditAgentInput, OperationsDecisionAgentInput
from app.agents.evidence_audit import EvidenceAuditAgent
from app.agents.operations_decision import OperationsDecisionAgent
from app.core.enums import AgentStatus, AuditStatus, DataMode, DataOrigin, ImplementationStatus, KnowledgeType
from app.schemas.analysis import AuditResult, OperationPlan, ProductMarketAnalysis, UserInsight
from app.schemas.common import Conclusion
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductCreate, ProductProfile
from app.schemas.report import DEMO_DISCLAIMER
from app.services.report_exporter import ReportExporter
from app.workflows.state import TradePilotState


def completed_state() -> TradePilotState:
    product = ProductProfile(
        product_id="product-1",
        data_origin=DataOrigin.DEMO,
        **ProductCreate(
            name="DEMO Portable Organizer",
            category="demo",
            features=["compact storage"],
            use_scenarios=["dorm rooms"],
            target_market="United States",
            target_audience=["college students"],
            data_mode=DataMode.DEMO,
        ).model_dump(),
    )
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
    plan = OperationsDecisionAgent().run(
        OperationsDecisionAgentInput(
            product=product,
            product_market_analysis=market,
            user_insight=insight,
        )
    )
    audit = EvidenceAuditAgent().run(
        EvidenceAuditAgentInput(product=product, operation_plan=plan)
    )
    return TradePilotState(
        task_id="task-1",
        run_id="run-1",
        session_id="session-1",
        thread_id="thread-1",
        data_mode=DataMode.DEMO,
        product_profile=product,
        target_market=product.target_market,
        product_market_analysis=market,
        user_insight=insight,
        operation_plan=plan,
        audit_result=audit,
        rag_evidence=[
            EvidenceReference(
                evidence_id="market-1",
                evidence_type="rag_excerpt",
                knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
                source_name="Demo product source",
                excerpt="Demo product evidence.",
                data_origin=DataOrigin.DEMO,
                is_demo=True,
            ),
            EvidenceReference(
                evidence_id="review-1",
                evidence_type="rag_excerpt",
                knowledge_type=KnowledgeType.REVIEW_INSIGHT,
                source_name="Demo review source",
                excerpt="Demo review evidence.",
                data_origin=DataOrigin.DEMO,
                is_demo=True,
            ),
        ],
        report_version=2,
    )


def test_exporter_writes_versioned_structured_json_and_markdown(tmp_path: Path) -> None:
    report = ReportExporter(tmp_path).export(completed_state())

    json_path = Path(report.json_path)
    markdown_path = Path(report.markdown_path)
    assert json_path.exists()
    assert markdown_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["data_origin"] == "demo"
    assert payload["implementation_status"] == "scaffold"
    assert payload["disclaimer"] == DEMO_DISCLAIMER
    assert payload["version"] == 3
    assert payload["sections"]["content_playbook"]["title"]
    assert len(payload["sections"]["content_playbook"]["bullets"]) == 5
    assert payload["sections"]["executive_summary"]["evidence_count"] == 2
    assert {item["evidence_id"] for item in payload["sections"]["evidence_index"]} == {
        "market-1",
        "review-1",
    }
    assert "DEMO" in markdown
    assert "Scaffold" in markdown
    assert "Content playbook" in markdown
    assert "market-1" in markdown
    assert DEMO_DISCLAIMER in markdown


def test_real_report_uses_unlisted_product_peer_group_sections_without_scaffold_text(tmp_path: Path) -> None:
    state = completed_state()
    state = state.model_copy(
        update={
            "data_mode": DataMode.REAL,
            "product_profile": state.product_profile.model_copy(
                update={"data_origin": DataOrigin.USER, "data_mode": DataMode.REAL, "name": "New Cat Fountain"}
            ),
            "peer_group_id": "peer-group-1",
            "selected_parent_asins": ["PEER-1"],
            "product_market_analysis": ProductMarketAnalysis(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
                product_summary="待上市新商品与同类市场商品比较。",
                price_analysis="同类市场价格来自 SQL。",
                feature_baseline=["循环供水"],
                prelaunch_validations=["验证运行噪音"],
                reasoned_hypotheses=["待验证假设：水泵结构可能带来噪音。"],
                evidence_ids=["market-1"],
            ),
            "user_insight": UserInsight(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
                insight_summary="同类商品评论样本关注清洗。",
                common_needs=["便于清洗"],
                prelaunch_validations=["验证拆洗路径"],
                sample_limitations=["样本仅来自最终同类商品组"],
                evidence_ids=["review-1"],
            ),
            "operation_plan": OperationPlan(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
                positioning="完成验证后突出易清洗结构。",
                evidence_ids=["market-1", "review-1"],
                conclusions=[
                    Conclusion(
                        conclusion="同类商品评论样本关注清洗。",
                        conclusion_type="user_insight",
                        confidence=0.7,
                        evidence_ids=["review-1"],
                    ),
                    Conclusion(
                        conclusion="待验证假设：水泵结构可能带来噪音。",
                        conclusion_type="reasoned_hypothesis",
                        confidence=0.4,
                    ),
                ],
            ),
            "audit_result": AuditResult(
                status=AuditStatus.PASS,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
            ),
        }
    )

    report = ReportExporter(tmp_path).export(state)
    markdown = Path(report.markdown_path).read_text(encoding="utf-8")

    assert report.is_demo is False
    assert report.implementation_status is ImplementationStatus.PRODUCTION
    for heading in (
        "## 新商品概况",
        "## 同类市场商品分析",
        "## 同类市场用户洞察",
        "## 商品特征与同类用户关注点的对应分析",
        "## 新商品上市前注意事项",
        "## 数据支持的结论",
        "## 基于商品属性的待验证假设",
        "## 数据限制与证据索引",
    ):
        assert heading in markdown
    assert "DEMO" not in markdown
    assert "Scaffold" not in markdown
    assert "当前商品反馈" not in markdown
