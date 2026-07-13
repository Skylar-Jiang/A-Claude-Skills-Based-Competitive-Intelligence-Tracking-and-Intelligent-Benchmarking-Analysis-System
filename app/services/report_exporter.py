import json
from pathlib import Path
from uuid import uuid4

from app.core.enums import DataOrigin
from app.schemas.common import utc_now
from app.schemas.report import DEMO_DISCLAIMER, FinalReport
from app.workflows.state import TradePilotState


class ReportExporter:
    def __init__(self, report_dir: Path) -> None:
        self.report_dir = report_dir

    def export(self, state: TradePilotState) -> FinalReport:
        if state.audit_result is None:
            raise ValueError("audit result is required before report export")
        self.report_dir.mkdir(parents=True, exist_ok=True)
        report_id = str(uuid4())
        json_path = (self.report_dir / f"{report_id}.json").resolve()
        markdown_path = (self.report_dir / f"{report_id}.md").resolve()
        sections = {
            "product_profile": state.product_profile.model_dump(mode="json"),
            "product_market_analysis": self._dump(state.product_market_analysis),
            "user_insight": self._dump(state.user_insight),
            "operation_plan": self._dump(state.operation_plan),
            "audit_result": state.audit_result.model_dump(mode="json"),
        }
        report = FinalReport(
            report_id=report_id,
            run_id=state.run_id,
            audit_status=state.audit_result.status,
            data_origin=DataOrigin.DEMO,
            is_demo=True,
            disclaimer=DEMO_DISCLAIMER,
            sections=sections,
            markdown_path=str(markdown_path),
            json_path=str(json_path),
            created_at=utc_now(),
        )
        json_path.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        markdown_path.write_text(self._markdown(report), encoding="utf-8")
        return report

    @staticmethod
    def _dump(value: object) -> dict[str, object] | None:
        return value.model_dump(mode="json") if value is not None else None  # type: ignore[union-attr]

    @staticmethod
    def _markdown(report: FinalReport) -> str:
        return "\n".join(
            [
                "# TradePilot DEMO Scaffold Report",
                "",
                f"> {report.disclaimer}",
                "",
                "- data_origin: `demo`",
                "- implementation_status: `scaffold`",
                f"- audit_status: `{report.audit_status.value}`",
                "",
                "## Scaffold outputs",
                "",
                "四个 Agent 当前仅返回确定性 Demo 占位结构；真实业务分析尚未实现。",
                "",
            ]
        )
