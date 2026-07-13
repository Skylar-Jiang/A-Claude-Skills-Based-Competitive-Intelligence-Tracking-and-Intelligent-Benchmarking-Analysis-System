from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import (
    AgentStatus,
    AuditStatus,
    DataMode,
    DataOrigin,
    ImplementationStatus,
    RunStatus,
)
from app.schemas.common import Conclusion, DataGap


class ScaffoldAgentOutput(BaseModel):
    status: AgentStatus
    data_origin: DataOrigin
    implementation_status: ImplementationStatus = ImplementationStatus.SCAFFOLD
    conclusions: list[Conclusion] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)
    scaffold_note: str = "Deterministic scaffold output; deferred business analysis is not implemented."


class ProductMarketAnalysis(ScaffoldAgentOutput):
    product_summary: str = ""


class UserInsight(ScaffoldAgentOutput):
    insight_summary: str = ""


class OperationPlan(ScaffoldAgentOutput):
    positioning: str = ""
    next_steps: list[str] = Field(default_factory=list)


class AuditResult(BaseModel):
    status: AuditStatus
    data_origin: DataOrigin
    implementation_status: ImplementationStatus = ImplementationStatus.SCAFFOLD
    issues: list[str] = Field(default_factory=list)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    manual_review_required: bool = False


class AnalysisRunCreate(BaseModel):
    product_id: str
    data_mode: DataMode = DataMode.DEMO
    session_id: str | None = None
    thread_id: str | None = None
    target_market: str | None = None
    user_constraints: dict[str, Any] = Field(default_factory=dict)


class AnalysisRunRead(BaseModel):
    run_id: str
    product_id: str
    data_mode: DataMode
    status: RunStatus
    current_node: str
    retry_count: int
    report_id: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)


class FeedbackCreate(BaseModel):
    message: str = Field(min_length=1)


class AgentOutputRead(BaseModel):
    agent_name: str
    status: AgentStatus
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
