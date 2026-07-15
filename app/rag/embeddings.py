import hashlib
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

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


class OpenAICompatibleEmbedding:
    """Concurrent OpenAI-compatible embedding function for Chroma."""

    def __init__(
        self,
        *,
        model_name: str,
        base_url: str | None,
        api_key: str,
        batch_size: int,
        concurrency: int,
        timeout: int,
        max_retries: int,
    ) -> None:
        self.model_name = model_name
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.batch_size = max(1, batch_size)
        self.concurrency = max(1, concurrency)
        self.timeout = timeout
        self.max_retries = max(1, max_retries)

    def __call__(self, input: list[str] | str) -> list[list[float]]:  # type: ignore[override]
        if isinstance(input, str):
            return self.embed_documents([input])
        return self.embed_documents(input)

    def embed_query(self, input: str | list[str]) -> list[list[float]]:
        if isinstance(input, list):
            return self.embed_documents(input)
        return self.embed_documents([input])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        chunks = [texts[index : index + self.batch_size] for index in range(0, len(texts), self.batch_size)]
        if len(chunks) <= 1 or self.concurrency == 1:
            embeddings: list[list[float]] = []
            for chunk in chunks:
                embeddings.extend(self._embed_chunk(chunk))
            return embeddings
        with ThreadPoolExecutor(max_workers=min(self.concurrency, len(chunks))) as executor:
            results = list(executor.map(self._embed_chunk, chunks))
        embeddings: list[list[float]] = []
        for item in results:
            embeddings.extend(item)
        return embeddings

    def _embed_chunk(self, texts: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for _ in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        f"{self.base_url}/embeddings",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={"model": self.model_name, "input": texts},
                    )
                response.raise_for_status()
                payload = response.json()
                data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
                return [item["embedding"] for item in data]
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Embedding request failed after retries: {last_error}") from last_error

    def name(self) -> str:
        return self.model_name

    def get_config(self) -> dict[str, object]:
        return {"model": self.model_name}

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list[str]:
        return ["cosine"]


def create_embedding_function(settings: Settings | None = None, *, offline: bool = False) -> Any:
    resolved = settings or get_settings()
    if offline or not resolved.embedding_model:
        return HashEmbedding()
    if not resolved.openai_api_key:
        raise LLMNotConfiguredError()
    return OpenAICompatibleEmbedding(
        model_name=resolved.embedding_model,
        base_url=resolved.openai_base_url,
        api_key=resolved.openai_api_key,
        batch_size=resolved.rag_embedding_batch_size,
        concurrency=resolved.rag_embedding_concurrency,
        timeout=resolved.model_timeout_seconds,
        max_retries=resolved.model_max_retries,
    )
