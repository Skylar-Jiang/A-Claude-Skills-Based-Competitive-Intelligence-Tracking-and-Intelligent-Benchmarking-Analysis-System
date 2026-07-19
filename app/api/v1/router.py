import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import API_ERROR_RESPONSES, success
from app.core.enums import FileType, RunStatus
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository
from app.schemas.analysis import AnalysisRunCreate, AnalysisRunRead, FeedbackCreate
from app.schemas.customer_service import (
    CustomerServiceConversationRead,
    CustomerServiceMessageRequest,
    CustomerServiceMessageResponse,
)
from app.schemas.api import ConversationRead, FeedbackAccepted, HealthRead, KnowledgeRebuildRead
from app.schemas.common import ApiResponse
from app.schemas.product import ProductCreate, ProductFileRead, ProductProfile
from app.schemas.report import FinalReport, ReportRollbackRequest, ReportSupportRequest
from app.services.analysis_service import AnalysisService
from app.services.conversation_service import ConversationService
from app.services.customer_service_agent_service import CustomerServiceAgentService
from app.services.knowledge_service import KnowledgeService
from app.services.product_service import ProductService
from app.services.report_support_service import ReportSupportService
from app.workflows.metadata import agent_frontend_view, workflow_metadata

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
        background_registry=request.app.state.background_registry,
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
    status_code=202,
    summary="Run a TradePilot analysis workflow",
    response_model=ApiResponse[AnalysisRunRead],
    responses=API_ERROR_RESPONSES,
)
def create_analysis_run(
    request: Request, payload: AnalysisRunCreate, session: DbSession
):  # type: ignore[no-untyped-def]
    run = analysis_service(request, session).create(payload)
    request.app.state.run_dispatcher.submit(run.run_id)
    return success(request, run, status_code=202, data_mode=payload.data_mode.value)


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
    "/analysis-runs/{run_id}/timeline",
    summary="Get the persisted workflow stage timeline",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def get_analysis_timeline(request: Request, run_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    service = analysis_service(request, session)
    run = service.get_run(run_id)
    stages = [item.model_dump(mode="json") for item in service.list_stages(run_id)]
    return success(
        request,
        {"run_id": run_id, "status": run.status.value, "stages": stages},
        data_mode=run.data_mode.value,
    )


@router.get(
    "/workflow/metadata",
    summary="Get stable workflow nodes, responsibilities, order and edges",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def get_workflow_metadata(request: Request):  # type: ignore[no-untyped-def]
    return success(request, workflow_metadata(request.app.state.settings))


@router.get(
    "/analysis-runs/{run_id}/status",
    summary="Get the current persisted run status",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def get_analysis_status(request: Request, run_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    run = analysis_service(request, session).get_run(run_id)
    return success(
        request,
        {
            "run_id": run.run_id,
            "status": run.status.value,
            "current_node": run.current_node,
            "report_id": run.report_id,
            "error": run.state.get("error"),
        },
        data_mode=run.data_mode.value,
    )


@router.get(
    "/analysis-runs/{run_id}/agents",
    summary="Get persisted Agent outputs and timings",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def get_analysis_agents(request: Request, run_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    service = analysis_service(request, session)
    run = service.get_run(run_id)
    agents = [
        agent_frontend_view(item, run=run, settings=request.app.state.settings)
        for item in service.list_agent_outputs(run_id)
    ]
    return success(request, {"run_id": run_id, "agents": agents}, data_mode=run.data_mode.value)


@router.get(
    "/analysis-runs/{run_id}/peers",
    summary="Get the selected peer products for this analysis group",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def get_analysis_peers(request: Request, run_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    run = analysis_service(request, session).get_run(run_id)
    return success(
        request,
        {
            "run_id": run_id,
            "peer_group_id": run.state.get("peer_group_id"),
            "selected_parent_asins": run.state.get("selected_parent_asins", []),
            "peers": run.state.get("selected_peer_products", []),
        },
        data_mode=run.data_mode.value,
    )


@router.get(
    "/analysis-runs/{run_id}/evidence",
    summary="Get persisted evidence references",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def get_analysis_evidence(request: Request, run_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    service = analysis_service(request, session)
    run = service.get_run(run_id)
    return success(
        request,
        {"run_id": run_id, "evidence": service.list_evidence(run_id)},
        data_mode=run.data_mode.value,
    )


@router.get(
    "/analysis-runs/{run_id}/evidence/{evidence_id}",
    summary="Get one persisted evidence reference",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def get_analysis_evidence_detail(
    request: Request,
    run_id: str,
    evidence_id: str,
    session: DbSession,
):  # type: ignore[no-untyped-def]
    service = analysis_service(request, session)
    run = service.get_run(run_id)
    return success(
        request,
        {"run_id": run_id, "evidence": service.get_evidence(run_id, evidence_id)},
        data_mode=run.data_mode.value,
    )


@router.get(
    "/analysis-runs/{run_id}/audit",
    summary="Get the persisted evidence-audit result",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def get_analysis_audit(request: Request, run_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    run = analysis_service(request, session).get_run(run_id)
    return success(
        request,
        {"run_id": run_id, "audit": run.state.get("audit_result")},
        data_mode=run.data_mode.value,
    )


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
    service.get_run(run_id)
    raw_last_event_id = request.headers.get("last-event-id", "0")
    cursor = int(raw_last_event_id) if raw_last_event_id.isdigit() else 0
    settings = request.app.state.settings
    session_factory = request.app.state.session_factory

    async def events():  # type: ignore[no-untyped-def]
        nonlocal cursor
        heartbeat_at = monotonic()
        while True:
            with session_factory() as poll_session:
                repository = SqlAlchemyAnalysisRepository(poll_session)
                batch = repository.list_events(run_id, after_event_id=cursor)
                run = repository.get_run(run_id)
            for event in batch:
                cursor = event.event_id
                data = {
                    "run_id": run_id,
                    "event_id": event.event_id,
                    "stage_key": event.stage_key,
                    "created_at": event.created_at.isoformat(),
                    **event.payload,
                }
                yield (
                    f"id: {event.event_id}\n"
                    f"event: {event.event_type}\n"
                    f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                )
                heartbeat_at = monotonic()
            terminal = run.status in {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.MANUAL_REVIEW,
            }
            if terminal and not batch:
                return
            if not batch and monotonic() - heartbeat_at >= settings.sse_heartbeat_seconds:
                yield ": heartbeat\n\n"
                heartbeat_at = monotonic()
            if await request.is_disconnected():
                return
            await asyncio.sleep(settings.sse_poll_interval_seconds)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    "/reports/{report_id}/support",
    summary="Explain or locally edit an evidence-grounded report section",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def support_report(
    request: Request,
    report_id: str,
    payload: ReportSupportRequest,
    session: DbSession,
):  # type: ignore[no-untyped-def]
    result = ReportSupportService(session).support(report_id, payload)
    return success(request, result)


@router.post(
    "/reports/{report_id}/customer-service/messages",
    summary="Send one customer-service message about a generated report",
    response_model=ApiResponse[CustomerServiceMessageResponse],
    responses=API_ERROR_RESPONSES,
)
def customer_service_message(
    request: Request,
    report_id: str,
    payload: CustomerServiceMessageRequest,
    session: DbSession,
):  # type: ignore[no-untyped-def]
    result = CustomerServiceAgentService(session).handle_message(report_id, payload)
    return success(request, result.model_dump(mode="json"))


@router.get(
    "/reports/{report_id}/customer-service/conversations/{conversation_id}",
    summary="Get customer-service conversation details for one report",
    response_model=ApiResponse[CustomerServiceConversationRead],
    responses=API_ERROR_RESPONSES,
)
def get_customer_service_conversation(
    request: Request,
    report_id: str,
    conversation_id: str,
    session: DbSession,
):  # type: ignore[no-untyped-def]
    result = CustomerServiceAgentService(session).get_conversation(report_id, conversation_id)
    return success(request, result.model_dump(mode="json"))


@router.get(
    "/reports/{report_id}/versions",
    summary="List immutable report versions",
    response_model=ApiResponse[dict[str, object]],
    responses=API_ERROR_RESPONSES,
)
def list_report_versions(request: Request, report_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    versions = ReportSupportService(session).versions(report_id)
    summaries = [
        {
            "report_id": item.report_id,
            "version": item.version,
            "parent_report_id": item.parent_report_id,
            "changed_section_ids": item.changed_section_ids,
            "created_at": item.created_at.isoformat(),
        }
        for item in versions
    ]
    return success(request, {"run_id": versions[0].run_id, "versions": summaries})


@router.post(
    "/reports/{report_id}/rollback",
    summary="Create a new report version from an immutable historical version",
    response_model=ApiResponse[FinalReport],
    responses=API_ERROR_RESPONSES,
)
def rollback_report(
    request: Request,
    report_id: str,
    payload: ReportRollbackRequest,
    session: DbSession,
):  # type: ignore[no-untyped-def]
    report = ReportSupportService(session).rollback(
        report_id,
        target_version=payload.target_version,
        reason=payload.reason,
    )
    return success(request, report, data_mode="demo" if report.is_demo else "real")


@router.post(
    "/knowledge/rebuild",
    summary="Rebuild lightweight knowledge store",
    response_model=ApiResponse[KnowledgeRebuildRead],
    responses=API_ERROR_RESPONSES,
)
def rebuild_knowledge(request: Request, session: DbSession):  # type: ignore[no-untyped-def]
    count = KnowledgeService(session, request.app.state.knowledge_store_factory()).rebuild()
    return success(request, {"documents_ingested": count, "implementation_status": "production"})


@router.get(
    "/conversations/{session_id}",
    summary="Get stored feedback conversation",
    response_model=ApiResponse[ConversationRead],
    responses=API_ERROR_RESPONSES,
)
def get_conversation(request: Request, session_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    return success(request, ConversationService(session).get(session_id))
