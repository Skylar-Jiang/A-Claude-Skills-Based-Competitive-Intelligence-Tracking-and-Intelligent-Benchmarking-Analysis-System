from pydantic import BaseModel, Field

from app.schemas.analysis import OperationPlan, ProductMarketAnalysis, UserInsight
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductProfile
from app.statistics.contracts import StatisticsResult


class ProductMarketAgentInput(BaseModel):
    product: ProductProfile
    evidence: list[EvidenceReference] = Field(default_factory=list)
    statistics: StatisticsResult
    user_constraints: dict[str, object] = Field(default_factory=dict)
    original_user_input: dict[str, object] = Field(default_factory=dict)


class UserInsightAgentInput(BaseModel):
    product: ProductProfile
    evidence: list[EvidenceReference] = Field(default_factory=list)
    statistics: StatisticsResult
    user_constraints: dict[str, object] = Field(default_factory=dict)
    original_user_input: dict[str, object] = Field(default_factory=dict)


class OperationsDecisionAgentInput(BaseModel):
    product: ProductProfile
    product_market_analysis: ProductMarketAnalysis
    user_insight: UserInsight


class EvidenceAuditAgentInput(BaseModel):
    product: ProductProfile
    operation_plan: OperationPlan
