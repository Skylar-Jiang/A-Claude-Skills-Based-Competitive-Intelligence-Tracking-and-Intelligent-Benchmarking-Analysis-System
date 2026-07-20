import logging
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Any

from app.core.enums import AgentStatus, DataOrigin, KnowledgeType, RetrievalScope
from app.rag.contracts import KnowledgeDocument
from app.schemas.common import DataGap
from app.schemas.evidence import EvidenceReference, RetrievalResult

logger = logging.getLogger("tradepilot.rag.chroma")


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
        mmr_enabled: bool = True,
        mmr_lambda: float = 0.7,
        query_max_retries: int = 3,
        query_retry_delay_seconds: float = 0.1,
    ) -> None:
        import chromadb

        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.embedding_function = embedding_function
        self.collection_names = collection_names or {item: item.value for item in KnowledgeType}
        self.score_threshold = score_threshold
        self.mmr_enabled = mmr_enabled
        self.mmr_lambda = mmr_lambda
        self.query_max_retries = query_max_retries
        self.query_retry_delay_seconds = query_retry_delay_seconds

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
        grouped_by_id: dict[KnowledgeType, dict[str, KnowledgeDocument]] = {}
        for document in documents:
            grouped_by_id.setdefault(document.knowledge_type, {})[document.document_id] = document
        for knowledge_type, documents_by_id in grouped_by_id.items():
            items = list(documents_by_id.values())
            collection = self._collection(knowledge_type)
            ids: list[str] = []
            contents: list[str] = []
            metadatas: list[dict[str, str | int | float | bool]] = []
            existing = collection.get(ids=[item.document_id for item in items], include=["metadatas"])
            existing_metadatas = {
                item_id: metadata or {}
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
                existing_metadata = existing_metadatas.get(item.document_id)
                if existing_metadata is not None and existing_metadata == metadata:
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
        result = self._query_with_recovery(
            collection,
            query=query,
            where=where,
            n_results=n_results,
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        raw_embeddings = result.get("embeddings")
        embeddings = raw_embeddings[0] if raw_embeddings is not None and len(raw_embeddings) else []
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
        rows = list(zip(ids, documents, metadatas, distances, embeddings, strict=False))
        selection_strategy = "similarity"
        if self.mmr_enabled and rows and all(
            len(list(row[4]) if row[4] is not None else []) > 0 for row in rows
        ):
            order = self._mmr_order(
                [
                    (
                        str(row[0]),
                        max(0.0, 1.0 - float(row[3] or 0.0)),
                        list(row[4]) if row[4] is not None else [],
                    )
                    for row in rows
                ],
                lambda_mult=self.mmr_lambda,
            )
            position = {item_id: index for index, item_id in enumerate(order)}
            rows.sort(key=lambda row: position[str(row[0])])
            selection_strategy = "mmr"
        evidence = []
        seen_parent_ids: set[str] = set()
        seen_review_ids: set[str] = set()
        for evidence_id, excerpt, metadata, distance, _embedding in rows:
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
                        "selection_strategy": selection_strategy,
                        "mmr_lambda": self.mmr_lambda if selection_strategy == "mmr" else None,
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
            distance = 1.0 - self._cosine(
                query_embedding,
                list(embedding) if embedding is not None else [],
            )
            scored.append((distance, item_id, document, metadata, embedding))
        scored.sort(key=lambda item: item[0])
        selected = scored[:n_results]
        return {
            "ids": [[item[1] for item in selected]],
            "documents": [[item[2] for item in selected]],
            "metadatas": [[item[3] for item in selected]],
            "distances": [[item[0] for item in selected]],
            "embeddings": [[item[4] for item in selected]],
        }

    def _query_with_recovery(
        self,
        collection,  # type: ignore[no-untyped-def]
        *,
        query: str,
        where: dict[str, object],
        n_results: int,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.query_max_retries):
            try:
                return collection.query(
                    query_texts=[query],
                    n_results=n_results,
                    where=where,
                    include=["documents", "metadatas", "distances", "embeddings"],
                )
            except Exception as query_error:
                last_error = query_error
                try:
                    return self._fallback_query(
                        collection,
                        query=query,
                        where=where,
                        n_results=n_results,
                    )
                except Exception as fallback_error:
                    last_error = fallback_error
            if attempt + 1 < self.query_max_retries:
                logger.warning(
                    "chroma_query_retry",
                    extra={
                        "event": "chroma_query_retry",
                        "attempt": attempt + 1,
                        "max_retries": self.query_max_retries,
                        "error_type": type(last_error).__name__,
                    },
                )
                sleep(self.query_retry_delay_seconds * (attempt + 1))
        if last_error is not None:
            raise last_error
        raise RuntimeError("Chroma query failed without an error")

    @staticmethod
    def _mmr_order(
        candidates: list[tuple[str, float, list[float]]],
        *,
        lambda_mult: float,
    ) -> list[str]:
        """Order candidates by maximal marginal relevance using their stored vectors."""
        if not candidates:
            return []
        indexed = list(enumerate(candidates))
        first = max(indexed, key=lambda item: (item[1][1], -item[0]))
        selected = [first]
        remaining = [item for item in indexed if item[0] != first[0]]
        while remaining:
            def mmr_score(item: tuple[int, tuple[str, float, list[float]]]) -> tuple[float, float, int]:
                _, (_, relevance, embedding) = item
                redundancy = max(
                    ChromaKnowledgeStore._cosine(embedding, selected_item[1][2])
                    for selected_item in selected
                )
                score = lambda_mult * relevance - (1 - lambda_mult) * redundancy
                return score, relevance, -item[0]

            chosen = max(remaining, key=mmr_score)
            selected.append(chosen)
            remaining.remove(chosen)
        return [item[1][0] for item in selected]

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
