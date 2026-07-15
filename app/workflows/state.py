from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field

from app.background.contracts import BackgroundResult
from app.core.enums import DataMode, RetrievalScope
from app.schemas.analysis import AuditResult, OperationPlan, ProductMarketAnalysis, UserInsight
from app.schemas.common import AgentExecution, DataGap, utc_now
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductProfile
from app.statistics.contracts import StatisticsResult


def merge_node_status(
    left: dict[str, AgentExecution], right: dict[str, AgentExecution]
) -> dict[str, AgentExecution]:
    return {**left, **right}


class TradePilotState(BaseModel):
    task_id: str
    run_id: str
    session_id: str
    thread_id: str
    data_mode: DataMode
    product_profile: ProductProfile
    retrieval_scope: RetrievalScope = RetrievalScope.EXACT_PRODUCT
    peer_group_id: str | None = None
    selected_peer_products: list[dict[str, Any]] = Field(default_factory=list)
    selected_parent_asins: list[str] = Field(default_factory=list)
    peer_group_statistics: StatisticsResult | None = None
    product_evidence: list[EvidenceReference] = Field(default_factory=list)
    review_evidence: list[EvidenceReference] = Field(default_factory=list)
    review_sample_scope: dict[str, Any] = Field(default_factory=dict)
    match_method: str = ""
    match_limitations: list[str] = Field(default_factory=list)
    vision_analysis: dict[str, Any] | None = None
    peer_selection_metadata: dict[str, Any] = Field(default_factory=dict)
    workflow_metadata: dict[str, Any] = Field(default_factory=dict)
    background_context: BackgroundResult | None = None
    background_evidence: list[EvidenceReference] = Field(default_factory=list)
    target_market: str = ""
    user_constraints: dict[str, Any] = Field(default_factory=dict)
    product_market_analysis: ProductMarketAnalysis | None = None
    user_insight: UserInsight | None = None
    operation_plan: OperationPlan | None = None
    audit_result: AuditResult | None = None
    rag_evidence: list[EvidenceReference] = Field(default_factory=list)
    statistics_result: StatisticsResult | None = None
    data_gaps: list[DataGap] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    current_node: str = "pending"
    node_status: Annotated[dict[str, AgentExecution], merge_node_status] = Field(default_factory=dict)
    retry_count: int = Field(default=0, ge=0, le=1)
    report_version: int = 0
    report_id: str | None = None
    report_paths: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
