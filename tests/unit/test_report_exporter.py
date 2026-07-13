import json
from pathlib import Path

from app.core.enums import AgentStatus, AuditStatus, DataMode, DataOrigin
from app.schemas.analysis import AuditResult, OperationPlan, ProductMarketAnalysis, UserInsight
from app.schemas.product import ProductCreate, ProductProfile
from app.schemas.report import DEMO_DISCLAIMER
from app.services.report_exporter import ReportExporter
from app.workflows.state import TradePilotState


def completed_state() -> TradePilotState:
    product = ProductProfile(
        product_id="product-1",
        data_origin=DataOrigin.DEMO,
        **ProductCreate(
            name="DEMO Portable Organizer", category="demo", data_mode=DataMode.DEMO
        ).model_dump(),
    )
    return TradePilotState(
        task_id="task-1",
        run_id="run-1",
        session_id="session-1",
        thread_id="thread-1",
        data_mode=DataMode.DEMO,
        product_profile=product,
        product_market_analysis=ProductMarketAnalysis(
            status=AgentStatus.SUCCEEDED, data_origin=DataOrigin.DEMO
        ),
        user_insight=UserInsight(status=AgentStatus.SUCCEEDED, data_origin=DataOrigin.DEMO),
        operation_plan=OperationPlan(status=AgentStatus.SUCCEEDED, data_origin=DataOrigin.DEMO),
        audit_result=AuditResult(status=AuditStatus.PASS, data_origin=DataOrigin.DEMO),
    )


def test_exporter_writes_demo_scaffold_json_and_markdown(tmp_path: Path) -> None:
    report = ReportExporter(tmp_path).export(completed_state())

    json_path = Path(report.json_path)
    markdown_path = Path(report.markdown_path)
    assert json_path.exists()
    assert markdown_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["data_origin"] == "demo"
    assert payload["implementation_status"] == "scaffold"
    assert payload["disclaimer"] == DEMO_DISCLAIMER
    assert "DEMO" in markdown
    assert "Scaffold" in markdown
    assert DEMO_DISCLAIMER in markdown
