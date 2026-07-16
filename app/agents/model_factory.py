import json
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import Settings, get_settings
from app.core.exceptions import LLMNotConfiguredError

logger = logging.getLogger(__name__)


def redact_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def ensure_analysis_model_config(settings: Settings | None = None) -> Settings:
    resolved = settings or get_settings()
    if not (resolved.deepseek_api_key or resolved.openai_api_key) or not resolved.model_analysis:
        raise LLMNotConfiguredError()
    return resolved


def create_analysis_model(settings: Settings | None = None) -> BaseChatModel:
    resolved = ensure_analysis_model_config(settings)
    logger.info(
        "creating analysis model",
        extra={
            "model_name": resolved.model_analysis,
            "provider": "deepseek" if resolved.deepseek_api_key else "openai-compatible",
        },
    )
    return ChatOpenAI(
        model=resolved.model_analysis,
        base_url=resolved.deepseek_base_url if resolved.deepseek_api_key else resolved.openai_base_url,
        api_key=resolved.deepseek_api_key or resolved.openai_api_key,
        temperature=resolved.model_temperature,
        timeout=resolved.model_timeout_seconds,
        max_retries=resolved.model_max_retries,
        max_tokens=resolved.model_max_tokens,
        model_kwargs={"response_format": {"type": "json_object"}},
        extra_body=_analysis_extra_body(resolved),
    )


def _analysis_extra_body(settings: Settings) -> dict[str, Any] | None:
    """Keep bounded JSON responses free of provider reasoning content."""
    if settings.deepseek_api_key:
        return {"thinking": {"type": "disabled"}}
    base_url = (settings.openai_base_url or "").lower()
    model_name = (settings.model_analysis or "").lower()
    if (
        ("api.minimax.io" in base_url or "api.minimaxi.com" in base_url)
        and model_name.startswith("minimax-m3")
    ):
        return {"thinking": {"type": "disabled"}}
    return None


def create_operations_model(settings: Settings | None = None) -> BaseChatModel:
    resolved = settings or get_settings()
    if not (resolved.qwen_api_key and resolved.model_report):
        if resolved.openai_api_key and resolved.model_analysis:
            return create_analysis_model(resolved)
        raise LLMNotConfiguredError("Real operations Agent requires QWEN_API_KEY and MODEL_REPORT")
    return _create_qwen_model(resolved, resolved.model_report)


def create_audit_model(settings: Settings | None = None) -> BaseChatModel:
    resolved = settings or get_settings()
    if not (resolved.qwen_api_key and resolved.model_fast):
        if resolved.openai_api_key and resolved.model_analysis:
            return create_analysis_model(resolved)
        raise LLMNotConfiguredError("Real evidence audit Agent requires QWEN_API_KEY and MODEL_FAST")
    return _create_qwen_model(resolved, resolved.model_fast)


def create_vision_model(settings: Settings | None = None) -> BaseChatModel:
    resolved = settings or get_settings()
    if not resolved.qwen_api_key:
        raise LLMNotConfiguredError("Real image understanding requires QWEN_API_KEY")
    return _create_qwen_model(resolved, resolved.model_vision or "qwen3-vl-plus")


def _create_qwen_model(settings: Settings, model_name: str) -> BaseChatModel:
    logger.info("creating Qwen model", extra={"model_name": model_name, "provider": "qwen"})
    return ChatOpenAI(
        model=model_name,
        base_url=settings.qwen_base_url,
        api_key=settings.qwen_api_key,
        temperature=settings.model_temperature,
        timeout=settings.model_timeout_seconds,
        max_retries=settings.model_max_retries,
        max_tokens=settings.model_max_tokens,
        model_kwargs={"response_format": {"type": "json_object"}},
        extra_body={"enable_thinking": False},
    )


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Model did not return a JSON object") from exc
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Model JSON output must be an object")
    return value


def normalize_model_data_gaps(payload: dict[str, Any], *, field: str) -> dict[str, Any]:
    payload["data_gaps"] = _normalize_gap_list(payload.get("data_gaps", []), field=field)
    for conclusion in payload.get("conclusions", []):
        if isinstance(conclusion, dict):
            conclusion["data_gaps"] = _normalize_gap_list(
                conclusion.get("data_gaps", []),
                field=field,
            )
    return payload


def normalize_text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_evidence_ids(value: object, *, allowed_ids: set[str]) -> list[str]:
    return [item for item in normalize_text_list(value) if item in allowed_ids]


def _normalize_gap_list(values: object, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        values = [values] if values else []
    normalized = []
    for value in values:
        if isinstance(value, dict):
            normalized.append(value)
        elif isinstance(value, str) and value.strip():
            normalized.append(
                {
                    "code": "model_reported_data_gap",
                    "field": field,
                    "reason": value.strip(),
                    "required_for": "stronger evidence-grounded conclusion",
                }
            )
    return normalized
