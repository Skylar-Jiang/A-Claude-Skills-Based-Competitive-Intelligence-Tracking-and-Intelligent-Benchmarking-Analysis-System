from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, Field

from app.core.enums import AgentStatus, DataOrigin, ImplementationStatus
from app.schemas.common import DataGap
from app.schemas.product import ProductProfile


class StatisticsResult(BaseModel):
    """Validated numeric facts supplied by a statistics implementation."""

    product_id: str
    result_id: str | None = None
    status: AgentStatus
    data_origin: DataOrigin
    implementation_status: ImplementationStatus = ImplementationStatus.SCAFFOLD
    metrics: dict[str, Decimal] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)


class StatisticsProvider(Protocol):
    def get_statistics(
        self,
        *,
        product: ProductProfile,
        peer_group_id: str | None = None,
    ) -> StatisticsResult: ...
