from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import AgentStatus, DataMode


def utc_now() -> datetime:
    return datetime.now(UTC)


class DataGap(BaseModel):
    code: str = "unspecified"
    field: str
    reason: str
    required_for: str | None = None


class Conclusion(BaseModel):
    conclusion: str
    conclusion_type: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)


class AgentExecution(BaseModel):
    agent_name: str
    status: AgentStatus = AgentStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error: dict[str, Any] | None = None


class ResponseMeta(BaseModel):
    request_id: str
    api_version: str = "v1"
    data_mode: DataMode | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)


class ApiResponse[T](BaseModel):
    success: bool
    data: T | None = None
    meta: ResponseMeta
    error: ErrorBody | None = None
