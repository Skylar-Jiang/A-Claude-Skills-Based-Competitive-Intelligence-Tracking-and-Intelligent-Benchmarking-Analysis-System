"""OpenAI-compatible LLM client with model layering."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


class LLMConfigurationError(RuntimeError):
    """Raised when the OpenAI-compatible client is not configured."""


@dataclass(frozen=True)
class ModelConfig:
    api_key: str
    base_url: str
    model_fast: str
    model_analysis: str
    model_report: str
    temperature: float = 0.0

    @classmethod
    def from_env(cls) -> "ModelConfig":
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise LLMConfigurationError("OPENAI_API_KEY or DEEPSEEK_API_KEY is empty. Please configure .env first.")

        base_url = (
            os.getenv("OPENAI_BASE_URL", "").strip()
            or os.getenv("DEEPSEEK_BASE_URL", "").strip()
            or "https://api.siliconflow.com/v1"
        )

        return cls(
            api_key=api_key,
            base_url=base_url,
            model_fast=os.getenv("MODEL_FAST", "deepseek-ai/DeepSeek-V4-Pro").strip(),
            model_analysis=os.getenv("MODEL_ANALYSIS", "deepseek-ai/DeepSeek-V4-Pro").strip(),
            model_report=os.getenv("MODEL_REPORT", "deepseek-ai/DeepSeek-V4-Pro").strip(),
            temperature=float(os.getenv("MODEL_TEMPERATURE", "0.0")),
        )

    def model_for_role(self, role: str) -> str:
        return {
            "fast": self.model_fast,
            "analysis": self.model_analysis,
            "report": self.model_report,
        }.get(role, self.model_analysis)


class OpenAICompatibleLLM:
    """Small wrapper used by agents, RAG chains, and tests."""

    def __init__(self, config: ModelConfig | None = None):
        self.config = config or ModelConfig.from_env()
        self.client = OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)

    def chat(self, system_prompt: str, user_prompt: str, role: str = "analysis", max_tokens: int = 1200) -> str:
        response = self.client.chat.completions.create(
            model=self.config.model_for_role(role),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.config.temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def chat_json(
        self,
        system_prompt: str,
        payload: dict[str, Any],
        role: str = "analysis",
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        content = self.chat(
            system_prompt=system_prompt,
            user_prompt=json.dumps(payload, ensure_ascii=False),
            role=role,
            max_tokens=max_tokens,
        )
        return parse_json_object(content)


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse a model JSON object and tolerate fenced or prefixed output."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Model did not return a JSON object: {content[:200]}")
    return json.loads(text[start : end + 1])
