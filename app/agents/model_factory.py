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
    if not resolved.openai_api_key or not resolved.model_analysis:
        raise LLMNotConfiguredError()
    return resolved


def create_analysis_model(settings: Settings | None = None) -> BaseChatModel:
    resolved = ensure_analysis_model_config(settings)
    logger.info(
        "creating analysis model",
        extra={"model_name": resolved.model_analysis, "base_url": resolved.openai_base_url or "default"},
    )
    return ChatOpenAI(
        model=resolved.model_analysis,
        base_url=resolved.openai_base_url,
        api_key=resolved.openai_api_key,
        temperature=resolved.model_temperature,
        timeout=resolved.model_timeout_seconds,
        max_retries=resolved.model_max_retries,
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
