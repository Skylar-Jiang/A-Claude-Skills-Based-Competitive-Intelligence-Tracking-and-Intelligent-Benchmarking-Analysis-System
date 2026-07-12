from __future__ import annotations

import os
from dataclasses import asdict
from typing import Literal
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from modules.analysis_chain import run_evidence_analysis
from modules.agent_core import AgentOrchestrator, registry_snapshot
from modules.dashboard import comparison_data, competitor_summary, list_reports, report_preview, risk_tags_view
from modules.data_loader import fetch_rss, fetch_webpage, load_project_records, save_records_csv
from modules.data_loader import load_csv
from modules.llm_client import LLMConfigurationError, ModelConfig, OpenAICompatibleLLM
from modules.memory_store import (
    append_conversation_message,
    clear_cache,
    clear_conversation,
    read_conversation_messages,
    read_traces,
)
from modules.rag_chain import get_embedding_settings, build_project_index
from modules.report_writer import save_report
from modules.prompts import PRICE_MONITOR_PROMPT
from modules.report_scheduler import ReportSchedule, load_report_schedules, upsert_report_schedule
from modules.scheduler import scheduler_enabled, start_background_collector
from modules.skill_core import get_skill, list_skills, read_skill_traces, run_skill
from modules.source_manager import (
    DataSourceConfig,
    delete_source,
    load_sources,
    read_collection_logs,
    run_collection_job,
    upsert_source,
)
from modules.tools import add_manual_record_tool, ingest_csv_tool, retrieve_evidence_tool, set_project_index

load_dotenv()

app = FastAPI(
    title="生鲜批发采购区域供应源竞品动态追踪与智能对标分析系统",
    description="面向生鲜批发采购场景的区域供应源 Skill + Agent + RAG + 报告生成 API。",
    version="1.0.0",
)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
        error = exc.detail
    else:
        error = {"code": f"http_{exc.status_code}", "message": str(exc.detail)}
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": error},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {"code": "validation_error", "message": "Request validation failed", "details": exc.errors()},
        },
    )


@app.exception_handler(LLMConfigurationError)
async def llm_configuration_error_handler(_: Request, exc: LLMConfigurationError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "success": False,
            "error": {"code": "llm_not_configured", "message": str(exc)},
        },
    )


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("APP_API_KEY", "").strip()
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


class ManualRecordRequest(BaseModel):
    title: str
    content: str
    source_url: str
    competitor: str = ""
    dimension: str = Field(default="general", examples=["price", "new_product", "sentiment"])


class WebIngestRequest(BaseModel):
    url: str
    competitor: str = ""
    dimension: str = "general"


class RSSIngestRequest(WebIngestRequest):
    limit: int = 20


class CSVIngestRequest(BaseModel):
    path: str


class AnalyzeRequest(BaseModel):
    competitor: str = Field(description="区域供应源竞品，例如“山东寿光黄瓜”。")
    question: str = "请基于现有公开数据进行区域供应源竞品动态分析"
    agent: str = Field(default="all", examples=["all", "price_monitor", "new_product", "sentiment"])
    top_k: int = 6
    session_id: str | None = Field(default=None, description="可选会话 ID；传入后会记录 user/assistant 回合。")


class FormalAnalysisRequest(BaseModel):
    competitor: str = Field(description="分析对象，例如“全国农产品批发市场”。")
    question: str = Field(min_length=1, description="必须由真实检索证据回答的问题。")
    mode: Literal["real", "mock"] = "real"
    top_k: int = Field(default=5, ge=1, le=20)


class SkillRunRequest(BaseModel):
    competitor: str = Field(default="山东寿光黄瓜", examples=["山东寿光黄瓜"], description="区域供应源竞品，不是品牌、公司或电商平台。")
    query: str = "分析山东寿光黄瓜相对河北黄瓜和辽宁批发市场黄瓜的批发价波动、异常价差、新批次供应和质量风险"
    question: str = "请基于现有公开证据进行生鲜批发采购区域供应源 Skill 化竞品分析"
    dimensions: list[str] = Field(default_factory=lambda: ["price", "product", "sentiment", "trend"])
    report_type: str = "weekly"
    date_range: dict[str, str] = Field(default_factory=lambda: {"start": "2026-07-01", "end": "2026-07-06"})
    top_k: int = 5
    provider: Literal["mock", "openai"] = Field(default="mock", examples=["mock", "openai"])
    context: dict[str, Any] = Field(default_factory=dict)


class DataSourceRequest(BaseModel):
    source_id: str
    source_type: str = Field(examples=["csv", "rss", "webpage", "forum", "agri_daily"])
    url: str = ""
    urls: list[str] = Field(default_factory=list)
    path: str = ""
    competitor: str = ""
    dimension: str = "general"
    priority: int = 5
    frequency_minutes: int = 1440
    enabled: bool = True
    keywords: list[str] = Field(default_factory=list)
    llm_filter_enabled: bool = True
    notes: str = ""


class ReportScheduleRequest(BaseModel):
    schedule_id: str
    competitor: str
    period: str = Field(default="daily", examples=["daily", "weekly", "monthly"])
    question: str = "请生成标准化竞品态势简报"
    enabled: bool = True


class ConversationMessageRequest(BaseModel):
    role: str = Field(examples=["user", "assistant"])
    content: str


@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def startup_scheduler() -> None:
    start_background_collector()


@app.get("/config")
def read_config(_: None = Depends(verify_api_key)) -> dict[str, Any]:
    try:
        config = ModelConfig.from_env()
    except LLMConfigurationError as exc:
        return {"configured": False, "error": str(exc)}
    return {
        "configured": True,
        "base_url": config.base_url,
        "models": {
            "fast": config.model_fast,
            "analysis": config.model_analysis,
            "report": config.model_report,
        },
        "temperature": config.temperature,
        "rag_embedding": get_embedding_settings(),
    }


@app.get("/agents")
def list_agents(_: None = Depends(verify_api_key)) -> list[dict[str, str]]:
    return registry_snapshot()


@app.get("/skills")
def skills(_: None = Depends(verify_api_key)) -> list[dict[str, Any]]:
    return list_skills()


@app.get("/skills/{skill_name}")
def skill_detail(skill_name: str, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    try:
        return get_skill(skill_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/skills/{skill_name}/run")
def run_single_skill(
    skill_name: str,
    payload: SkillRunRequest,
    _: None = Depends(verify_api_key),
) -> dict[str, Any]:
    try:
        get_skill(skill_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        return run_skill(skill_name, payload.model_dump())
    except LLMConfigurationError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "skill_execution_failed", "message": str(exc)},
        ) from exc


@app.post("/analyze/multi-agent")
def analyze_multi_agent(payload: SkillRunRequest, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    try:
        return run_skill("orchestrator_skill", payload.model_dump())
    except LLMConfigurationError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "analysis_failed", "message": str(exc)},
        ) from exc


@app.post("/report/generate")
def generate_report_from_skill(payload: SkillRunRequest, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    try:
        return run_skill("report_generation_skill", payload.model_dump())
    except LLMConfigurationError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "report_generation_failed", "message": str(exc)},
        ) from exc


@app.get("/logs/skill-trace")
def skill_trace_logs(limit: int = 50, _: None = Depends(verify_api_key)) -> list[dict[str, Any]]:
    return read_skill_traces(limit=limit)


@app.get("/sources")
def list_data_sources(_: None = Depends(verify_api_key)) -> list[dict[str, Any]]:
    return [source.__dict__ for source in load_sources()]


@app.get("/records")
def list_records(
    competitor: str | None = None,
    dimension: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _: None = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    records = load_project_records()
    if competitor:
        records = [record for record in records if record.competitor == competitor]
    if dimension:
        records = [record for record in records if record.dimension == dimension]
    return [asdict(record) for record in records[offset : offset + limit]]


@app.post("/sources")
def save_data_source(payload: DataSourceRequest, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    source = DataSourceConfig(**payload.model_dump())
    return upsert_source(source).__dict__


@app.delete("/sources/{source_id}")
def remove_data_source(source_id: str, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    deleted = delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Data source not found")
    return {"deleted": source_id}


@app.post("/collect/run")
def run_collection(
    force: bool = True,
    use_llm_filter: bool = True,
    _: None = Depends(verify_api_key),
) -> dict[str, Any]:
    return run_collection_job(force=force, use_llm_filter=use_llm_filter)


@app.get("/collect/scheduler")
def collection_scheduler_status(_: None = Depends(verify_api_key)) -> dict[str, Any]:
    return {
        "enabled": scheduler_enabled(),
        "poll_seconds": int(os.getenv("COLLECTION_POLL_SECONDS", "300")),
    }


@app.get("/collect/logs")
def collection_logs(limit: int = 50, _: None = Depends(verify_api_key)) -> list[dict[str, Any]]:
    return read_collection_logs(limit=limit)


@app.post("/ingest/manual")
def ingest_manual(payload: ManualRecordRequest, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    return add_manual_record_tool(**payload.model_dump())


@app.post("/ingest/csv")
def ingest_csv(payload: CSVIngestRequest, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    return ingest_csv_tool(payload.path)


@app.post("/ingest/webpage")
def ingest_webpage(payload: WebIngestRequest, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    try:
        record = fetch_webpage(payload.url, competitor=payload.competitor, dimension=payload.dimension)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Webpage fetch failed: {exc}") from exc
    output_path = "data/raw/webpage_records.csv"
    existing = load_csv(output_path) if os.path.exists(output_path) else []
    path = save_records_csv(existing + [record], output_path)
    build_project_index()
    return {"count": 1, "output_path": str(path), "record_id": record.record_id}


@app.post("/ingest/rss")
def ingest_rss(payload: RSSIngestRequest, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    try:
        records = fetch_rss(
            payload.url,
            competitor=payload.competitor,
            dimension=payload.dimension,
            limit=payload.limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"RSS fetch failed: {exc}") from exc
    output_path = "data/raw/rss_records.csv"
    existing = load_csv(output_path) if os.path.exists(output_path) else []
    path = save_records_csv(existing + records, output_path)
    build_project_index()
    return {"count": len(records), "output_path": str(path)}


@app.post("/rag/rebuild")
def rebuild_rag(_: None = Depends(verify_api_key)) -> dict[str, Any]:
    index = build_project_index()
    set_project_index(index)
    return {
        "chunks": len(index.chunks),
        "vector_store": "Chroma",
        "collection": index.collection.name,
        "embedding": index.embedding_settings,
    }


@app.get("/rag/search")
def search_rag(
    query: str = Query(default="山东寿光黄瓜 河北黄瓜 批发价 到货价 价差 质量风险"),
    dimension: str | None = None,
    competitor: str | None = None,
    top_k: int = 5,
    _: None = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    return retrieve_evidence_tool(query=query, dimension=dimension, top_k=top_k, competitor=competitor)


@app.post("/analysis/run")
def run_formal_analysis(payload: FormalAnalysisRequest, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    try:
        evidence = retrieve_evidence_tool(
            query=f"{payload.competitor} {payload.question}",
            dimension="price",
            top_k=payload.top_k,
            competitor=None,
        )
        if not evidence:
            return run_evidence_analysis(
                None,
                PRICE_MONITOR_PROMPT,
                {"competitor": payload.competitor, "question": payload.question, "evidence": []},
                mode=payload.mode,
            )
        llm = None if payload.mode == "mock" else OpenAICompatibleLLM()
        return run_evidence_analysis(
            llm,
            PRICE_MONITOR_PROMPT,
            {"competitor": payload.competitor, "question": payload.question, "evidence": evidence},
            mode=payload.mode,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "llm_not_configured", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "analysis_failed", "message": str(exc)},
        ) from exc


@app.get("/dashboard/summary")
def dashboard_summary(_: None = Depends(verify_api_key)) -> list[dict[str, Any]]:
    return competitor_summary()


@app.get("/dashboard/comparison")
def dashboard_comparison(_: None = Depends(verify_api_key)) -> dict[str, Any]:
    return comparison_data()


@app.get("/dashboard/risk-tags")
def dashboard_risk_tags(_: None = Depends(verify_api_key)) -> list[dict[str, Any]]:
    return risk_tags_view()


@app.get("/traces")
def agent_traces(limit: int = 50, _: None = Depends(verify_api_key)) -> list[dict[str, Any]]:
    return read_traces(limit=limit)


@app.delete("/memory/cache")
def purge_memory_cache(_: None = Depends(verify_api_key)) -> dict[str, int]:
    return clear_cache()


@app.get("/memory/conversations/{session_id}")
def conversation_memory(session_id: str, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    messages = read_conversation_messages(session_id)
    return {"session_id": session_id, "messages": messages, "message_count": len(messages)}


@app.post("/memory/conversations/{session_id}")
def append_conversation_memory(
    session_id: str,
    payload: ConversationMessageRequest,
    _: None = Depends(verify_api_key),
) -> dict[str, Any]:
    if payload.role not in {"user", "assistant", "system"}:
        raise HTTPException(status_code=400, detail="role must be user, assistant, or system")
    return append_conversation_message(session_id, payload.role, payload.content)


@app.delete("/memory/conversations/{session_id}")
def purge_conversation_memory(session_id: str, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    return clear_conversation(session_id)


@app.get("/reports")
def reports(_: None = Depends(verify_api_key)) -> list[dict[str, Any]]:
    return list_reports()


@app.get("/reports/{report_name}/preview")
def preview_report(report_name: str, _: None = Depends(verify_api_key)) -> dict[str, str]:
    try:
        return report_preview(report_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report not found") from exc


@app.get("/report-schedules")
def report_schedules(_: None = Depends(verify_api_key)) -> list[dict[str, Any]]:
    return [schedule.__dict__ for schedule in load_report_schedules()]


@app.post("/report-schedules")
def save_report_schedule(payload: ReportScheduleRequest, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    schedule = ReportSchedule(**payload.model_dump())
    return upsert_report_schedule(schedule).__dict__


@app.post("/report-schedules/{schedule_id}/run")
def run_report_schedule(schedule_id: str, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    schedules = load_report_schedules()
    for schedule in schedules:
        if schedule.schedule_id != schedule_id:
            continue
        orchestrator = AgentOrchestrator()
        result = orchestrator.run_all(schedule.competitor, schedule.question, top_k=6)
        result["report"] = orchestrator.generate_report(schedule.competitor, result["results"])
        result["report_files"] = save_report(result["report"], schedule.competitor)
        schedule.mark_run()
        upsert_report_schedule(schedule)
        return result
    raise HTTPException(status_code=404, detail="Report schedule not found")


@app.post("/analyze")
def analyze(payload: AnalyzeRequest, _: None = Depends(verify_api_key)) -> dict[str, Any]:
    try:
        if payload.session_id:
            append_conversation_message(payload.session_id, "user", payload.question)
        orchestrator = AgentOrchestrator()
        if payload.agent == "all":
            result = orchestrator.run_all(payload.competitor, payload.question, top_k=payload.top_k)
            result["report"] = orchestrator.generate_report(payload.competitor, result["results"])
            result["report_files"] = save_report(result["report"], payload.competitor)
            attach_conversation_memory(payload.session_id, result)
            return result
        result = orchestrator.run_agent(payload.agent, payload.competitor, payload.question, top_k=payload.top_k)
        attach_conversation_memory(payload.session_id, result)
        return result
    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "llm_not_configured", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "analysis_failed", "message": str(exc)},
        ) from exc


def attach_conversation_memory(session_id: str | None, result: dict[str, Any]) -> None:
    if not session_id:
        return
    assistant_summary = result.get("report", result).get("summary") or result.get("report", result).get(
        "executive_summary",
        "分析结果已生成",
    )
    append_conversation_message(session_id, "assistant", str(assistant_summary))
    messages = read_conversation_messages(session_id)
    result["memory"] = {"session_id": session_id, "message_count": len(messages)}
