import json
from collections.abc import Callable
from time import perf_counter

from langgraph.graph import END, START, StateGraph

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
from app.core.enums import AgentStatus, AuditStatus, KnowledgeType
from app.rag.contracts import KnowledgeStore
from app.rag.pipeline import RetrievalPipeline
from app.rag.utils import stable_id
from app.schemas.common import AgentExecution, DataGap, utc_now
from app.schemas.evidence import EvidenceReference
from app.statistics.contracts import StatisticsProvider
from app.statistics.stub import ScaffoldStatisticsProvider
from app.workflows.state import TradePilotState

PersistCallback = Callable[[TradePilotState], dict[str, object]]


def _merge_data_gaps(*groups: list[DataGap]) -> list[DataGap]:
    merged: list[DataGap] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for group in groups:
        for gap in group:
            key = (gap.code, gap.field, gap.reason, gap.required_for)
            if key not in seen:
                seen.add(key)
                merged.append(gap)
    return merged


def _execution(
    name: str,
    status: AgentStatus = AgentStatus.SUCCEEDED,
    *,
    started_at=None,  # type: ignore[no-untyped-def]
    completed_at=None,  # type: ignore[no-untyped-def]
    duration_ms: int | None = None,
) -> dict[str, AgentExecution]:
    return {
        name: AgentExecution(
            agent_name=name,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
    }


class TradePilotWorkflow:
    def __init__(
        self,
        *,
        knowledge_store: KnowledgeStore,
        statistics_provider: StatisticsProvider | None = None,
        product_market_agent: ProductMarketAgent | None = None,
        user_insight_agent: UserInsightAgent | None = None,
        operations_decision_agent: OperationsDecisionAgent | None = None,
        evidence_audit_agent: EvidenceAuditAgent | None = None,
        persist_callback: PersistCallback | None = None,
    ) -> None:
        self.knowledge_store = knowledge_store
        self.retrieval_pipeline = RetrievalPipeline(knowledge_store)
        self.statistics_provider = statistics_provider or ScaffoldStatisticsProvider()
        self.product_market_agent = product_market_agent or ProductMarketAgent(
            retrieval_pipeline=self.retrieval_pipeline
        )
        self.user_insight_agent = user_insight_agent or UserInsightAgent(
            retrieval_pipeline=self.retrieval_pipeline
        )
        self.operations_decision_agent = operations_decision_agent or OperationsDecisionAgent()
        self.evidence_audit_agent = evidence_audit_agent or EvidenceAuditAgent()
        self.persist_callback = persist_callback
        self.compiled = self._build_graph().compile()

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(TradePilotState)
        graph.add_node("input_validator", self._input_validator)
        graph.add_node("product_normalizer", self._product_normalizer)
        graph.add_node("statistics_provider", self._statistics_provider)
        graph.add_node("product_market_agent", self._product_market)
        graph.add_node("user_insight_agent", self._user_insight)
        graph.add_node("operations_decision_agent", self._operations_decision)
        graph.add_node("evidence_audit_agent", self._evidence_audit)
        graph.add_node("persist_and_export", self._persist_and_export)
        graph.add_edge(START, "input_validator")
        graph.add_edge("input_validator", "product_normalizer")
        graph.add_edge("product_normalizer", "statistics_provider")
        graph.add_edge("statistics_provider", "product_market_agent")
        graph.add_edge("statistics_provider", "user_insight_agent")
        graph.add_edge(
            ["product_market_agent", "user_insight_agent"],
            "operations_decision_agent",
        )
        graph.add_edge("operations_decision_agent", "evidence_audit_agent")
        graph.add_conditional_edges(
            "evidence_audit_agent",
            self._route_after_audit,
            {"retry": "operations_decision_agent", "persist": "persist_and_export"},
        )
        graph.add_edge("persist_and_export", END)
        return graph

    def invoke(self, state: TradePilotState) -> dict[str, object]:
        return self.compiled.invoke(state)

    @staticmethod
    def _input_validator(state: TradePilotState) -> dict[str, object]:
        TradePilotState.model_validate(state)
        return {
            "current_node": "input_validator",
            "node_status": _execution("input_validator"),
        }

    def _product_normalizer(self, state: TradePilotState) -> dict[str, object]:
        started_at = utc_now()
        started = perf_counter()
        product = state.product_profile.model_copy(
            update={"name": state.product_profile.name.strip(), "category": state.product_profile.category.strip()}
        )
        evidence = []
        gaps = []
        for knowledge_type in KnowledgeType:
            result = self.knowledge_store.retrieve(
                query=product.name,
                product_id=product.product_id,
                knowledge_type=knowledge_type,
                scope=state.retrieval_scope,
                peer_group_id=state.peer_group_id,
            )
            evidence.extend(result.evidence)
            gaps.extend(result.data_gaps)
        if state.retrieval_scope.value == "peer_group" and state.selected_parent_asins:
            selected = set(state.selected_parent_asins)
            evidence = [item for item in evidence if str(item.metadata.get("parent_asin") or "") in selected]
        product_evidence = [
            item for item in evidence if item.knowledge_type is KnowledgeType.PRODUCT_KNOWLEDGE
        ]
        review_evidence = [
            item for item in evidence if item.knowledge_type is KnowledgeType.REVIEW_INSIGHT
        ]
        completed_at = utc_now()
        return {
            "product_profile": product,
            "rag_evidence": evidence,
            "product_evidence": product_evidence,
            "review_evidence": review_evidence,
            "review_sample_scope": {
                "peer_group_id": state.peer_group_id,
                "selected_parent_asins": state.selected_parent_asins,
                "retrieved_review_evidence_count": len(review_evidence),
            },
            "data_gaps": _merge_data_gaps(state.data_gaps, gaps),
            "current_node": "product_normalizer",
            "node_status": _execution(
                "product_normalizer",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round((perf_counter() - started) * 1000),
            ),
        }

    def _statistics_provider(self, state: TradePilotState) -> dict[str, object]:
        started_at = utc_now()
        started = perf_counter()
        if state.peer_group_id:
            result = self.statistics_provider.get_statistics(
                product=state.product_profile,
                peer_group_id=state.peer_group_id,
            )
        else:
            result = self.statistics_provider.get_statistics(product=state.product_profile)
        statistics_evidence = EvidenceReference(
            evidence_id=stable_id(
                "statistics",
                state.product_profile.product_id,
                state.peer_group_id or "exact_product",
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
            ),
            evidence_type="sql_statistics",
            knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
            source_name="TradePilot peer-group SQL statistics",
            excerpt=json.dumps(result.metrics, ensure_ascii=False, default=str, sort_keys=True),
            data_origin=result.data_origin,
            is_demo=result.data_origin.value == "demo",
            metadata={
                "source_type": "sql_statistics",
                "evidence_scope": "peer_group" if state.peer_group_id else "exact_product",
                "peer_group_id": state.peer_group_id or "",
                "candidate_product_id": state.product_profile.product_id,
            },
        )
        merged_gaps = _merge_data_gaps(state.data_gaps, result.data_gaps)
        result = result.model_copy(
            update={
                "evidence_ids": list(dict.fromkeys([*result.evidence_ids, statistics_evidence.evidence_id])),
                "data_gaps": merged_gaps,
            }
        )
        completed_at = utc_now()
        return {
            "statistics_result": result,
            "peer_group_statistics": result if state.peer_group_id else None,
            "rag_evidence": [*state.rag_evidence, statistics_evidence],
            "product_evidence": [*state.product_evidence, statistics_evidence],
            "data_gaps": merged_gaps,
            "current_node": "statistics_provider",
            "node_status": _execution(
                "statistics_provider",
                result.status,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round((perf_counter() - started) * 1000),
            ),
        }

    def _product_market(self, state: TradePilotState) -> dict[str, object]:
        if state.statistics_result is None:
            raise ValueError("statistics result is required")
        evidence = state.product_evidence
        started_at = utc_now()
        started = perf_counter()
        output = self.product_market_agent.run(
            ProductMarketAgentInput(
                product=state.product_profile,
                evidence=evidence,
                statistics=state.statistics_result,
                peer_group_id=state.peer_group_id,
                selected_parent_asins=state.selected_parent_asins,
                selected_peer_products=state.selected_peer_products,
                user_constraints=state.user_constraints,
            )
        )
        completed_at = utc_now()
        return {
            "product_market_analysis": output,
            "node_status": _execution(
                "product_market_agent",
                output.status,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round((perf_counter() - started) * 1000),
            ),
        }

    def _user_insight(self, state: TradePilotState) -> dict[str, object]:
        if state.statistics_result is None:
            raise ValueError("statistics result is required")
        evidence = state.review_evidence
        started_at = utc_now()
        started = perf_counter()
        output = self.user_insight_agent.run(
            UserInsightAgentInput(
                product=state.product_profile,
                evidence=evidence,
                statistics=state.statistics_result,
                peer_group_id=state.peer_group_id,
                selected_parent_asins=state.selected_parent_asins,
                selected_peer_products=state.selected_peer_products,
                user_constraints=state.user_constraints,
            )
        )
        completed_at = utc_now()
        return {
            "user_insight": output,
            "node_status": _execution(
                "user_insight_agent",
                output.status,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round((perf_counter() - started) * 1000),
            ),
        }

    def _operations_decision(self, state: TradePilotState) -> dict[str, object]:
        if state.product_market_analysis is None or state.user_insight is None:
            raise ValueError("parallel agent outputs are required")
        started_at = utc_now()
        started = perf_counter()
        output = self.operations_decision_agent.run(
            OperationsDecisionAgentInput(
                product=state.product_profile,
                product_market_analysis=state.product_market_analysis,
                user_insight=state.user_insight,
                statistics=state.statistics_result,
                evidence=state.rag_evidence,
                peer_group_id=state.peer_group_id,
                selected_parent_asins=state.selected_parent_asins,
                user_constraints=state.user_constraints,
            )
        )
        completed_at = utc_now()
        return {
            "operation_plan": output,
            "current_node": "operations_decision_agent",
            "node_status": _execution(
                "operations_decision_agent",
                output.status,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round((perf_counter() - started) * 1000),
            ),
        }

    def _evidence_audit(self, state: TradePilotState) -> dict[str, object]:
        if state.operation_plan is None:
            raise ValueError("operation plan is required")
        started_at = utc_now()
        started = perf_counter()
        output = self.evidence_audit_agent.run(
            EvidenceAuditAgentInput(
                product=state.product_profile,
                operation_plan=state.operation_plan,
                evidence=state.rag_evidence,
                statistics=state.statistics_result,
                peer_group_id=state.peer_group_id,
            )
        )
        completed_at = utc_now()
        if output.status is AuditStatus.REJECTED and state.retry_count == 0:
            current_node = "evidence_audit_retry"
            retry_count = 1
        elif output.status is AuditStatus.REJECTED:
            current_node = "evidence_audit_final"
            retry_count = state.retry_count
            output = output.model_copy(update={"manual_review_required": True})
        else:
            current_node = "evidence_audit_pass"
            retry_count = state.retry_count
        return {
            "audit_result": output,
            "retry_count": retry_count,
            "current_node": current_node,
            "node_status": _execution(
                "evidence_audit_agent",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round((perf_counter() - started) * 1000),
            ),
        }

    @staticmethod
    def _route_after_audit(state: TradePilotState) -> str:
        return "retry" if state.current_node == "evidence_audit_retry" else "persist"

    def _persist_and_export(self, state: TradePilotState) -> dict[str, object]:
        completed_at = utc_now()
        rag_execution = state.node_status.get("product_normalizer")
        statistics_execution = state.node_status.get("statistics_provider")
        workflow_metadata = {
            **state.workflow_metadata,
            "started_at": state.created_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_ms": round((completed_at - state.created_at).total_seconds() * 1000),
            "parallel_agent_overlap": self._parallel_overlap(state),
            "rag_retrieval_duration_ms": rag_execution.duration_ms if rag_execution else None,
            "statistics_query_duration_ms": (
                statistics_execution.duration_ms if statistics_execution else None
            ),
        }
        final_state = state.model_copy(
            update={
                "current_node": "persist_and_export",
                "workflow_metadata": workflow_metadata,
                "updated_at": completed_at,
            }
        )
        updates = self.persist_callback(final_state) if self.persist_callback else {}
        return {
            **updates,
            "current_node": "persist_and_export",
            "workflow_metadata": workflow_metadata,
            "updated_at": completed_at,
            "node_status": _execution("persist_and_export"),
        }

    @staticmethod
    def _parallel_overlap(state: TradePilotState) -> bool:
        market = state.node_status.get("product_market_agent")
        insight = state.node_status.get("user_insight_agent")
        if not market or not insight:
            return False
        if not all((market.started_at, market.completed_at, insight.started_at, insight.completed_at)):
            return False
        return max(market.started_at, insight.started_at) < min(market.completed_at, insight.completed_at)
