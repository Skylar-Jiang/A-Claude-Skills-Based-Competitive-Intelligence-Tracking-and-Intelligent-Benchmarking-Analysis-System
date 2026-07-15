import json
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import API_ERROR_RESPONSES, success
from app.core.enums import FileType
from app.schemas.analysis import AnalysisRunCreate, AnalysisRunRead, FeedbackCreate
from app.schemas.api import ConversationRead, FeedbackAccepted, HealthRead, KnowledgeRebuildRead
from app.schemas.common import ApiResponse
from app.schemas.product import ProductCreate, ProductFileRead, ProductProfile
from app.schemas.report import FinalReport
from app.services.analysis_service import AnalysisService
from app.services.conversation_service import ConversationService
from app.services.knowledge_service import KnowledgeService
from app.services.product_service import ProductService

router = APIRouter(prefix="/api/v1")
DbSession = Annotated[Session, Depends(get_db)]
UploadedFile = Annotated[UploadFile, File()]
FileTypeForm = Annotated[FileType, Form()]


def analysis_service(request: Request, session: Session) -> AnalysisService:
    return AnalysisService(
        session=session,
        knowledge_store=request.app.state.knowledge_store,
        report_dir=request.app.state.settings.report_dir,
        settings=request.app.state.settings,
        statistics_provider=request.app.state.statistics_provider_factory(session),
    )


@router.get(
    "/health",
    summary="TradePilot health and implementation status",
    response_model=ApiResponse[HealthRead],
    responses=API_ERROR_RESPONSES,
)
def health(request: Request):  # type: ignore[no-untyped-def]
    return success(
        request,
        {"service": "TradePilot", "status": "ok", "implementation_status": "production"},
    )


@router.post(
    "/products",
    status_code=201,
    summary="Create a product profile",
    response_model=ApiResponse[ProductProfile],
    responses=API_ERROR_RESPONSES,
)
def create_product(request: Request, payload: ProductCreate, session: DbSession):  # type: ignore[no-untyped-def]
    product = ProductService(session, request.app.state.settings.upload_dir).create(payload)
    return success(request, product, status_code=201, data_mode=payload.data_mode.value)


@router.get(
    "/products/{product_id}",
    summary="Get a product profile",
    response_model=ApiResponse[ProductProfile],
    responses=API_ERROR_RESPONSES,
)
def get_product(request: Request, product_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    product = ProductService(session, request.app.state.settings.upload_dir).get(product_id)
    return success(request, product, data_mode=product.data_mode.value)


@router.post(
    "/products/{product_id}/files",
    status_code=201,
    summary="Attach a product file",
    response_model=ApiResponse[ProductFileRead],
    responses=API_ERROR_RESPONSES,
)
def add_product_file(
    request: Request,
    product_id: str,
    file: UploadedFile,
    session: DbSession,
    file_type: FileTypeForm = FileType.DOCUMENT,
):  # type: ignore[no-untyped-def]
    result = ProductService(session, request.app.state.settings.upload_dir).add_file(
        product_id,
        file_name=file.filename or "upload.bin",
        content_type=file.content_type or "application/octet-stream",
        content=file.file.read(),
        file_type=file_type,
    )
    return success(request, result, status_code=201)


@router.post(
    "/analysis-runs",
    status_code=201,
    summary="Run a TradePilot analysis workflow",
    response_model=ApiResponse[AnalysisRunRead],
    responses=API_ERROR_RESPONSES,
)
def create_analysis_run(
    request: Request, payload: AnalysisRunCreate, session: DbSession
):  # type: ignore[no-untyped-def]
    run = analysis_service(request, session).start(payload)
    return success(request, run, status_code=201, data_mode=payload.data_mode.value)


@router.get(
    "/analysis-runs/{run_id}",
    summary="Get persisted analysis state",
    response_model=ApiResponse[AnalysisRunRead],
    responses=API_ERROR_RESPONSES,
)
def get_analysis_run(request: Request, run_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    run = analysis_service(request, session).get_run(run_id)
    return success(request, run, data_mode=run.data_mode.value)


@router.get(
    "/analysis-runs/{run_id}/metadata",
    summary="Get workflow, peer-scope, and timing metadata",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def get_analysis_metadata(request: Request, run_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    run = analysis_service(request, session).get_run(run_id)
    keys = (
        "peer_group_id",
        "selected_parent_asins",
        "review_sample_scope",
        "match_method",
        "match_limitations",
        "peer_selection_metadata",
        "workflow_metadata",
        "node_status",
    )
    return success(request, {key: run.state.get(key) for key in keys}, data_mode=run.data_mode.value)


@router.get(
    "/analysis-runs/{run_id}/events",
    summary="Stream persisted Agent and workflow events as SSE",
    responses=API_ERROR_RESPONSES,
)
def stream_analysis_events(request: Request, run_id: str, session: DbSession) -> StreamingResponse:
    service = analysis_service(request, session)
    run = service.get_run(run_id)
    outputs = service.list_agent_outputs(run_id)

    def events() -> Iterator[str]:
        for output in outputs:
            payload = {
                "run_id": run_id,
                "agent_name": output.agent_name,
                "status": output.status.value,
                "started_at": output.started_at.isoformat() if output.started_at else None,
                "completed_at": output.completed_at.isoformat() if output.completed_at else None,
                "duration_ms": output.duration_ms,
            }
            yield f"event: agent_completed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        completed = {
            "run_id": run_id,
            "status": run.status.value,
            "workflow_metadata": run.state.get("workflow_metadata", {}),
        }
        yield f"event: workflow_completed\ndata: {json.dumps(completed, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post(
    "/analysis-runs/{run_id}/feedback",
    status_code=201,
    summary="Store analysis feedback",
    response_model=ApiResponse[FeedbackAccepted],
    responses=API_ERROR_RESPONSES,
)
def add_feedback(
    request: Request,
    run_id: str,
    payload: FeedbackCreate,
    session: DbSession,
):  # type: ignore[no-untyped-def]
    run = analysis_service(request, session).get_run(run_id)
    session_id = str(run.state.get("session_id") or run_id)
    result = ConversationService(session).add_feedback(run_id, session_id, payload.message)
    return success(request, result, status_code=201)


@router.get(
    "/reports/{report_id}",
    summary="Get a structured TradePilot report",
    response_model=ApiResponse[FinalReport],
    responses=API_ERROR_RESPONSES,
)
def get_report(request: Request, report_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    report = analysis_service(request, session).get_report(report_id)
    return success(request, report, data_mode="demo" if report.is_demo else "real")


@router.get(
    "/reports/{report_id}/markdown",
    summary="Get final report Markdown content",
    responses=API_ERROR_RESPONSES,
)
def get_report_markdown(request: Request, report_id: str, session: DbSession) -> PlainTextResponse:
    report = analysis_service(request, session).get_report(report_id)
    return PlainTextResponse(Path(report.markdown_path).read_text(encoding="utf-8"), media_type="text/markdown")


@router.get(
    "/reports/{report_id}/json",
    summary="Get final report JSON content",
    responses=API_ERROR_RESPONSES,
)
def get_report_json(request: Request, report_id: str, session: DbSession) -> JSONResponse:
    report = analysis_service(request, session).get_report(report_id)
    payload = json.loads(Path(report.json_path).read_text(encoding="utf-8"))
    return JSONResponse(content=payload)


@router.post(
    "/knowledge/rebuild",
    summary="Rebuild lightweight knowledge store",
    response_model=ApiResponse[KnowledgeRebuildRead],
    responses=API_ERROR_RESPONSES,
)
def rebuild_knowledge(request: Request, session: DbSession):  # type: ignore[no-untyped-def]
    count = KnowledgeService(session, request.app.state.knowledge_store).rebuild()
    return success(request, {"documents_ingested": count, "implementation_status": "production"})


@router.get(
    "/conversations/{session_id}",
    summary="Get stored feedback conversation",
    response_model=ApiResponse[ConversationRead],
    responses=API_ERROR_RESPONSES,
)
def get_conversation(request: Request, session_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    return success(request, ConversationService(session).get(session_id))
