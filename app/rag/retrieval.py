from dataclasses import dataclass

from app.core.enums import AgentStatus, KnowledgeType
from app.rag.contracts import KnowledgeStore
from app.schemas.common import DataGap
from app.schemas.evidence import EvidenceReference, RetrievalResult
from app.schemas.product import ProductProfile


@dataclass(slots=True)
class RetrievalConfig:
    top_k: int = 8
    fetch_k: int = 30
    score_threshold: float = 0.0


def build_product_query(product: ProductProfile) -> str:
    parts = [
        product.name,
        product.category,
        product.description,
        " ".join(product.features),
        " ".join(product.use_scenarios),
        product.target_market,
    ]
    return " ".join(part for part in parts if part).strip()


def build_review_query(product: ProductProfile) -> str:
    parts = [
        product.name,
        product.category,
        product.target_market,
        "customer reviews pain points benefits usage scenario complaints purchase motivation",
    ]
    return " ".join(part for part in parts if part).strip()


def retrieve_for_product(
    store: KnowledgeStore,
    product: ProductProfile,
    knowledge_type: KnowledgeType,
    *,
    config: RetrievalConfig | None = None,
    query: str | None = None,
    filters: dict[str, object] | None = None,
) -> RetrievalResult:
    resolved = config or RetrievalConfig()
    text_query = query or (
        build_product_query(product)
        if knowledge_type is KnowledgeType.PRODUCT_KNOWLEDGE
        else build_review_query(product)
    )
    try:
        result = store.retrieve(
            query=text_query,
            product_id=product.product_id,
            knowledge_type=knowledge_type,
            top_k=resolved.top_k,
            filters=filters,  # type: ignore[arg-type]
            fetch_k=resolved.fetch_k,  # type: ignore[arg-type]
        )
    except TypeError:
        result = store.retrieve(
            query=text_query,
            product_id=product.product_id,
            knowledge_type=knowledge_type,
            top_k=resolved.top_k,
        )
    if result.status is not AgentStatus.SUCCEEDED:
        return result
    evidence = [
        item
        for item in result.evidence
        if float(item.metadata.get("retrieval_score", 1.0)) >= resolved.score_threshold
    ]
    if not evidence:
        return RetrievalResult(
            status=AgentStatus.INSUFFICIENT_EVIDENCE,
            data_gaps=[
                DataGap(
                    code="low_relevance_rag_evidence",
                    field=knowledge_type.value,
                    reason="No retrieved evidence passed the configured relevance threshold.",
                    required_for="agent analysis",
                )
            ],
        )
    return RetrievalResult(status=AgentStatus.SUCCEEDED, evidence=_diversify(evidence, resolved.top_k))


def _diversify(evidence: list[EvidenceReference], top_k: int) -> list[EvidenceReference]:
    selected: list[EvidenceReference] = []
    seen_reviews: set[str] = set()
    seen_hashes: set[str] = set()
    source_counts: dict[str, int] = {}
    for item in sorted(evidence, key=lambda ev: float(ev.metadata.get("retrieval_score", 0.0)), reverse=True):
        review_id = str(item.metadata.get("review_id") or "")
        content_hash = str(item.metadata.get("content_hash") or "")
        source_file = str(item.metadata.get("source_file") or item.source_name)
        if review_id and review_id in seen_reviews:
            continue
        if content_hash and content_hash in seen_hashes:
            continue
        if source_counts.get(source_file, 0) >= max(2, top_k // 2):
            continue
        selected.append(item)
        if review_id:
            seen_reviews.add(review_id)
        if content_hash:
            seen_hashes.add(content_hash)
        source_counts[source_file] = source_counts.get(source_file, 0) + 1
        if len(selected) >= top_k:
            break
    return selected
