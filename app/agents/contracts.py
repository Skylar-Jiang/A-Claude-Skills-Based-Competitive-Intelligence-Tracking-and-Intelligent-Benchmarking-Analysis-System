from pydantic import BaseModel, Field

from app.schemas.analysis import OperationPlan, ProductMarketAnalysis, UserInsight
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductProfile


class ProductMarketAgentInput(BaseModel):
    product: ProductProfile
    evidence: list[EvidenceReference] = Field(default_factory=list)


class UserInsightAgentInput(BaseModel):
    product: ProductProfile
    evidence: list[EvidenceReference] = Field(default_factory=list)


class OperationsDecisionAgentInput(BaseModel):
    product: ProductProfile
    product_market_analysis: ProductMarketAnalysis
    user_insight: UserInsight


class EvidenceAuditAgentInput(BaseModel):
    product: ProductProfile
    operation_plan: OperationPlan
