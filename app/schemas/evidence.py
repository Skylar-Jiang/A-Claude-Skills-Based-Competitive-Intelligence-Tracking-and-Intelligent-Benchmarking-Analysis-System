from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.enums import AgentStatus, DataOrigin, KnowledgeType
from app.schemas.common import DataGap


class EvidenceReference(BaseModel):
    evidence_id: str
    evidence_type: str
    knowledge_type: KnowledgeType
    source_name: str
    source_uri: str | None = None
    excerpt: str
    published_at: datetime | None = None
    data_origin: DataOrigin
    is_demo: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_demo_marker(self) -> "EvidenceReference":
        if self.is_demo != (self.data_origin is DataOrigin.DEMO):
            raise ValueError("is_demo must be derived from data_origin")
        return self


class RetrievalResult(BaseModel):
    status: AgentStatus
    evidence: list[EvidenceReference] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)
