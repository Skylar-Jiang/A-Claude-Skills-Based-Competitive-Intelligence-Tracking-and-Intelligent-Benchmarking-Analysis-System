from pathlib import Path
from typing import Any

from app.core.enums import AgentStatus, DataOrigin, KnowledgeType
from app.rag.contracts import KnowledgeDocument
from app.schemas.common import DataGap
from app.schemas.evidence import EvidenceReference, RetrievalResult


class ChromaKnowledgeStore:
    """Minimal Chroma adapter; callers must inject an embedding function."""

    def __init__(self, persist_dir: Path, embedding_function: Any) -> None:
        import chromadb

        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.embedding_function = embedding_function

    def _collection(self, knowledge_type: KnowledgeType):  # type: ignore[no-untyped-def]
        return self.client.get_or_create_collection(
            name=knowledge_type.value,
            embedding_function=self.embedding_function,
        )

    def ingest(self, documents: list[KnowledgeDocument]) -> int:
        grouped: dict[KnowledgeType, list[KnowledgeDocument]] = {}
        for document in documents:
            grouped.setdefault(document.knowledge_type, []).append(document)
        for knowledge_type, items in grouped.items():
            collection = self._collection(knowledge_type)
            collection.upsert(
                ids=[item.document_id for item in items],
                documents=[item.content for item in items],
                metadatas=[
                    {
                        "product_id": item.product_id,
                        "source_name": item.source_name,
                        "source_uri": item.source_uri or "",
                        "data_origin": item.data_origin.value,
                    }
                    for item in items
                ],
            )
        return len(documents)

    def retrieve(
        self,
        *,
        query: str,
        product_id: str,
        knowledge_type: KnowledgeType,
        top_k: int = 5,
    ) -> RetrievalResult:
        result = self._collection(knowledge_type).query(
            query_texts=[query],
            n_results=top_k,
            where={"product_id": product_id},
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        if not ids:
            return RetrievalResult(
                status=AgentStatus.INSUFFICIENT_EVIDENCE,
                data_gaps=[
                    DataGap(
                        code="no_rag_evidence",
                        field=knowledge_type.value,
                        reason="No matching evidence exists in Chroma.",
                        required_for="agent analysis",
                    )
                ],
            )
        evidence = []
        for evidence_id, excerpt, metadata in zip(ids, documents, metadatas, strict=True):
            metadata = metadata or {}
            origin = DataOrigin(metadata["data_origin"])
            evidence.append(
                EvidenceReference(
                    evidence_id=evidence_id,
                    evidence_type="chroma_document",
                    knowledge_type=knowledge_type,
                    source_name=str(metadata.get("source_name", "Chroma")),
                    source_uri=str(metadata.get("source_uri") or "") or None,
                    excerpt=excerpt or "",
                    data_origin=origin,
                    is_demo=origin is DataOrigin.DEMO,
                    metadata={"product_id": product_id},
                )
            )
        return RetrievalResult(status=AgentStatus.SUCCEEDED, evidence=evidence)
