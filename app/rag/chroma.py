from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.enums import AgentStatus, DataOrigin, KnowledgeType, RetrievalScope
from app.rag.contracts import KnowledgeDocument
from app.schemas.common import DataGap
from app.schemas.evidence import EvidenceReference, RetrievalResult


@dataclass(slots=True)
class ChromaIngestReport:
    attempted: int = 0
    inserted_or_updated: int = 0
    skipped_unchanged: int = 0
    failed: int = 0


class ChromaKnowledgeStore:
    """Persistent two-domain Chroma adapter with scalar metadata and evidence mapping."""

    def __init__(
        self,
        persist_dir: Path,
        embedding_function: Any,
        *,
        collection_names: dict[KnowledgeType, str] | None = None,
        score_threshold: float = 0.0,
    ) -> None:
        import chromadb

        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.embedding_function = embedding_function
        self.collection_names = collection_names or {item: item.value for item in KnowledgeType}
        self.score_threshold = score_threshold

    def _collection(self, knowledge_type: KnowledgeType):  # type: ignore[no-untyped-def]
        return self.client.get_or_create_collection(
            name=self.collection_names[knowledge_type],
            embedding_function=self.embedding_function,
            metadata={
                "hnsw:space": getattr(self.embedding_function, "default_space", lambda: "cosine")(),
                "knowledge_type": knowledge_type.value,
                "embedding_model": getattr(self.embedding_function, "name", lambda: "configured")(),
            },
        )

    def ingest(self, documents: list[KnowledgeDocument]) -> int:
        return self.ingest_with_report(documents).inserted_or_updated

    def ingest_with_report(self, documents: list[KnowledgeDocument]) -> ChromaIngestReport:
        report = ChromaIngestReport(attempted=len(documents))
        grouped: dict[KnowledgeType, list[KnowledgeDocument]] = {}
        for document in documents:
            grouped.setdefault(document.knowledge_type, []).append(document)
        for knowledge_type, items in grouped.items():
            collection = self._collection(knowledge_type)
            ids: list[str] = []
            contents: list[str] = []
            metadatas: list[dict[str, str | int | float | bool]] = []
            existing = collection.get(ids=[item.document_id for item in items], include=["metadatas"])
            existing_hashes = {
                item_id: (metadata or {}).get("content_hash")
                for item_id, metadata in zip(existing.get("ids", []), existing.get("metadatas", []), strict=False)
            }
            for item in items:
                metadata = {
                    **item.metadata,
                    "document_id": item.document_id,
                    "product_id": item.product_id,
                    "source_name": item.source_name,
                    "source_uri": item.source_uri or "",
                    "data_origin": item.data_origin.value,
                    "is_demo": item.data_origin is DataOrigin.DEMO,
                    "knowledge_type": item.knowledge_type.value,
                }
                existing_hash = existing_hashes.get(item.document_id)
                new_hash = metadata.get("content_hash")
                if existing_hash is not None and new_hash is not None and existing_hash == new_hash:
                    report.skipped_unchanged += 1
                    continue
                ids.append(item.document_id)
                contents.append(item.content)
                metadatas.append(metadata)
            if not ids:
                continue
            try:
                collection.upsert(ids=ids, documents=contents, metadatas=metadatas)
                report.inserted_or_updated += len(ids)
            except Exception:
                report.failed += len(ids)
                raise
        return report

    def clear(self) -> None:
        for collection in self.client.list_collections():
            if collection.name in set(self.collection_names.values()):
                self.client.delete_collection(name=collection.name)

    def clear_collection(self, knowledge_type: KnowledgeType) -> None:
        collection_name = self.collection_names[knowledge_type]
        for collection in self.client.list_collections():
            if collection.name == collection_name:
                self.client.delete_collection(name=collection.name)
                return

    def status(self) -> dict[str, dict[str, object]]:
        status: dict[str, dict[str, object]] = {}
        for knowledge_type in KnowledgeType:
            collection = self._collection(knowledge_type)
            status[self.collection_names[knowledge_type]] = {
                "knowledge_type": knowledge_type.value,
                "count": collection.count(),
                "metadata": collection.metadata or {},
            }
        return status

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
    ) -> RetrievalResult:
        if scope is RetrievalScope.PEER_GROUP:
            if not peer_group_id:
                raise ValueError("peer_group_id is required for peer_group retrieval")
            where: dict[str, object] = {"peer_group_id": peer_group_id}
        else:
            where = {"product_id": product_id}
        for key, value in (filters or {}).items():
            if value is not None and value != "":
                where[key] = value
        collection = self._collection(knowledge_type)
        collection_count = collection.count()
        if collection_count == 0:
            return RetrievalResult(
                status=AgentStatus.INSUFFICIENT_EVIDENCE,
                data_gaps=[
                    DataGap(
                        code="no_rag_evidence",
                        field=knowledge_type.value,
                        reason="The Chroma collection is empty.",
                        required_for="agent analysis",
                    )
                ],
            )
        n_results = min(fetch_k or max(top_k, 10), collection_count)
        try:
            result = collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            result = self._fallback_query(collection, query=query, where=where, n_results=n_results)
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
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
        seen_parent_ids: set[str] = set()
        seen_review_ids: set[str] = set()
        for evidence_id, excerpt, metadata, distance in zip(ids, documents, metadatas, distances, strict=True):
            metadata = metadata or {}
            score = max(0.0, 1.0 - float(distance or 0.0))
            if score < self.score_threshold:
                continue
            parent_id = str(metadata.get("parent_id") or metadata.get("document_id") or evidence_id)
            review_id = str(metadata.get("review_id") or "")
            if review_id and review_id in seen_review_ids:
                continue
            if parent_id in seen_parent_ids and len(evidence) >= max(1, top_k // 2):
                continue
            seen_parent_ids.add(parent_id)
            if review_id:
                seen_review_ids.add(review_id)
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
                    metadata={
                        **metadata,
                        "product_id": str(metadata.get("product_id") or product_id),
                        "retrieval_scope": scope.value,
                        **(
                            {"candidate_product_id": product_id, "peer_group_id": peer_group_id}
                            if scope is RetrievalScope.PEER_GROUP
                            else {}
                        ),
                        "collection": self.collection_names[knowledge_type],
                        "retrieval_score": score,
                        "query": query,
                    },
                )
            )
            if len(evidence) >= top_k:
                break
        if not evidence:
            return RetrievalResult(
                status=AgentStatus.INSUFFICIENT_EVIDENCE,
                data_gaps=[
                    DataGap(
                        code="low_relevance_rag_evidence",
                        field=knowledge_type.value,
                        reason="Retrieved Chroma matches were empty after relevance threshold and deduplication.",
                        required_for="agent analysis",
                    )
                ],
            )
        return RetrievalResult(status=AgentStatus.SUCCEEDED, evidence=evidence)

    def retrieve_raw(
        self,
        *,
        query: str,
        product_id: str,
        knowledge_type: KnowledgeType,
        top_k: int = 30,
        filters: dict[str, object] | None = None,
        fetch_k: int | None = None,
        evidence_id_prefix: str = "",
    ) -> list[EvidenceReference]:
        collection = self._collection(knowledge_type)
        collection_count = collection.count()
        if collection_count == 0:
            return []
        where = filters or {"product_id": product_id}
        n_results = min(fetch_k or top_k, collection_count)
        result = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        evidence = []
        for evidence_id, excerpt, metadata, distance in zip(
            result.get("ids", [[]])[0],
            result.get("documents", [[]])[0],
            result.get("metadatas", [[]])[0],
            result.get("distances", [[]])[0],
            strict=False,
        ):
            metadata = metadata or {}
            score = max(0.0, 1.0 - float(distance or 0.0))
            origin = DataOrigin(metadata["data_origin"])
            evidence.append(
                EvidenceReference(
                    evidence_id=f"{evidence_id_prefix}{evidence_id}",
                    evidence_type="chroma_document",
                    knowledge_type=knowledge_type,
                    source_name=str(metadata.get("source_name", "Chroma")),
                    source_uri=str(metadata.get("source_uri") or "") or None,
                    excerpt=(excerpt or "")[:1800],
                    data_origin=origin,
                    is_demo=origin is DataOrigin.DEMO,
                    metadata={
                        **metadata,
                        "product_id": metadata.get("product_id", product_id),
                        "collection": self.collection_names[knowledge_type],
                        "retrieval_score": score,
                        "vector_score": score,
                        "query": query,
                    },
                )
            )
        return evidence

    def _fallback_query(
        self,
        collection,  # type: ignore[no-untyped-def]
        *,
        query: str,
        where: dict[str, object],
        n_results: int,
    ) -> dict[str, list[list[object]]]:
        raw = collection.get(where=where, include=["documents", "metadatas", "embeddings"])
        ids = raw.get("ids", [])
        documents = raw.get("documents", [])
        metadatas = raw.get("metadatas", [])
        embeddings = raw.get("embeddings", [])
        if not ids:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        query_embedding = self._query_embedding(query)
        scored = []
        for item_id, document, metadata, embedding in zip(ids, documents, metadatas, embeddings, strict=False):
            distance = 1.0 - self._cosine(query_embedding, list(embedding or []))
            scored.append((distance, item_id, document, metadata))
        scored.sort(key=lambda item: item[0])
        selected = scored[:n_results]
        return {
            "ids": [[item[1] for item in selected]],
            "documents": [[item[2] for item in selected]],
            "metadatas": [[item[3] for item in selected]],
            "distances": [[item[0] for item in selected]],
        }

    def _query_embedding(self, query: str) -> list[float]:
        if hasattr(self.embedding_function, "embed_query"):
            value = self.embedding_function.embed_query(query)
        else:
            value = self.embedding_function([query])
        if value and isinstance(value[0], list):
            return list(value[0])
        return list(value)

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        limit = min(len(left), len(right))
        dot = sum(left[index] * right[index] for index in range(limit))
        left_norm = sum(value * value for value in left[:limit]) ** 0.5
        right_norm = sum(value * value for value in right[:limit]) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)
