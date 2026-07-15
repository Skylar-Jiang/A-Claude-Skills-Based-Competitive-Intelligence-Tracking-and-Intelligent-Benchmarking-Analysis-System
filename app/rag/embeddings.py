import hashlib
import math
from typing import Any

from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings, get_settings
from app.core.exceptions import LLMNotConfiguredError


class HashEmbedding:
    """Deterministic local embedding for tests, CLI validation, and offline development."""

    def __init__(self, dimensions: int = 128) -> None:
        self.dimensions = dimensions

    @staticmethod
    def name() -> str:
        return "tradepilot-hash-embedding"

    @staticmethod
    def build_from_config(config: dict[str, object]) -> "HashEmbedding":
        return HashEmbedding(dimensions=int(config.get("dimensions", 128)))

    def __call__(self, input: list[str] | str) -> list[list[float]]:  # type: ignore[override]
        if isinstance(input, str):
            return [self._embed(input)]
        return [self._embed(text) for text in input]

    def embed_query(self, input: str | list[str]) -> list[list[float]]:
        if isinstance(input, list):
            return [self._embed(text) for text in input]
        return [self._embed(input)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = -1.0 if digest[4] % 2 else 1.0
            vector[index] += sign
        norm = math.sqrt(sum(item * item for item in vector)) or 1.0
        return [item / norm for item in vector]

    def get_config(self) -> dict[str, object]:
        return {"dimensions": self.dimensions}

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list[str]:
        return ["cosine", "l2", "ip"]


def create_embedding_function(settings: Settings | None = None, *, offline: bool = False) -> Any:
    resolved = settings or get_settings()
    if offline or not resolved.embedding_model:
        return HashEmbedding()
    if not resolved.openai_api_key:
        raise LLMNotConfiguredError()
    return OpenAIEmbeddings(
        model=resolved.embedding_model,
        base_url=resolved.openai_base_url,
        api_key=resolved.openai_api_key,
        timeout=resolved.model_timeout_seconds,
        max_retries=resolved.model_max_retries,
    )
