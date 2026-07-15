from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.enums import AuditStatus, DataOrigin, ImplementationStatus

DEMO_DISCLAIMER = "本报告基于演示数据生成，仅用于验证系统流程，不代表真实市场结论。"
REAL_DISCLAIMER = "本报告基于用户提供的新商品资料、真实同类商品结构化数据及同类商品评论样本生成。"


class ReportSectionDescriptor(BaseModel):
    section_id: str
    title: str


class FinalReport(BaseModel):
    report_id: str
    run_id: str
    version: int = 1
    audit_status: AuditStatus
    data_origin: DataOrigin
    implementation_status: ImplementationStatus = ImplementationStatus.SCAFFOLD
    is_demo: bool
    disclaimer: str
    sections: dict[str, Any] = Field(default_factory=dict)
    section_index: dict[str, ReportSectionDescriptor] = Field(default_factory=dict)
    parent_report_id: str | None = None
    changed_section_ids: list[str] = Field(default_factory=list)
    markdown_path: str
    json_path: str
    created_at: datetime


class ReportSupportRequest(BaseModel):
    action: Literal["explain", "edit"]
    section_id: str
    message: str = Field(min_length=1)
    replacement: Any | None = None
    conversation_id: str | None = None


class ReportRollbackRequest(BaseModel):
    target_version: int = Field(ge=1)
    reason: str = Field(min_length=1)
