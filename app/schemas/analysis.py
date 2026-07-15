from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import (
    AgentStatus,
    AuditStatus,
    DataMode,
    DataOrigin,
    ImplementationStatus,
    RunStageStatus,
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
    evidence_references: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence_types: list[str] = Field(default_factory=list)
    unverifiable_claims: list[str] = Field(default_factory=list)
    statistics_result_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    scaffold_note: str = "Deterministic scaffold output; deferred business analysis is not implemented."


class ProductMarketAnalysis(ScaffoldAgentOutput):
    peer_group_id: str | None = None
    selected_parent_asins: list[str] = Field(default_factory=list)
    product_summary: str = ""
    price_analysis: str = ""
    feature_baseline: list[str] = Field(default_factory=list)
    structure_and_scenarios: list[str] = Field(default_factory=list)
    brand_positioning: list[str] = Field(default_factory=list)
    rating_analysis: str = ""
    homogenization_risks: list[str] = Field(default_factory=list)
    differentiation_opportunities: list[str] = Field(default_factory=list)
    missing_parameters: list[str] = Field(default_factory=list)
    prelaunch_validations: list[str] = Field(default_factory=list)
    reasoned_hypotheses: list[str] = Field(default_factory=list)
    product_category: str = ""
    product_functions: list[str] = Field(default_factory=list)
    key_parameters: list[str] = Field(default_factory=list)
    usage_scenarios: list[str] = Field(default_factory=list)
    target_users: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    competitor_differences: list[str] = Field(default_factory=list)
    target_market_fit: str | None = None
    optimization_suggestions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class UserInsight(ScaffoldAgentOutput):
    peer_group_id: str | None = None
    selected_parent_asins: list[str] = Field(default_factory=list)
    insight_summary: str = ""
    common_needs: list[str] = Field(default_factory=list)
    positive_experiences: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    purchase_factors: list[str] = Field(default_factory=list)
    feature_usage_maintenance_concerns: list[str] = Field(default_factory=list)
    prelaunch_validations: list[str] = Field(default_factory=list)
    convertible_selling_points: list[str] = Field(default_factory=list)
    optimization_directions: list[str] = Field(default_factory=list)
    sample_limitations: list[str] = Field(default_factory=list)
    reasoned_hypotheses: list[str] = Field(default_factory=list)
    target_user_profiles: list[str] = Field(default_factory=list)
    identity_or_demographic_observations: list[str] = Field(default_factory=list)
    usage_scenarios: list[str] = Field(default_factory=list)
    purchase_motivations: list[str] = Field(default_factory=list)
    positive_concerns: list[str] = Field(default_factory=list)
    frequent_keywords: list[str] = Field(default_factory=list)
    negative_review_reasons: list[str] = Field(default_factory=list)
    user_expectations: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)


class OperationPlan(ScaffoldAgentOutput):
    positioning: str = ""
    next_steps: list[str] = Field(default_factory=list)
    peer_group_id: str | None = None
    selected_parent_asins: list[str] = Field(default_factory=list)
    analysis_scopes: dict[str, Any] = Field(default_factory=dict)


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
    jurisdiction: str = ""
    platform: str = ""
    background_context_types: list[str] = Field(default_factory=list)
    background_provider: str | None = None
    effective_date: date | None = None
    query_date: date | None = None
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


class RunStageRead(BaseModel):
    stage_key: str
    sequence: int
    status: RunStageStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class AnalysisEventRead(BaseModel):
    event_id: int
    run_id: str
    event_type: str
    stage_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
