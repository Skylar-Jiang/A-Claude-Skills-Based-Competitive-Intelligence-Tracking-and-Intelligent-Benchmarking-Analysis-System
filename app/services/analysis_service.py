from datetime import date
from pathlib import Path
from threading import Lock
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.background.contracts import BackgroundQuery
from app.background.registry import BackgroundProviderRegistry
from app.core.config import Settings
from app.core.enums import DataMode, ErrorCode, KnowledgeType, RetrievalScope, RunStageStatus, RunStatus
from app.core.exceptions import (
    AnalysisAlreadyRunningError,
    AnalysisCapacityReachedError,
    DataPreparationRequiredError,
    LLMNotConfiguredError,
    ScaffoldOnlyError,
    TradePilotError,
)
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository, SqlAlchemyProductRepository
from app.domain.product_catalog import ProductCatalog
from app.domain.review_lookup import ReviewLookup
from app.rag.contracts import KnowledgeStore
from app.schemas.analysis import AnalysisRunCreate, AnalysisRunRead
from app.schemas.evidence import EvidenceReference
from app.schemas.report import FinalReport
from app.services.peer_group_service import PeerGroupService
from app.services.product_vision_service import ProductVisionService
from app.services.report_exporter import ReportExporter
from app.statistics.contracts import StatisticsProvider
from app.workflows.graph import TradePilotWorkflow
from app.workflows.state import TradePilotState


def _is_git_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as source:
            return source.read(128).startswith(b"version https://git-lfs.github.com/spec/v1")
    except OSError:
        return False


def validate_real_readiness(settings: Settings) -> None:
    if not settings.real_model_configured:
        raise LLMNotConfiguredError()
    if not settings.rag_use_chroma:
        raise DataPreparationRequiredError(
            "real Chroma RAG",
            action="set RAG_USE_CHROMA=true and configure the real retrieval data",
        )

    embedding_model = (settings.embedding_model or "").strip()
    if not embedding_model:
        raise LLMNotConfiguredError("Real mode requires EMBEDDING_MODEL for peer matching and Chroma retrieval")
    if embedding_model.startswith("text-embedding-"):
        if not settings.qwen_api_key:
            raise LLMNotConfiguredError(
                f"Real mode embedding model {embedding_model} requires QWEN_API_KEY"
            )
    elif not settings.openai_api_key:
        raise LLMNotConfiguredError(
            f"Real mode embedding model {embedding_model} requires OPENAI_API_KEY"
        )

    source_paths = (
        (settings.peer_metadata_path, "product metadata"),
        (settings.peer_reviews_path, "review data"),
    )
    for source_path, label in source_paths:
        if not source_path.is_file():
            raise DataPreparationRequiredError(
                f"{label} source",
                action="download the peer source data, then run python scripts/prepare_peer_data.py",
            )
        if _is_git_lfs_pointer(source_path):
            raise DataPreparationRequiredError(
                f"{label} source",
                action="run git lfs pull, then run python scripts/prepare_peer_data.py",
            )

    ProductCatalog.open_prepared(
        settings.peer_metadata_path,
        settings.peer_cache_dir / "product_catalog.sqlite",
    )
    ReviewLookup.open_prepared(
        settings.peer_reviews_path,
        settings.peer_cache_dir / "review_lookup.sqlite",
    )


class AnalysisService:
    STAGE_KEYS = [
        "product_preparation",
        "image_understanding",
        "peer_matching",
        "rag_preparation",
        "statistics",
        "product_market_agent",
        "user_insight_agent",
        "operations_decision_agent",
        "evidence_audit_agent",
        "report_export",
    ]

    def __init__(
        self,
        *,
        session: Session,
        knowledge_store: KnowledgeStore,
        report_dir: Path,
        settings: Settings,
        statistics_provider: StatisticsProvider | None = None,
        background_registry: BackgroundProviderRegistry | None = None,
    ) -> None:
        self.products = SqlAlchemyProductRepository(session)
        self.analyses = SqlAlchemyAnalysisRepository(session)
        self.knowledge_store = knowledge_store
        self.exporter = ReportExporter(report_dir)
        self.settings = settings
        self.statistics_provider = statistics_provider
        self.background_registry = background_registry or BackgroundProviderRegistry()
        self._progress_lock = Lock()
        self._progress_session_factory = sessionmaker(
            bind=session.get_bind(),
            autoflush=False,
            expire_on_commit=False,
        )

    def create(self, payload: AnalysisRunCreate) -> AnalysisRunRead:
        if payload.data_mode is DataMode.REAL:
            validate_real_readiness(self.settings)
        if payload.data_mode is DataMode.MOCK:
            raise ScaffoldOnlyError("mock")
        self.products.get(payload.product_id)
        if self.analyses.has_active_run_for_product(payload.product_id):
            raise AnalysisAlreadyRunningError()
        if self.analyses.count_active_runs() >= self.settings.analysis_max_active_runs:
            raise AnalysisCapacityReachedError()
        run = self.analyses.create_run(payload)
        self.analyses.initialize_stages(run.run_id, self.STAGE_KEYS)
        self.analyses.append_event(
            run.run_id,
            event_type="workflow_created",
            payload={"status": RunStatus.PENDING.value, "data_mode": payload.data_mode.value},
        )
        return run

    def start(self, payload: AnalysisRunCreate) -> AnalysisRunRead:
        run = self.create(payload)
        self.execute(run.run_id)
        return self.analyses.get_run(run.run_id)

    def execute(self, run_id: str) -> AnalysisRunRead:
        payload = AnalysisRunCreate.model_validate(self.analyses.get_run_request(run_id))
        self.analyses.update_run(
            run_id,
            status=RunStatus.RUNNING,
            current_node="product_preparation",
            retry_count=0,
            state={},
        )
        self._stage(run_id, "product_preparation", RunStageStatus.RUNNING)
        product = self.products.get(payload.product_id)
        self._stage(run_id, "product_preparation", RunStageStatus.SUCCEEDED)
        peer_context = None
        vision_analysis = None
        if payload.data_mode is DataMode.REAL:
            self._stage(run_id, "image_understanding", RunStageStatus.RUNNING)
            vision_analysis = ProductVisionService(session=self.products.session).analyze_if_available(product)
            self._stage(run_id, "image_understanding", RunStageStatus.SUCCEEDED)
            self._stage(run_id, "peer_matching", RunStageStatus.RUNNING)
            peer_context = PeerGroupService(
                session=self.products.session,
                knowledge_store=self.knowledge_store,
                settings=self.settings,
                progress_callback=lambda phase: self.analyses.append_event(
                    run_id,
                    event_type=f"peer_{phase}",
                    payload={"stage_key": "peer_matching" if "selection" in phase else "rag_preparation"},
                ),
            ).build_context(product, vision_summary=vision_analysis.summary if vision_analysis else "")
            self._stage(
                run_id,
                "peer_matching",
                RunStageStatus.SUCCEEDED,
                payload={
                    "peer_group_id": peer_context.peer_group_id,
                    "peer_product_count": len(peer_context.selected_parent_asins),
                    "duration_ms": peer_context.match_duration_ms,
                },
            )
            rag_duration_ms = (
                peer_context.database_persist_duration_ms
                + peer_context.rag_document_build_duration_ms
                + peer_context.rag_ingest_duration_ms
            )
            self._stage(
                run_id,
                "rag_preparation",
                RunStageStatus.SUCCEEDED,
                payload={
                    "documents_ingested": peer_context.documents_ingested,
                    "duration_ms": rag_duration_ms,
                },
            )
        else:
            for stage_key in ("image_understanding", "peer_matching", "rag_preparation"):
                self._stage(run_id, stage_key, RunStageStatus.SKIPPED)

        background_context = self.background_registry.query(
            BackgroundQuery(
                product_name=product.name,
                product_type=product.category,
                market=payload.target_market or product.target_market,
                jurisdiction=payload.jurisdiction,
                platform=payload.platform,
                context_types=payload.background_context_types,
                effective_date=payload.effective_date,
                query_date=payload.query_date or date.today(),
                user_constraints=payload.user_constraints,
            ),
            provider_name=payload.background_provider,
        )
        background_evidence = (
            [
                EvidenceReference(
                    evidence_id=item.evidence_id,
                    evidence_type="product_background",
                    knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
                    source_name=item.source_name,
                    source_uri=item.source_uri,
                    excerpt=item.content,
                    data_origin=item.data_origin,
                    is_demo=False,
                    metadata={
                        "source_type": "product_background_provider",
                        "provider": background_context.provider,
                        "context_type": item.context_type,
                        "effective_date": item.effective_date.isoformat() if item.effective_date else None,
                        "jurisdiction": item.jurisdiction,
                        "confidence": item.confidence,
                        "evidence_scope": "product_background",
                        "peer_group_id": peer_context.peer_group_id if peer_context else "",
                    },
                )
                for item in background_context.evidence
            ]
            if background_context
            else []
        )

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
            progress_callback=lambda node, event, details: self._workflow_progress(
                run_id, node, event, details
            ),
        )
        state = TradePilotState(
            task_id=run_id,
            run_id=run_id,
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
            data_gaps=[
                *(peer_context.match_data_gaps if peer_context else []),
                *(background_context.data_gaps if background_context else []),
            ],
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
            background_context=background_context,
            background_evidence=background_evidence,
        )
        try:
            workflow.invoke(state)
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
            failed_state = state.model_dump(mode="json")
            failed_state["error"] = error
            self.analyses.update_run(
                run_id,
                status=RunStatus.FAILED,
                current_node="workflow_failed",
                retry_count=state.retry_count,
                state=failed_state,
            )
            raise TradePilotError(
                code=ErrorCode.WORKFLOW_FAILED,
                message="Analysis workflow failed; no Demo/Mock fallback was used",
                status_code=500,
                details=[{"run_id": run_id, "error_type": type(exc).__name__}],
            ) from exc
        completed = self.analyses.get_run(run_id)
        for stage_key in (
            "statistics",
            "product_market_agent",
            "user_insight_agent",
            "operations_decision_agent",
            "evidence_audit_agent",
            "report_export",
        ):
            stage = next(item for item in self.analyses.list_stages(run_id) if item.stage_key == stage_key)
            if stage.status is RunStageStatus.PENDING:
                self._stage(run_id, stage_key, RunStageStatus.SUCCEEDED)
        self.analyses.append_event(
            run_id,
            event_type="workflow_completed",
            payload={"status": completed.status.value, "report_id": completed.report_id},
        )
        return self.analyses.get_run(run_id)

    def _stage(
        self,
        run_id: str,
        stage_key: str,
        status: RunStageStatus,
        *,
        payload: dict[str, object] | None = None,
    ) -> None:
        if status is RunStageStatus.RUNNING:
            self.analyses.set_current_node(run_id, stage_key)
        stage = self.analyses.transition_stage(run_id, stage_key, status, payload=payload)
        event_type = {
            RunStageStatus.RUNNING: "stage_started",
            RunStageStatus.SUCCEEDED: "stage_completed",
            RunStageStatus.FAILED: "stage_failed",
            RunStageStatus.SKIPPED: "stage_skipped",
            RunStageStatus.PENDING: "stage_pending",
        }[status]
        self.analyses.append_event(
            run_id,
            event_type=event_type,
            stage_key=stage_key,
            payload={
                "status": status.value,
                "duration_ms": stage.duration_ms,
                **(payload or {}),
            },
        )

    def _workflow_progress(
        self,
        run_id: str,
        node_name: str,
        event: str,
        payload: dict[str, object],
    ) -> None:
        stage_key = {
            "statistics_provider": "statistics",
            "product_market_agent": "product_market_agent",
            "user_insight_agent": "user_insight_agent",
            "operations_decision_agent": "operations_decision_agent",
            "evidence_audit_agent": "evidence_audit_agent",
            "persist_and_export": "report_export",
        }.get(node_name)
        if stage_key is None:
            return
        status = {
            "started": RunStageStatus.RUNNING,
            "completed": RunStageStatus.SUCCEEDED,
            "failed": RunStageStatus.FAILED,
        }[event]
        event_prefix = "agent" if stage_key.endswith("_agent") else "stage"
        with self._progress_lock:
            with self._progress_session_factory() as progress_session:
                repository = SqlAlchemyAnalysisRepository(progress_session)
                if status is RunStageStatus.RUNNING:
                    repository.set_current_node(run_id, stage_key)
                repository.transition_stage(
                    run_id,
                    stage_key,
                    status,
                    payload=payload,
                    error=payload if status is RunStageStatus.FAILED else None,
                )
                repository.append_event(
                    run_id,
                    event_type=f"{event_prefix}_{event}",
                    stage_key=stage_key,
                    payload=payload,
                )

    def get_run(self, run_id: str) -> AnalysisRunRead:
        return self.analyses.get_run(run_id)

    def list_agent_outputs(self, run_id: str):  # type: ignore[no-untyped-def]
        self.analyses.get_run(run_id)
        return self.analyses.list_agent_outputs(run_id)

    def list_stages(self, run_id: str):  # type: ignore[no-untyped-def]
        return self.analyses.list_stages(run_id)

    def list_events(self, run_id: str, *, after_event_id: int = 0):  # type: ignore[no-untyped-def]
        return self.analyses.list_events(run_id, after_event_id=after_event_id)

    def list_evidence(self, run_id: str) -> list[dict[str, object]]:
        return self.analyses.list_evidence(run_id)

    def get_evidence(self, run_id: str, evidence_id: str) -> dict[str, object]:
        return self.analyses.get_evidence(run_id, evidence_id)

    def get_report(self, report_id: str) -> FinalReport:
        return self.analyses.get_report(report_id)
