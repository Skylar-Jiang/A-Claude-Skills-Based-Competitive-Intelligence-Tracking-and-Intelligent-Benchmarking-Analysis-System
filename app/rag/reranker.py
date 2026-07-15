from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings


@dataclass(slots=True)
class RerankSummary:
    used: bool = False
    fallback: bool = False
    error: str | None = None


class Reranker:
    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.rerank_model or ""
        self.base_url = (settings.rerank_base_url or settings.openai_base_url or "").rstrip("/")
        self.api_key = settings.openai_api_key or ""
        self.timeout = settings.rerank_timeout_seconds
        self.max_retries = max(1, settings.rerank_max_retries)
        self.required = settings.rerank_required

    @property
    def configured(self) -> bool:
        return bool(self.model_name and self.base_url and self.api_key)

    def rerank(
        self,
        query: str,
        items: list[dict[str, Any]],
        *,
        top_n: int,
    ) -> tuple[list[dict[str, Any]], RerankSummary]:
        if not self.configured:
            return items, RerankSummary(fallback=True, error="reranker_not_configured")
        documents = [str(item.get("document") or "") for item in items]
        last_error: Exception | None = None
        for _ in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        f"{self.base_url}/rerank",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": self.model_name,
                            "query": query,
                            "documents": documents,
                            "top_n": min(top_n, len(documents)),
                            "return_documents": False,
                        },
                    )
                response.raise_for_status()
                payload = response.json()
                return self._apply_scores(items, payload), RerankSummary(used=True)
            except Exception as exc:
                last_error = exc
        if self.required:
            raise RuntimeError(f"Reranker request failed and RERANK_REQUIRED=true: {last_error}") from last_error
        return items, RerankSummary(fallback=True, error=f"reranker_request_failed: {last_error}")

    @staticmethod
    def _apply_scores(items: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        scored_indices: set[int] = set()
        for result in payload.get("results", []):
            index = int(result.get("index", -1))
            if 0 <= index < len(items):
                item = dict(items[index])
                score = float(result.get("relevance_score", result.get("score", item.get("score", 0.0))))
                item["rerank_score"] = score
                item["score"] = score
                scored.append(item)
                scored_indices.add(index)
        remaining = [item for index, item in enumerate(items) if index not in scored_indices]
        remaining.sort(key=lambda item: float(item.get("vector_score", 0.0)), reverse=True)
        return scored + remaining
