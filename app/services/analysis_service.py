from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import DataMode, ErrorCode, RetrievalScope, RunStatus
from app.core.exceptions import LLMNotConfiguredError, ScaffoldOnlyError, TradePilotError
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository, SqlAlchemyProductRepository
from app.rag.contracts import KnowledgeStore
from app.schemas.analysis import AnalysisRunCreate, AnalysisRunRead
from app.schemas.report import FinalReport
from app.services.peer_group_service import PeerGroupService
from app.services.product_vision_service import ProductVisionService
from app.services.report_exporter import ReportExporter
from app.statistics.contracts import StatisticsProvider
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
        statistics_provider: StatisticsProvider | None = None,
    ) -> None:
        self.products = SqlAlchemyProductRepository(session)
        self.analyses = SqlAlchemyAnalysisRepository(session)
        self.knowledge_store = knowledge_store
        self.exporter = ReportExporter(report_dir)
        self.settings = settings
        self.statistics_provider = statistics_provider

    def start(self, payload: AnalysisRunCreate) -> AnalysisRunRead:
        if payload.data_mode is DataMode.REAL:
            if not self.settings.real_model_configured:
                raise LLMNotConfiguredError()
            if not self.settings.rag_use_chroma:
                raise ScaffoldOnlyError("real")
        if payload.data_mode is DataMode.MOCK:
            raise ScaffoldOnlyError("mock")
        product = self.products.get(payload.product_id)
        peer_context = None
        vision_analysis = None
        if payload.data_mode is DataMode.REAL:
            vision_analysis = ProductVisionService(session=self.products.session).analyze_if_available(product)
            peer_context = PeerGroupService(
                session=self.products.session,
                knowledge_store=self.knowledge_store,
                settings=self.settings,
            ).build_context(product, vision_summary=vision_analysis.summary if vision_analysis else "")
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
            statistics_provider=self.statistics_provider,
            persist_callback=persist,
        )
        state = TradePilotState(
            task_id=run.run_id,
            run_id=run.run_id,
            session_id=payload.session_id or str(uuid4()),
            thread_id=payload.thread_id or str(uuid4()),
            data_mode=payload.data_mode,
            product_profile=product,
            retrieval_scope=(
                RetrievalScope.PEER_GROUP if peer_context is not None else RetrievalScope.EXACT_PRODUCT
            ),
            peer_group_id=peer_context.peer_group_id if peer_context else None,
            selected_peer_products=peer_context.selected_peer_products if peer_context else [],
            selected_parent_asins=peer_context.selected_parent_asins if peer_context else [],
            review_sample_scope=(
                {
                    "peer_group_id": peer_context.peer_group_id,
                    "selected_parent_asins": peer_context.selected_parent_asins,
                    "review_count": peer_context.review_count,
                }
                if peer_context
                else {}
            ),
            match_method=peer_context.match_method if peer_context else "",
            match_limitations=peer_context.match_limitations if peer_context else [],
            data_gaps=peer_context.match_data_gaps if peer_context else [],
            vision_analysis=vision_analysis.model_dump(mode="json") if vision_analysis else None,
            peer_selection_metadata=(
                {
                    "prefilter_count": peer_context.prefilter_count,
                    "rerank_count": peer_context.rerank_count,
                    "excluded_accessory_count": peer_context.excluded_accessory_count,
                    "match_duration_ms": peer_context.match_duration_ms,
                    "review_read_duration_ms": peer_context.review_read_duration_ms,
                    "total_duration_ms": peer_context.total_duration_ms,
                    "documents_ingested": peer_context.documents_ingested,
                    "database_persist_duration_ms": peer_context.database_persist_duration_ms,
                    "rag_document_build_duration_ms": peer_context.rag_document_build_duration_ms,
                    "rag_ingest_duration_ms": peer_context.rag_ingest_duration_ms,
                    "peer_group_service_total_duration_ms": (
                        peer_context.peer_group_service_total_duration_ms
                    ),
                    "peer_product_count": len(peer_context.selected_parent_asins),
                    "insufficient_peer_products": any(
                        gap.code == "insufficient_peer_products" for gap in peer_context.match_data_gaps
                    ),
                    **peer_context.match_metadata,
                }
                if peer_context
                else {}
            ),
            target_market=payload.target_market or product.target_market,
            user_constraints=payload.user_constraints,
        )
        try:
            workflow.invoke(state)
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
            failed_state = state.model_dump(mode="json")
            failed_state["error"] = error
            self.analyses.update_run(
                run.run_id,
                status=RunStatus.FAILED,
                current_node="workflow_failed",
                retry_count=state.retry_count,
                state=failed_state,
            )
            raise TradePilotError(
                code=ErrorCode.WORKFLOW_FAILED,
                message="Analysis workflow failed; no Demo/Mock fallback was used",
                status_code=500,
                details=[{"run_id": run.run_id, "error_type": type(exc).__name__}],
            ) from exc
        return self.analyses.get_run(run.run_id)

    def get_run(self, run_id: str) -> AnalysisRunRead:
        return self.analyses.get_run(run_id)

    def list_agent_outputs(self, run_id: str):  # type: ignore[no-untyped-def]
        self.analyses.get_run(run_id)
        return self.analyses.list_agent_outputs(run_id)

    def get_report(self, report_id: str) -> FinalReport:
        return self.analyses.get_report(report_id)
