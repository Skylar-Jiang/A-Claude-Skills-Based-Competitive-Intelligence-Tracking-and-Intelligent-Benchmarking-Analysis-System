from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.responses import failure
from app.api.v1.router import router
from app.core.config import Settings, get_settings
from app.core.exceptions import TradePilotError
from app.db.migrations import upgrade_database
from app.rag.factory import KnowledgeStoreFactory, create_knowledge_store
from app.statistics.factory import StatisticsProviderFactory, create_statistics_provider


def create_app(
    settings: Settings | None = None,
    *,
    knowledge_store_factory: KnowledgeStoreFactory = create_knowledge_store,
    statistics_provider_factory: StatisticsProviderFactory = create_statistics_provider,
) -> FastAPI:
    resolved = settings or get_settings()
    connect_args = {"check_same_thread": False} if resolved.database_url.startswith("sqlite") else {}
    engine = create_engine(resolved.database_url, connect_args=connect_args)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(application: FastAPI):  # type: ignore[no-untyped-def]
        for path in (resolved.upload_dir, resolved.report_dir, resolved.chroma_dir, resolved.chroma_persist_dir):
            Path(path).mkdir(parents=True, exist_ok=True)
        upgrade_database(resolved.database_url)
        application.state.settings = resolved
        application.state.session_factory = session_factory
        application.state.knowledge_store = (
            create_knowledge_store(resolved)
            if knowledge_store_factory is create_knowledge_store
            else knowledge_store_factory()
        )
        application.state.statistics_provider_factory = statistics_provider_factory
        yield
        engine.dispose()

    application = FastAPI(
        title="TradePilot Backend",
        version=resolved.app_version,
        description=(
            "Evidence-grounded peer-group analysis for unlisted pet products, with LCEL Agents, RAG, SQL, SSE, "
            "and Markdown/JSON reports."
        ),
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("X-Request-ID", str(uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(TradePilotError)
    async def tradepilot_error(request: Request, exc: TradePilotError):  # type: ignore[no-untyped-def]
        return failure(
            request,
            status_code=exc.status_code,
            code=exc.code.value,
            message=exc.message,
            details=exc.details,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
        return failure(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details=exc.errors(),
        )

    application.include_router(router)
    return application


app = create_app()
