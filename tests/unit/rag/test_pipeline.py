from decimal import Decimal

from app.core.config import Settings
from app.core.enums import AgentStatus, DataMode, DataOrigin, KnowledgeType
from app.rag.filters import build_metadata_filter, relaxed_filters
from app.rag.pipeline import RetrievalPipeline
from app.rag.query_builder import build_product_queries, build_review_queries
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductProfile


class FakeStore:
    collection_names = {
        KnowledgeType.PRODUCT_KNOWLEDGE: "product_knowledge",
        KnowledgeType.REVIEW_INSIGHT: "review_insight",
    }

    def __init__(self, evidence: list[EvidenceReference]) -> None:
        self.evidence = evidence

    def clear(self) -> None:
        return None

    def ingest(self, documents):  # type: ignore[no-untyped-def]
        return len(documents)

    def retrieve(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("pipeline should use retrieve_raw when available")

    def retrieve_raw(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.evidence


class FakeReranker:
    model_name = "fake-rerank"

    def rerank(self, query, items, *, top_n):  # type: ignore[no-untyped-def]
        from app.rag.reranker import RerankSummary

        reranked = list(reversed(items[:top_n]))
        for index, item in enumerate(reranked):
            item["rerank_score"] = 1.0 - index / 10
        return reranked, RerankSummary(used=True)


def product() -> ProductProfile:
    return ProductProfile(
        product_id="p1",
        name="Pet stairs",
        category="Pet Supplies",
        description="Foldable stairs for small dogs",
        features=["foldable", "non slip"],
        use_scenarios=["sofa access"],
        target_market="amazon_us",
        target_price=Decimal("29.99"),
        data_mode=DataMode.REAL,
        data_origin=DataOrigin.REAL,
    )


def evidence(item_id: str, *, review_id: str = "", rating: float = 5.0) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=item_id,
        evidence_type="chroma_document",
        knowledge_type=KnowledgeType.REVIEW_INSIGHT if review_id else KnowledgeType.PRODUCT_KNOWLEDGE,
        source_name="fixture",
        excerpt="Feature material durable safe non slip stairs",
        data_origin=DataOrigin.REAL,
        is_demo=False,
        metadata={
            "product_id": "p1",
            "document_id": item_id,
            "review_id": review_id,
            "content_hash": item_id,
            "source_file": f"{item_id}.jsonl",
            "rating": rating,
            "vector_score": 0.9,
            "data_origin": "real",
            "is_demo": False,
        },
    )


def test_query_builders_are_stable_and_not_name_only() -> None:
    profile = product()
    assert build_product_queries(profile) == build_product_queries(profile)
    assert "Pet stairs" not in build_product_queries(profile).original_query
    assert len(build_review_queries(profile).sub_queries) >= 8


def test_metadata_filter_and_relaxation() -> None:
    where = build_metadata_filter(product(), KnowledgeType.REVIEW_INSIGHT, {"rating_min": 2, "verified_purchase": True})
    assert "$and" in where
    assert any("rating" in clause for clause in where["$and"])
    relaxed = relaxed_filters(where)
    assert relaxed[0] == where
    assert any("product_id" in str(item) for item in relaxed)


def test_pipeline_deduplicates_diversifies_and_prefixes_ids() -> None:
    settings = Settings(_env_file=None)
    settings.rag_min_product_evidence = 1
    settings.rag_top_k = 3
    settings.rag_max_per_source = 2
    items = [evidence("a"), evidence("a-dup"), evidence("b")]
    items[1].metadata["content_hash"] = "a"
    bundle = RetrievalPipeline(FakeStore(items), settings=settings).retrieve_product_evidence(product())
    assert bundle.status is AgentStatus.SUCCEEDED
    assert bundle.duplicate_count == 1
    assert all(item.evidence_id.startswith("RAG-PRODUCT-") for item in bundle.evidence)


def test_pipeline_conditional_rerank_preserves_scores() -> None:
    settings = Settings(_env_file=None)
    settings.rerank_enabled = True
    settings.rerank_review_enabled = True
    settings.rerank_min_candidates = 1
    settings.rag_min_review_evidence = 1
    items = [evidence("r1", review_id="r1", rating=1), evidence("r2", review_id="r2", rating=5)]
    bundle = RetrievalPipeline(FakeStore(items), settings=settings, reranker=FakeReranker()).retrieve_review_evidence(
        product()
    )
    assert bundle.rerank_used
    assert bundle.evidence[0].metadata["rerank_score"] is not None
    assert bundle.evidence[0].metadata["vector_score"] is not None
