from typing import Protocol

from pydantic import BaseModel, Field

from app.core.enums import DataOrigin, KnowledgeType, RetrievalScope
from app.schemas.evidence import RetrievalResult


class KnowledgeDocument(BaseModel):
    document_id: str
    product_id: str
    knowledge_type: KnowledgeType
    content: str = Field(min_length=1)
    source_name: str
    source_uri: str | None = None
    data_origin: DataOrigin
    metadata: dict[str, object] = Field(default_factory=dict)


class KnowledgeStore(Protocol):
    def clear(self) -> None: ...

    def ingest(self, documents: list[KnowledgeDocument]) -> int: ...

    def retrieve(
        self,
        *,
        query: str,
        product_id: str,
        knowledge_type: KnowledgeType,
        top_k: int = 5,
        scope: RetrievalScope = RetrievalScope.EXACT_PRODUCT,
        peer_group_id: str | None = None,
        filters: dict[str, object] | None = None,
        fetch_k: int | None = None,
    ) -> RetrievalResult: ...
