from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import success
from app.core.enums import FileType
from app.schemas.analysis import AnalysisRunCreate, FeedbackCreate
from app.schemas.product import ProductCreate
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
    )


@router.get("/health", summary="TradePilot scaffold health")
def health(request: Request):  # type: ignore[no-untyped-def]
    return success(
        request,
        {"service": "TradePilot", "status": "ok", "implementation_status": "scaffold"},
    )


@router.post("/products", status_code=201, summary="Create a product profile")
def create_product(request: Request, payload: ProductCreate, session: DbSession):  # type: ignore[no-untyped-def]
    product = ProductService(session, request.app.state.settings.upload_dir).create(payload)
    return success(request, product, status_code=201, data_mode=payload.data_mode.value)


@router.get("/products/{product_id}", summary="Get a product profile")
def get_product(request: Request, product_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    product = ProductService(session, request.app.state.settings.upload_dir).get(product_id)
    return success(request, product, data_mode=product.data_mode.value)


@router.post("/products/{product_id}/files", status_code=201, summary="Attach a product file")
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


@router.post("/analysis-runs", status_code=201, summary="Run Demo scaffold analysis")
def create_analysis_run(
    request: Request, payload: AnalysisRunCreate, session: DbSession
):  # type: ignore[no-untyped-def]
    run = analysis_service(request, session).start(payload)
    return success(request, run, status_code=201, data_mode=payload.data_mode.value)


@router.get("/analysis-runs/{run_id}", summary="Get persisted analysis state")
def get_analysis_run(request: Request, run_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    run = analysis_service(request, session).get_run(run_id)
    return success(request, run, data_mode=run.data_mode.value)


@router.post("/analysis-runs/{run_id}/feedback", status_code=201, summary="Store scaffold feedback")
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


@router.get("/reports/{report_id}", summary="Get Demo scaffold report")
def get_report(request: Request, report_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    report = analysis_service(request, session).get_report(report_id)
    return success(request, report, data_mode="demo")


@router.post("/knowledge/rebuild", summary="Rebuild lightweight knowledge store")
def rebuild_knowledge(request: Request, session: DbSession):  # type: ignore[no-untyped-def]
    count = KnowledgeService(session, request.app.state.knowledge_store).rebuild()
    return success(request, {"documents_ingested": count, "implementation_status": "scaffold"})


@router.get("/conversations/{session_id}", summary="Get stored feedback conversation")
def get_conversation(request: Request, session_id: str, session: DbSession):  # type: ignore[no-untyped-def]
    return success(request, ConversationService(session).get(session_id))
