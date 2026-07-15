from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import AgentStatus, DataOrigin, KnowledgeType
from app.rag.contracts import KnowledgeStore
from app.rag.filters import build_metadata_filter, relaxed_filters
from app.rag.query_builder import BuiltQuery, build_product_queries, build_review_queries
from app.rag.reranker import Reranker
from app.rag.sufficiency import assess_evidence_sufficiency
from app.schemas.common import DataGap
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductProfile


@dataclass(slots=True)
class RetrievalBundle:
    original_query: str
    rewritten_queries: list[str]
    executed_queries: list[str]
    collection: str
    filters: dict[str, Any]
    evidence: list[EvidenceReference]
    fetched_count: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    sufficient: bool
    insufficiency_reasons: list[str] = field(default_factory=list)
    missing_evidence_types: list[str] = field(default_factory=list)
    rerank_requested: bool = False
    rerank_used: bool = False
    rerank_fallback: bool = False
    rerank_fallback_reason: str | None = None
    latency_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> AgentStatus:
        return AgentStatus.SUCCEEDED if self.sufficient else AgentStatus.INSUFFICIENT_EVIDENCE

    def data_gaps(self, field: str) -> list[DataGap]:
        return [
            DataGap(code="rag_insufficient_evidence", field=field, reason=reason, required_for="agent analysis")
            for reason in self.insufficiency_reasons
        ]


class RetrievalPipeline:
    def __init__(
        self,
        store: KnowledgeStore,
        *,
        settings: Settings | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self.reranker = reranker or Reranker(self.settings)

    def retrieve_product_evidence(
        self,
        profile: ProductProfile,
        constraints: dict[str, Any] | None = None,
        *,
        deep: bool = False,
    ) -> RetrievalBundle:
        query = build_product_queries(profile, constraints)
        return self._retrieve(profile, KnowledgeType.PRODUCT_KNOWLEDGE, query, constraints or {}, deep=deep)

    def retrieve_review_evidence(
        self,
        profile: ProductProfile,
        constraints: dict[str, Any] | None = None,
        *,
        deep: bool = False,
    ) -> RetrievalBundle:
        query = build_review_queries(profile, constraints)
        return self._retrieve(profile, KnowledgeType.REVIEW_INSIGHT, query, constraints or {}, deep=deep)

    def _retrieve(
        self,
        profile: ProductProfile,
        knowledge_type: KnowledgeType,
        built_query: BuiltQuery,
        constraints: dict[str, Any],
        *,
        deep: bool,
    ) -> RetrievalBundle:
        started = time.perf_counter()
        collection = self._collection_name(knowledge_type)
        where = build_metadata_filter(profile, knowledge_type, constraints, strict=True)
        fetched: list[EvidenceReference] = []
        warnings: list[str] = []
        errors: list[str] = []
        executed = []
        for candidate_filter in relaxed_filters(where):
            executed_query = built_query.original_query
            executed.append(executed_query)
            try:
                fetched = self._recall(
                    query=executed_query,
                    profile=profile,
                    knowledge_type=knowledge_type,
                    where=candidate_filter,
                    fetch_k=self._fetch_k(knowledge_type),
                )
            except Exception as exc:
                errors.append(str(exc))
                fetched = []
            if fetched:
                where = candidate_filter
                if candidate_filter != build_metadata_filter(profile, knowledge_type, constraints, strict=True):
                    warnings.append("metadata_filter_relaxed")
                break
        scored = [
            item
            for item in fetched
            if float(item.metadata.get("vector_score", item.metadata.get("retrieval_score", 0.0)) or 0.0)
            >= self.settings.rag_score_threshold
        ]
        deduped, duplicate_count = self._deduplicate(scored)
        diversified = self._diversify(deduped, self.settings.rag_top_k)
        rerank_requested = self._should_rerank(knowledge_type, deep, len(deduped))
        rerank_used = rerank_fallback = False
        rerank_fallback_reason = None
        if rerank_requested and deduped:
            reranked, summary = self.reranker.rerank(
                built_query.original_query,
                [
                    {
                        "id": item.evidence_id,
                        "document": item.excerpt,
                        "metadata": item.metadata,
                        "score": item.metadata.get("vector_score", item.metadata.get("retrieval_score", 0.0)),
                        "vector_score": item.metadata.get("vector_score", item.metadata.get("retrieval_score", 0.0)),
                    }
                    for item in deduped[: self.settings.rerank_max_candidates]
                ],
                top_n=self.settings.rag_top_k,
            )
            rerank_used = summary.used
            rerank_fallback = summary.fallback
            rerank_fallback_reason = summary.error
            if summary.used:
                by_id = {item.evidence_id: item for item in deduped}
                diversified = []
                for candidate in reranked:
                    evidence = by_id.get(str(candidate["id"]))
                    if not evidence:
                        continue
                    metadata = {
                        **evidence.metadata,
                        "rerank_score": candidate.get("rerank_score"),
                        "rerank_model": self.reranker.model_name,
                        "rerank_used": True,
                        "vector_score": candidate.get("vector_score"),
                    }
                    diversified.append(evidence.model_copy(update={"metadata": metadata}))
                diversified = self._diversify(diversified, self.settings.rag_top_k)
            elif summary.error:
                warnings.append(f"rerank_fallback:{summary.error}")
        sufficiency = assess_evidence_sufficiency(
            profile=profile,
            knowledge_type=knowledge_type,
            evidence=diversified,
            min_evidence=self._min_evidence(knowledge_type),
        )
        return RetrievalBundle(
            original_query=built_query.original_query,
            rewritten_queries=[],
            executed_queries=executed,
            collection=collection,
            filters=where,
            evidence=diversified,
            fetched_count=len(fetched),
            accepted_count=len(diversified),
            rejected_count=max(0, len(fetched) - len(diversified)),
            duplicate_count=duplicate_count,
            sufficient=sufficiency.sufficient,
            insufficiency_reasons=sufficiency.reasons,
            missing_evidence_types=sufficiency.missing_evidence_types,
            rerank_requested=rerank_requested,
            rerank_used=rerank_used,
            rerank_fallback=rerank_fallback,
            rerank_fallback_reason=rerank_fallback_reason,
            latency_ms=(time.perf_counter() - started) * 1000,
            warnings=[*warnings, *sufficiency.warnings],
            errors=errors,
        )

    def _recall(
        self,
        *,
        query: str,
        profile: ProductProfile,
        knowledge_type: KnowledgeType,
        where: dict[str, Any],
        fetch_k: int,
    ) -> list[EvidenceReference]:
        if hasattr(self.store, "retrieve_raw"):
            evidence = self.store.retrieve_raw(  # type: ignore[attr-defined]
                query=query,
                product_id=profile.product_id,
                knowledge_type=knowledge_type,
                top_k=fetch_k,
                filters=where,
                fetch_k=fetch_k,
                evidence_id_prefix=self._evidence_prefix(knowledge_type),
            )
            return [self._normalize_id(item, knowledge_type) for item in evidence]
        result = self.store.retrieve(
            query=query,
            product_id=profile.product_id,
            knowledge_type=knowledge_type,
            top_k=fetch_k,
        )
        return [self._normalize_id(item, knowledge_type) for item in result.evidence]

    def _collection_name(self, knowledge_type: KnowledgeType) -> str:
        return getattr(self.store, "collection_names", {}).get(knowledge_type, knowledge_type.value)

    def _fetch_k(self, knowledge_type: KnowledgeType) -> int:
        if knowledge_type is KnowledgeType.PRODUCT_KNOWLEDGE:
            return self.settings.rag_product_fetch_k or self.settings.rag_fetch_k
        return self.settings.rag_review_fetch_k or self.settings.rag_fetch_k

    def _min_evidence(self, knowledge_type: KnowledgeType) -> int:
        if knowledge_type is KnowledgeType.PRODUCT_KNOWLEDGE:
            return self.settings.rag_min_product_evidence
        return self.settings.rag_min_review_evidence

    def _should_rerank(self, knowledge_type: KnowledgeType, deep: bool, candidate_count: int) -> bool:
        if candidate_count < self.settings.rerank_min_candidates:
            return False
        if not (self.settings.rerank_enabled or deep):
            return False
        if knowledge_type is KnowledgeType.PRODUCT_KNOWLEDGE:
            return self.settings.rerank_product_enabled or deep
        return self.settings.rerank_review_enabled or deep

    def _deduplicate(self, evidence: list[EvidenceReference]) -> tuple[list[EvidenceReference], int]:
        seen: set[str] = set()
        selected: list[EvidenceReference] = []
        duplicate_count = 0
        for item in evidence:
            keys = [
                item.evidence_id,
                str(item.metadata.get("document_id") or ""),
                str(item.metadata.get("review_id") or ""),
                str(item.metadata.get("content_hash") or ""),
            ]
            keys = [key for key in keys if key]
            if any(key in seen for key in keys):
                duplicate_count += 1
                continue
            seen.update(keys)
            selected.append(item)
        return selected, duplicate_count

    def _diversify(self, evidence: list[EvidenceReference], top_k: int) -> list[EvidenceReference]:
        selected: list[EvidenceReference] = []
        source_counts: dict[str, int] = {}
        for item in evidence:
            source = str(item.metadata.get("source_file") or item.source_name)
            if source_counts.get(source, 0) >= self.settings.rag_max_per_source:
                continue
            selected.append(item)
            source_counts[source] = source_counts.get(source, 0) + 1
            if len(selected) >= top_k:
                break
        return selected

    def _normalize_id(self, item: EvidenceReference, knowledge_type: KnowledgeType) -> EvidenceReference:
        if item.evidence_id.startswith("RAG-"):
            return item
        return item.model_copy(update={"evidence_id": f"{self._evidence_prefix(knowledge_type)}{item.evidence_id}"})

    @staticmethod
    def _evidence_prefix(knowledge_type: KnowledgeType) -> str:
        return "RAG-PRODUCT-" if knowledge_type is KnowledgeType.PRODUCT_KNOWLEDGE else "RAG-REVIEW-"


def user_provided_evidence(profile: ProductProfile) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"USER-PROVIDED-{profile.product_id}",
        evidence_type="user_provided",
        knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
        source_name="user_input",
        excerpt=profile.model_dump_json(exclude={"data_gaps"}),
        data_origin=DataOrigin.USER,
        is_demo=False,
        metadata={"product_id": profile.product_id, "source": "user_provided"},
    )
