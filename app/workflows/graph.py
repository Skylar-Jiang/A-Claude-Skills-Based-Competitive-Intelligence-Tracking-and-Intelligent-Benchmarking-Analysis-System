from collections.abc import Callable

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
from app.schemas.common import AgentExecution
from app.workflows.state import TradePilotState

PersistCallback = Callable[[TradePilotState], dict[str, object]]


def _execution(name: str, status: AgentStatus = AgentStatus.SUCCEEDED) -> dict[str, AgentExecution]:
    return {name: AgentExecution(agent_name=name, status=status)}


class TradePilotWorkflow:
    def __init__(
        self,
        *,
        knowledge_store: KnowledgeStore,
        product_market_agent: ProductMarketAgent | None = None,
        user_insight_agent: UserInsightAgent | None = None,
        operations_decision_agent: OperationsDecisionAgent | None = None,
        evidence_audit_agent: EvidenceAuditAgent | None = None,
        persist_callback: PersistCallback | None = None,
    ) -> None:
        self.knowledge_store = knowledge_store
        self.product_market_agent = product_market_agent or ProductMarketAgent()
        self.user_insight_agent = user_insight_agent or UserInsightAgent()
        self.operations_decision_agent = operations_decision_agent or OperationsDecisionAgent()
        self.evidence_audit_agent = evidence_audit_agent or EvidenceAuditAgent()
        self.persist_callback = persist_callback
        self.compiled = self._build_graph().compile()

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(TradePilotState)
        graph.add_node("input_validator", self._input_validator)
        graph.add_node("product_normalizer", self._product_normalizer)
        graph.add_node("product_market_agent", self._product_market)
        graph.add_node("user_insight_agent", self._user_insight)
        graph.add_node("operations_decision_agent", self._operations_decision)
        graph.add_node("evidence_audit_agent", self._evidence_audit)
        graph.add_node("persist_and_export", self._persist_and_export)
        graph.add_edge(START, "input_validator")
        graph.add_edge("input_validator", "product_normalizer")
        graph.add_edge("product_normalizer", "product_market_agent")
        graph.add_edge("product_normalizer", "user_insight_agent")
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
            )
            evidence.extend(result.evidence)
            gaps.extend(result.data_gaps)
        return {
            "product_profile": product,
            "rag_evidence": evidence,
            "data_gaps": gaps,
            "current_node": "product_normalizer",
            "node_status": _execution("product_normalizer"),
        }

    def _product_market(self, state: TradePilotState) -> dict[str, object]:
        evidence = [
            item for item in state.rag_evidence if item.knowledge_type is KnowledgeType.PRODUCT_KNOWLEDGE
        ]
        output = self.product_market_agent.run(
            ProductMarketAgentInput(product=state.product_profile, evidence=evidence)
        )
        return {
            "product_market_analysis": output,
            "node_status": _execution("product_market_agent", output.status),
        }

    def _user_insight(self, state: TradePilotState) -> dict[str, object]:
        evidence = [
            item for item in state.rag_evidence if item.knowledge_type is KnowledgeType.REVIEW_INSIGHT
        ]
        output = self.user_insight_agent.run(
            UserInsightAgentInput(product=state.product_profile, evidence=evidence)
        )
        return {
            "user_insight": output,
            "node_status": _execution("user_insight_agent", output.status),
        }

    def _operations_decision(self, state: TradePilotState) -> dict[str, object]:
        if state.product_market_analysis is None or state.user_insight is None:
            raise ValueError("parallel agent outputs are required")
        output = self.operations_decision_agent.run(
            OperationsDecisionAgentInput(
                product=state.product_profile,
                product_market_analysis=state.product_market_analysis,
                user_insight=state.user_insight,
            )
        )
        return {
            "operation_plan": output,
            "current_node": "operations_decision_agent",
            "node_status": _execution("operations_decision_agent", output.status),
        }

    def _evidence_audit(self, state: TradePilotState) -> dict[str, object]:
        if state.operation_plan is None:
            raise ValueError("operation plan is required")
        output = self.evidence_audit_agent.run(
            EvidenceAuditAgentInput(product=state.product_profile, operation_plan=state.operation_plan)
        )
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
            "node_status": _execution("evidence_audit_agent"),
        }

    @staticmethod
    def _route_after_audit(state: TradePilotState) -> str:
        return "retry" if state.current_node == "evidence_audit_retry" else "persist"

    def _persist_and_export(self, state: TradePilotState) -> dict[str, object]:
        updates = self.persist_callback(state) if self.persist_callback else {}
        return {
            **updates,
            "current_node": "persist_and_export",
            "node_status": _execution("persist_and_export"),
        }
