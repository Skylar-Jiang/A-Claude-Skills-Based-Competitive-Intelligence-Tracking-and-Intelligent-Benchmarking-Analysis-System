from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import RunStatus
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository
from app.services.analysis_service import AnalysisService


class RunDispatcher:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        knowledge_store_factory: Any,
        settings: Any,
        statistics_provider_factory: Any,
        background_registry: Any,
    ) -> None:
        self.session_factory = session_factory
        self.knowledge_store_factory = knowledge_store_factory
        self.settings = settings
        self.statistics_provider_factory = statistics_provider_factory
        self.background_registry = background_registry
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

    def _execute(self, run_id: str) -> None:
        with self.session_factory() as session:
            service = AnalysisService(
                session=session,
                knowledge_store=self.knowledge_store_factory(),
                report_dir=self.settings.report_dir,
                settings=self.settings,
                statistics_provider=self.statistics_provider_factory(session),
                background_registry=self.background_registry,
            )
            try:
                service.execute(run_id)
            except Exception as exc:
                session.rollback()
                repository = SqlAlchemyAnalysisRepository(session)
                run = repository.get_run(run_id)
                persisted_error = run.state.get("error")
                error = (
                    persisted_error
                    if isinstance(persisted_error, dict)
                    else {"type": type(exc).__name__, "message": str(exc)}
                )
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

    def _discard(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)
