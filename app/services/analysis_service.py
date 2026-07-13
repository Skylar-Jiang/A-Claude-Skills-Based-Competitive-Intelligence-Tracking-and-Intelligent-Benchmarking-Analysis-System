from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import DataMode
from app.core.exceptions import LLMNotConfiguredError, ScaffoldOnlyError
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository, SqlAlchemyProductRepository
from app.rag.contracts import KnowledgeStore
from app.schemas.analysis import AnalysisRunCreate, AnalysisRunRead
from app.schemas.report import FinalReport
from app.services.report_exporter import ReportExporter
from app.workflows.graph import TradePilotWorkflow
from app.workflows.state import TradePilotState


class AnalysisService:
    def __init__(
        self,
        *,
        session: Session,
        knowledge_store: KnowledgeStore,
        report_dir: Path,
        settings: Settings,
    ) -> None:
        self.products = SqlAlchemyProductRepository(session)
        self.analyses = SqlAlchemyAnalysisRepository(session)
        self.knowledge_store = knowledge_store
        self.exporter = ReportExporter(report_dir)
        self.settings = settings

    def start(self, payload: AnalysisRunCreate) -> AnalysisRunRead:
        if payload.data_mode is DataMode.REAL:
            if not self.settings.real_model_configured:
                raise LLMNotConfiguredError()
            raise ScaffoldOnlyError()
        if payload.data_mode is DataMode.MOCK:
            raise ScaffoldOnlyError("mock")
        product = self.products.get(payload.product_id)
        run = self.analyses.create_run(payload)

        def persist(state: TradePilotState) -> dict[str, object]:
            report = self.exporter.export(state)
            self.analyses.persist_result(state, report)
            return {
                "report_id": report.report_id,
                "report_version": report.version,
                "report_paths": {"json": report.json_path, "markdown": report.markdown_path},
            }

        workflow = TradePilotWorkflow(
            knowledge_store=self.knowledge_store,
            persist_callback=persist,
        )
        state = TradePilotState(
            task_id=run.run_id,
            run_id=run.run_id,
            session_id=payload.session_id or str(uuid4()),
            thread_id=payload.thread_id or str(uuid4()),
            data_mode=payload.data_mode,
            product_profile=product,
            target_market=payload.target_market or product.target_market,
            user_constraints=payload.user_constraints,
        )
        workflow.invoke(state)
        return self.analyses.get_run(run.run_id)

    def get_run(self, run_id: str) -> AnalysisRunRead:
        return self.analyses.get_run(run_id)

    def list_agent_outputs(self, run_id: str):  # type: ignore[no-untyped-def]
        self.analyses.get_run(run_id)
        return self.analyses.list_agent_outputs(run_id)

    def get_report(self, report_id: str) -> FinalReport:
        return self.analyses.get_report(report_id)
