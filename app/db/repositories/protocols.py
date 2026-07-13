from typing import Any, Protocol, runtime_checkable

from app.core.enums import AgentStatus, DataOrigin, RunStatus
from app.schemas.analysis import AgentOutputRead, AnalysisRunCreate, AnalysisRunRead
from app.schemas.product import ProductCreate, ProductProfile
from app.schemas.report import FinalReport
from app.workflows.state import TradePilotState


@runtime_checkable
class ProductRepository(Protocol):
    def create(self, payload: ProductCreate, *, data_origin: DataOrigin) -> ProductProfile: ...

    def get(self, product_id: str) -> ProductProfile: ...

    def list(self) -> list[ProductProfile]: ...


@runtime_checkable
class AnalysisRepository(Protocol):
    def create_run(self, payload: AnalysisRunCreate) -> AnalysisRunRead: ...

    def get_run(self, run_id: str) -> AnalysisRunRead: ...

    def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        current_node: str,
        retry_count: int,
        state: dict[str, Any],
        report_id: str | None = None,
    ) -> AnalysisRunRead: ...

    def save_agent_output(
        self,
        run_id: str,
        *,
        agent_name: str,
        status: AgentStatus,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        error: dict[str, Any] | None = None,
    ) -> AgentOutputRead: ...

    def list_agent_outputs(self, run_id: str) -> list[AgentOutputRead]: ...

    def persist_result(self, state: TradePilotState, report: FinalReport) -> AnalysisRunRead: ...

    def get_report(self, report_id: str) -> FinalReport: ...
