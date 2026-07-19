import json
from pathlib import Path

from app.agents.contracts import EvidenceAuditAgentInput, OperationsDecisionAgentInput
from app.agents.evidence_audit import EvidenceAuditAgent
from app.agents.operations_decision import OperationsDecisionAgent
from app.core.enums import AgentStatus, AuditStatus, DataMode, DataOrigin, ImplementationStatus, KnowledgeType
from app.schemas.analysis import AuditResult, OperationPlan, ProductMarketAnalysis, UserInsight
from app.schemas.common import Conclusion, DataGap
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
    assert payload["section_index"]["executive_summary"]["section_id"] == "executive-summary"
    assert '<a id="executive-summary"></a>' in markdown


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
            "data_gaps": [
                DataGap(
                    code="model_reported_data_gap",
                    field="product_specifications",
                    reason="Waste drawer capacity is unspecified.",
                    required_for="market analysis",
                )
            ],
            "product_market_analysis": ProductMarketAnalysis(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
                product_summary="待上市新商品与同类市场商品比较。",
                product_category="宠物饮水机",
                product_functions=["紧凑收纳"],
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
                marketing_objective="用可验证的易清洗体验建立首发认知。",
                target_segments=["重视维护效率的养宠家庭"],
                value_propositions=["降低日常拆洗负担"],
                pricing_strategy=["结合同类价格带校验首发价格"],
                channel_strategy=["优先使用可演示清洗过程的内容渠道"],
                messaging_strategy=["用真实清洗步骤支持易维护卖点"],
                launch_actions=["完成清洗便利性测试后再发布卖点"],
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
        "## 新商品上市营销策略",
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
    assert "- 商品类别：宠物饮水机" in markdown
    assert "compact storage" not in markdown
    assert "紧凑收纳 ↔ 便于清洗" in markdown
    assert "用可验证的易清洗体验建立首发认知" in markdown
    assert "重视维护效率的养宠家庭" in markdown
    assert "结合同类价格带校验首发价格" in markdown
    assert "product_specifications" not in markdown
    assert "Waste drawer capacity is unspecified." not in markdown
    assert "商品参数：缺少形成可靠结论所需的数据或证据。" in markdown
    assert report.section_index["new_product_overview"].section_id == "new-product-overview"
    assert '<a id="new-product-overview"></a>' in markdown
    assert '<a id="peer-market-product-analysis"></a>' in markdown


def test_customer_text_escapes_untrusted_markdown_html_and_newlines(tmp_path: Path) -> None:
    rendered = ReportExporter._customer_text(
        "<script>alert('x')</script>\n[点击](javascript:alert(1)) **伪标题**"
    )

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert r"\[点击\]" in rendered
    assert r"\*\*伪标题\*\*" in rendered
    assert "\n" not in rendered

    base = completed_state()
    state = base.model_copy(
        update={
            "data_mode": DataMode.REAL,
            "product_profile": base.product_profile.model_copy(
                update={
                    "data_origin": DataOrigin.USER,
                    "data_mode": DataMode.REAL,
                    "name": "<img src=x onerror=alert(1)>\n## 伪标题",
                }
            ),
            "audit_result": AuditResult(
                status=AuditStatus.PASS,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
            ),
        }
    )
    markdown = Path(ReportExporter(tmp_path).export(state).markdown_path).read_text(encoding="utf-8")

    assert "<img src=x" not in markdown
    assert "&lt;img src=x" in markdown
    assert "\n## 伪标题" not in markdown


def test_real_report_uses_friendly_evidence_labels_and_keeps_machine_mapping(tmp_path: Path) -> None:
    state = completed_state().model_copy(
        update={
            "data_mode": DataMode.REAL,
            "product_profile": completed_state().product_profile.model_copy(
                update={"data_origin": DataOrigin.USER, "data_mode": DataMode.REAL}
            ),
            "audit_result": AuditResult(
                status=AuditStatus.PASS,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
            ),
            "rag_evidence": [
                EvidenceReference(
                    evidence_id="machine-product-uuid",
                    evidence_type="rag_excerpt",
                    knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
                    source_name="Nature's Miracle 自动猫砂盆",
                    excerpt="该同类商品采用自动清洁耙结构。",
                    data_origin=DataOrigin.REAL,
                    metadata={"parent_asin": "ASIN-1", "source_row": 10},
                ),
                EvidenceReference(
                    evidence_id="machine-review-uuid",
                    evidence_type="rag_excerpt",
                    knowledge_type=KnowledgeType.REVIEW_INSIGHT,
                    source_name="同类商品评论样本 ASIN-1",
                    excerpt="开关偶尔失效，清洁耙会卡住。",
                    data_origin=DataOrigin.REAL,
                    metadata={"parent_asin": "ASIN-1", "source_row": 20},
                ),
            ],
            "operation_plan": OperationPlan(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
                evidence_ids=["machine-review-uuid"],
                conclusions=[
                    Conclusion(
                        conclusion="上市前需要验证清洁耙可靠性。",
                        conclusion_type="recommendation",
                        confidence=0.8,
                        evidence_ids=["machine-review-uuid"],
                    )
                ],
            ),
        }
    )

    report = ReportExporter(tmp_path).export(state)
    markdown = Path(report.markdown_path).read_text(encoding="utf-8")
    review_item = report.sections["evidence_index"][1]

    assert "[证据2]" in markdown
    assert "### 证据2｜Nature's Miracle 自动猫砂盆用户评论" in markdown
    assert "`machine-review-uuid`" not in markdown
    assert review_item["evidence_id"] == "machine-review-uuid"
    assert review_item["display_label"] == "证据2"
    assert review_item["detail_path"].endswith("/evidence/machine-review-uuid")


def test_real_report_does_not_expose_machine_references_in_customer_narrative(
    tmp_path: Path,
) -> None:
    base = completed_state()
    state = base.model_copy(
        update={
            "data_mode": DataMode.REAL,
            "product_profile": base.product_profile.model_copy(
                update={"data_origin": DataOrigin.USER, "data_mode": DataMode.REAL}
            ),
            "user_insight": UserInsight(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
                insight_summary="基于20款同类商品共11571条评论的统计分析，清洗是主要关注点。",
                pain_points=[
                    "清洗步骤复杂（证据ID: f75f0967-29d7-4cb4-b8d5-02dd041f4782）",
                    "水泵噪音过大（证据ID: 无直接引用，仅为常见说法）",
                ],
                evidence_ids=["machine-review-uuid"],
            ),
            "product_market_analysis": ProductMarketAnalysis(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
                product_summary="如B0ABCDEF12展示了同类商品结构。",
                brand_positioning=["B0ABCDEF12属于同类商品样本。"],
                evidence_ids=["machine-product-uuid"],
            ),
            "audit_result": AuditResult(
                status=AuditStatus.PASS,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
            ),
            "operation_plan": OperationPlan(
                status=AgentStatus.SUCCEEDED,
                data_origin=DataOrigin.USER,
                implementation_status=ImplementationStatus.PRODUCTION,
                positioning="突出易清洗体验。",
                messaging_strategy=[
                    "removable reservoir and visible water level；Professional, Caring, Modern"
                ],
            ),
            "rag_evidence": [
                EvidenceReference(
                    evidence_id="machine-review-uuid",
                    evidence_type="rag_excerpt",
                    knowledge_type=KnowledgeType.REVIEW_INSIGHT,
                    source_name="同类商品评论样本 B0ABCDEF12",
                    excerpt="Original review text.",
                    data_origin=DataOrigin.REAL,
                    metadata={
                        "parent_asin": "B0ABCDEF12",
                        "source_row": 12,
                        "evidence_scope": "peer_product",
                    },
                )
            ],
            "selected_peer_products": [
                {"parent_asin": "B0ABCDEF12", "title": "CleanFlow Cat Fountain"}
            ],
        }
    )

    report = ReportExporter(tmp_path).export(state)
    markdown = Path(report.markdown_path).read_text(encoding="utf-8")

    assert "f75f0967-29d7-4cb4-b8d5-02dd041f4782" not in markdown
    assert "evidence_id" not in markdown
    assert "证据ID" not in markdown
    assert "B0ABCDEF12" not in markdown
    assert "20款" not in markdown
    assert "11571条" not in markdown
    assert "参考 Amazon 数据中的同类市场商品及其真实评论样本" in markdown
    assert "同类组：" not in markdown
    assert "基于 Amazon 同类市场商品及其真实评论样本" in markdown
    assert "水泵噪音过大" not in markdown
    assert "removable reservoir" not in markdown
    assert "visible water level" not in markdown
    assert "Professional, Caring, Modern" not in markdown
    assert "可拆卸储水容器和可视水位；专业、关怀、现代" in markdown
    assert "### 证据1｜CleanFlow Cat Fountain用户评论" in markdown
    assert "同类市场商品的真实用户评论；原始文本未改写" in markdown
