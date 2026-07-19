from threading import Barrier
from time import sleep

from app.agents.evidence_audit import EvidenceAuditAgent
from app.agents.operations_decision import OperationsDecisionAgent
from app.agents.product_market import ProductMarketAgent
from app.agents.user_insight import UserInsightAgent
from app.core.enums import AgentStatus, AuditStatus, DataMode, DataOrigin, KnowledgeType, RetrievalScope
from app.rag.contracts import KnowledgeDocument
from app.rag.in_memory import InMemoryKnowledgeStore
from app.schemas.analysis import AuditResult, OperationPlan, ProductMarketAnalysis, UserInsight
from app.schemas.common import DataGap
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductCreate, ProductProfile
from app.statistics.contracts import StatisticsResult
from app.workflows.graph import TradePilotWorkflow
from app.workflows.state import TradePilotState


def initial_state() -> TradePilotState:
    product = ProductProfile(
        product_id="product-1",
        data_origin=DataOrigin.DEMO,
        **ProductCreate(
            name=" DEMO Portable Organizer ",
            category="demo-generic",
            data_mode=DataMode.DEMO,
        ).model_dump(),
    )
    return TradePilotState(
        task_id="task-1",
        run_id="run-1",
        session_id="session-1",
        thread_id="thread-1",
        data_mode=DataMode.DEMO,
        product_profile=product,
    )


class ParallelProductAgent(ProductMarketAgent):
    def __init__(self, barrier: Barrier) -> None:
        super().__init__()
        self.barrier = barrier

    def run(self, context):  # type: ignore[no-untyped-def]
        self.barrier.wait(timeout=2)
        sleep(0.02)
        return ProductMarketAnalysis(status=AgentStatus.SUCCEEDED, data_origin=DataOrigin.DEMO)


class ParallelInsightAgent(UserInsightAgent):
    def __init__(self, barrier: Barrier) -> None:
        super().__init__()
        self.barrier = barrier

    def run(self, context):  # type: ignore[no-untyped-def]
        self.barrier.wait(timeout=2)
        sleep(0.02)
        return UserInsight(status=AgentStatus.SUCCEEDED, data_origin=DataOrigin.DEMO)


class CountingOperationsAgent(OperationsDecisionAgent):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def run(self, context):  # type: ignore[no-untyped-def]
        self.calls += 1
        return OperationPlan(status=AgentStatus.SUCCEEDED, data_origin=DataOrigin.DEMO)


class RejectingAuditAgent(EvidenceAuditAgent):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def run(self, context):  # type: ignore[no-untyped-def]
        self.calls += 1
        return AuditResult(status=AuditStatus.REJECTED, data_origin=DataOrigin.DEMO)


class RecordingStatisticsProvider:
    def __init__(self) -> None:
        self.calls = 0

    def get_statistics(self, *, product: ProductProfile) -> StatisticsResult:
        self.calls += 1
        return StatisticsResult(
            product_id=product.product_id,
            status=AgentStatus.INSUFFICIENT_EVIDENCE,
            data_origin=DataOrigin.DEMO,
        )


def test_state_graph_runs_first_two_agents_in_parallel() -> None:
    barrier = Barrier(2)
    statistics = RecordingStatisticsProvider()
    workflow = TradePilotWorkflow(
        knowledge_store=InMemoryKnowledgeStore(),
        statistics_provider=statistics,
        product_market_agent=ParallelProductAgent(barrier),
        user_insight_agent=ParallelInsightAgent(barrier),
    )

    result = TradePilotState.model_validate(workflow.invoke(initial_state()))

    assert result.product_profile.name == "DEMO Portable Organizer"
    assert result.product_market_analysis is not None
    assert result.user_insight is not None
    assert result.statistics_result is not None
    assert statistics.calls == 1
    assert result.audit_result is not None
    assert result.audit_result.status is AuditStatus.PASS
    graph = workflow.compiled.get_graph()
    assert any(edge.source == "product_normalizer" and edge.target == "statistics_provider" for edge in graph.edges)
    assert any(edge.source == "statistics_provider" and edge.target == "product_market_agent" for edge in graph.edges)
    assert any(edge.source == "statistics_provider" and edge.target == "user_insight_agent" for edge in graph.edges)
    market_execution = result.node_status["product_market_agent"]
    insight_execution = result.node_status["user_insight_agent"]
    assert market_execution.started_at is not None and market_execution.completed_at is not None
    assert insight_execution.started_at is not None and insight_execution.completed_at is not None
    assert max(market_execution.started_at, insight_execution.started_at) < min(
        market_execution.completed_at,
        insight_execution.completed_at,
    )
    assert result.workflow_metadata["parallel_agent_overlap"] is True
    assert result.workflow_metadata["rag_retrieval_duration_ms"] >= 0
    assert result.workflow_metadata["statistics_query_duration_ms"] >= 0



def test_rejected_audit_retries_operations_once_then_stops() -> None:
    operations = CountingOperationsAgent()
    audit = RejectingAuditAgent()
    workflow = TradePilotWorkflow(
        knowledge_store=InMemoryKnowledgeStore(),
        operations_decision_agent=operations,
        evidence_audit_agent=audit,
    )

    result = TradePilotState.model_validate(workflow.invoke(initial_state()))

    assert operations.calls == 2
    assert audit.calls == 2
    assert result.retry_count == 1
    assert result.audit_result is not None
    assert result.audit_result.manual_review_required is True
    assert result.current_node == "persist_and_export"


def test_real_new_product_workflow_retrieves_peer_group_evidence() -> None:
    store = InMemoryKnowledgeStore()
    store.ingest(
        [
            KnowledgeDocument(
                document_id="peer-review-evidence",
                product_id="listed-peer-1",
                knowledge_type=KnowledgeType.REVIEW_INSIGHT,
                content="A real review belonging to a listed peer product.",
                source_name="real peer review",
                data_origin=DataOrigin.REAL,
                metadata={"peer_group_id": "fountain-group", "evidence_scope": "peer_product"},
            )
        ]
    )
    state = initial_state().model_copy(
        update={
            "data_mode": DataMode.REAL,
            "peer_group_id": "fountain-group",
            "retrieval_scope": RetrievalScope.PEER_GROUP,
        }
    )
    workflow = TradePilotWorkflow(knowledge_store=store)

    result = TradePilotState.model_validate(workflow.invoke(state))

    assert "peer-review-evidence" in {item.evidence_id for item in result.rag_evidence}
    peer_review = next(item for item in result.rag_evidence if item.evidence_id == "peer-review-evidence")
    assert peer_review.metadata["candidate_product_id"] == "product-1"
    assert any(item.evidence_type == "sql_statistics" for item in result.rag_evidence)


def test_peer_group_filter_keeps_product_background_evidence() -> None:
    store = InMemoryKnowledgeStore()
    store.ingest(
        [
            KnowledgeDocument(
                document_id="selected-peer-evidence",
                product_id="listed-peer-1",
                knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
                content="A selected peer product.",
                source_name="selected peer",
                data_origin=DataOrigin.REAL,
                metadata={
                    "peer_group_id": "fountain-group",
                    "evidence_scope": "peer_product",
                    "parent_asin": "PEER-A",
                },
            )
        ]
    )
    background = EvidenceReference(
        evidence_id="us-hts-8421210000-2026-01-01",
        evidence_type="product_background",
        knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
        source_name="USITC Harmonized Tariff Schedule",
        excerpt="Candidate HTS 8421210000.",
        data_origin=DataOrigin.REAL,
        metadata={
            "source_type": "product_background_provider",
            "evidence_scope": "product_background",
        },
    )
    state = initial_state().model_copy(
        update={
            "data_mode": DataMode.REAL,
            "peer_group_id": "fountain-group",
            "retrieval_scope": RetrievalScope.PEER_GROUP,
            "selected_parent_asins": ["PEER-A"],
            "background_evidence": [background],
        }
    )

    result = TradePilotState.model_validate(TradePilotWorkflow(knowledge_store=store).invoke(state))

    evidence_ids = {item.evidence_id for item in result.rag_evidence}
    assert "selected-peer-evidence" in evidence_ids
    assert "us-hts-8421210000-2026-01-01" in evidence_ids


def test_peer_matching_data_gap_reaches_statistics_and_analysis_agents() -> None:
    gap = DataGap(
        code="insufficient_peer_products",
        field="peer_group",
        reason="Only 6 peer products passed the configured semantic threshold.",
        required_for="broader peer-market coverage",
    )
    state = initial_state().model_copy(update={"data_gaps": [gap]})
    workflow = TradePilotWorkflow(knowledge_store=InMemoryKnowledgeStore())

    result = TradePilotState.model_validate(workflow.invoke(state))

    assert result.statistics_result is not None
    assert gap in result.statistics_result.data_gaps
    assert result.product_market_analysis is not None
    assert gap in result.product_market_analysis.data_gaps
    assert result.user_insight is not None
    assert gap in result.user_insight.data_gaps
