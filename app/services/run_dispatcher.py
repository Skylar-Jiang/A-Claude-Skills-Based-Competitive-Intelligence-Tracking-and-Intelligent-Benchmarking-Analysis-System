import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import DataMode, RunStageStatus, RunStatus
from app.core.exceptions import TradePilotError
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository
from app.rag.in_memory import InMemoryKnowledgeStore
from app.schemas.analysis import AnalysisRunCreate
from app.services.analysis_service import AnalysisService, validate_real_readiness

logger = logging.getLogger(__name__)


class RunDispatcher:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        knowledge_store_factory: Any,
        settings: Any,
        statistics_provider_factory: Any,
        background_registry: Any,
        demo_knowledge_store_factory: Any | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.knowledge_store_factory = knowledge_store_factory
        self.settings = settings
        self.statistics_provider_factory = statistics_provider_factory
        self.background_registry = background_registry
        self.demo_knowledge_store_factory = demo_knowledge_store_factory or InMemoryKnowledgeStore
        self.executor = ThreadPoolExecutor(
            max_workers=settings.run_worker_count,
            thread_name_prefix="tradepilot-run",
        )
        self._futures: set[Future[None]] = set()
        self._lock = Lock()

    def submit(self, run_id: str) -> None:
        future = self.executor.submit(self._execute, run_id)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._discard)

    def recover_pending(self) -> int:
        with self.session_factory() as session:
            run_ids = SqlAlchemyAnalysisRepository(session).list_run_ids({RunStatus.PENDING})
        for run_id in run_ids:
            self.submit(run_id)
        if run_ids:
            logger.info("recovered pending analysis runs", extra={"run_count": len(run_ids)})
        return len(run_ids)

    def _execute(self, run_id: str) -> None:
        with self.session_factory() as session:
            repository = SqlAlchemyAnalysisRepository(session)
            try:
                payload = AnalysisRunCreate.model_validate(repository.get_run_request(run_id))
                if payload.data_mode is DataMode.REAL:
                    validate_real_readiness(self.settings)
                knowledge_store = (
                    self.demo_knowledge_store_factory()
                    if payload.data_mode is DataMode.DEMO
                    else self.knowledge_store_factory()
                )
                service = AnalysisService(
                    session=session,
                    knowledge_store=knowledge_store,
                    report_dir=self.settings.report_dir,
                    settings=self.settings,
                    statistics_provider=self.statistics_provider_factory(session),
                    background_registry=self.background_registry,
                )
                service.execute(run_id)
            except Exception as exc:
                session.rollback()
                run = repository.get_run(run_id)
                persisted_error = run.state.get("error")
                error = (
                    persisted_error
                    if isinstance(persisted_error, dict)
                    else self._serialize_error(exc)
                )
                running_stage = next(
                    (
                        stage
                        for stage in repository.list_stages(run_id)
                        if stage.status is RunStageStatus.RUNNING
                    ),
                    None,
                )
                failed_stage_key = running_stage.stage_key if running_stage is not None else None
                if failed_stage_key is not None:
                    try:
                        repository.transition_stage(
                            run_id,
                            failed_stage_key,
                            RunStageStatus.FAILED,
                            error=error,
                        )
                        repository.append_event(
                            run_id,
                            event_type="stage_failed",
                            stage_key=failed_stage_key,
                            payload={"status": RunStageStatus.FAILED.value, "error_type": error.get("type")},
                        )
                    except Exception:
                        session.rollback()
                elif run.current_node == "created":
                    try:
                        repository.transition_stage(
                            run_id,
                            "product_preparation",
                            RunStageStatus.FAILED,
                            error=error,
                        )
                    except Exception:
                        session.rollback()
                state = {
                    **run.state,
                    "error": error,
                    "fallback_used": False,
                }
                repository.update_run(
                    run_id,
                    status=RunStatus.FAILED,
                    current_node="workflow_failed",
                    retry_count=run.retry_count,
                    state=state,
                )
                repository.append_event(
                    run_id,
                    event_type="workflow_failed",
                    payload={"error_type": error.get("type", type(exc).__name__), "fallback_used": False},
                )

    @staticmethod
    def _serialize_error(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, TradePilotError):
            return {
                "type": type(exc).__name__,
                "code": exc.code.value,
                "message": exc.message,
                "details": exc.details,
            }
        return {"type": type(exc).__name__, "message": str(exc)}

    def _discard(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)
        try:
            error = future.exception()
        except Exception:
            logger.exception("analysis worker future inspection failed")
            return
        if error is not None:
            logger.error(
                "analysis worker terminated unexpectedly",
                extra={"error_type": type(error).__name__},
                exc_info=(type(error), error, error.__traceback__),
            )

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)
