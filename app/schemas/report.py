from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import AuditStatus, DataOrigin, ImplementationStatus

DEMO_DISCLAIMER = "本报告基于演示数据生成，仅用于验证系统流程，不代表真实市场结论。"
REAL_DISCLAIMER = "本报告基于用户提供的新商品资料、真实同类商品结构化数据及同类商品评论样本生成。"


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
    markdown_path: str
    json_path: str
    created_at: datetime
