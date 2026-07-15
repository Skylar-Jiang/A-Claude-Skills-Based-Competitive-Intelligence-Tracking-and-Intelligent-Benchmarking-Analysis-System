from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.core.enums import DataOrigin
from app.schemas.common import DataGap


class BackgroundQuery(BaseModel):
    product_name: str
    product_type: str
    market: str = ""
    jurisdiction: str = ""
    platform: str = ""
    context_types: list[str] = Field(default_factory=list)
    effective_date: date | None = None
    query_date: date
    user_constraints: dict[str, object] = Field(default_factory=dict)


class BackgroundEvidence(BaseModel):
    evidence_id: str
    context_type: str
    content: str
    source_name: str
    source_uri: str
    effective_date: date | None = None
    jurisdiction: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)
    data_origin: DataOrigin = DataOrigin.REAL
    data_gaps: list[DataGap] = Field(default_factory=list)


class BackgroundResult(BaseModel):
    provider: str
    query: BackgroundQuery
    evidence: list[BackgroundEvidence] = Field(default_factory=list)
    text: str = ""
    data_gaps: list[DataGap] = Field(default_factory=list)


@runtime_checkable
class BackgroundProvider(Protocol):
    name: str

    def query(self, query: BackgroundQuery) -> BackgroundResult: ...
