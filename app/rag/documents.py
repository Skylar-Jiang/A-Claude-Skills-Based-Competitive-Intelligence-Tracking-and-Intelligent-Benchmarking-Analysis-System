from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.enums import DataOrigin, KnowledgeType
from app.rag.contracts import KnowledgeDocument
from app.rag.utils import CHUNK_CONFIG_VERSION, clean_text, content_hash, scalar_metadata, stable_id


@dataclass(slots=True)
class RagChunk:
    chunk_id: str
    document_id: str
    parent_id: str
    chunk_index: int
    content: str
    knowledge_type: KnowledgeType
    product_id: str
    source_name: str
    source_file: str
    source_locator: str
    data_origin: DataOrigin = DataOrigin.REAL
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def hash(self) -> str:
        return content_hash(self.content)

    def to_document(self) -> KnowledgeDocument:
        metadata = {
            **self.metadata,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "parent_id": self.parent_id,
            "chunk_index": self.chunk_index,
            "content_hash": self.hash,
            "source_file": self.source_file,
            "source_locator": self.source_locator,
            "knowledge_type": self.knowledge_type.value,
            "data_origin": self.data_origin.value,
            "is_demo": self.data_origin is DataOrigin.DEMO,
            "chunk_config_version": CHUNK_CONFIG_VERSION,
        }
        return KnowledgeDocument(
            document_id=self.chunk_id,
            product_id=self.product_id,
            knowledge_type=self.knowledge_type,
            content=self.content,
            source_name=self.source_name,
            data_origin=self.data_origin,
            metadata=scalar_metadata(metadata),
        )


def split_product_text(
    *,
    parent_id: str,
    product_id: str,
    source_name: str,
    source_file: Path,
    source_locator: str,
    text: str,
    metadata: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
) -> list[RagChunk]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    paragraphs = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [cleaned]:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= chunk_size:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            end = min(start + chunk_size, len(paragraph))
            chunks.append(paragraph[start:end])
            if end == len(paragraph):
                break
            start = max(end - chunk_overlap, start + 1)
        current = ""
    if current:
        chunks.append(current)
    return [
        RagChunk(
            chunk_id=stable_id("rag-product-chunk", parent_id, index, content_hash(chunk)),
            document_id=stable_id("rag-product-doc", parent_id),
            parent_id=parent_id,
            chunk_index=index,
            content=chunk,
            knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
            product_id=product_id,
            source_name=source_name,
            source_file=str(source_file),
            source_locator=source_locator,
            metadata=metadata,
        )
        for index, chunk in enumerate(chunks)
        if len(chunk) >= 20
    ]


def split_review_text(
    *,
    parent_id: str,
    product_id: str,
    source_name: str,
    source_file: Path,
    source_locator: str,
    text: str,
    metadata: dict[str, Any],
    chunk_size: int,
    chunk_overlap: int,
) -> list[RagChunk]:
    cleaned = clean_text(text)
    if len(cleaned) < 12:
        return []
    if len(cleaned) <= chunk_size:
        parts = [cleaned]
    else:
        paragraphs = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
        parts = []
        current = ""
        for paragraph in paragraphs or [cleaned]:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    parts.append(current)
                start = 0
                while start < len(paragraph):
                    end = min(start + chunk_size, len(paragraph))
                    parts.append(paragraph[start:end])
                    if end == len(paragraph):
                        break
                    start = max(end - chunk_overlap, start + 1)
                current = ""
        if current:
            parts.append(current)
    return [
        RagChunk(
            chunk_id=stable_id("rag-review-chunk", parent_id, index, content_hash(part)),
            document_id=stable_id("rag-review-doc", parent_id),
            parent_id=parent_id,
            chunk_index=index,
            content=part,
            knowledge_type=KnowledgeType.REVIEW_INSIGHT,
            product_id=product_id,
            source_name=source_name,
            source_file=str(source_file),
            source_locator=source_locator,
            metadata=metadata,
        )
        for index, part in enumerate(parts)
        if len(part) >= 12
    ]
