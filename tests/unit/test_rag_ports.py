from pathlib import Path

from app.core.enums import AgentStatus, DataOrigin, KnowledgeType, RetrievalScope
from app.rag.chroma import ChromaKnowledgeStore
from app.rag.collections import COLLECTION_NAMES
from app.rag.contracts import KnowledgeDocument
from app.rag.in_memory import InMemoryKnowledgeStore


def test_only_two_logical_collections_are_defined() -> None:
    assert COLLECTION_NAMES == {"product_knowledge", "review_insight"}


def test_in_memory_store_returns_demo_evidence_reference() -> None:
    store = InMemoryKnowledgeStore()
    store.ingest(
        [
            KnowledgeDocument(
                document_id="demo-doc-1",
                product_id="product-1",
                knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
                content="DEMO organizer has a zip closure.",
                source_name="TradePilot demo fixture",
                data_origin=DataOrigin.DEMO,
            )
        ]
    )

    result = store.retrieve(
        query="zip closure",
        product_id="product-1",
        knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
    )

    assert result.status is AgentStatus.SUCCEEDED
    assert result.evidence[0].evidence_id == "demo-doc-1"
    assert result.evidence[0].is_demo is True


def test_in_memory_store_returns_insufficient_evidence_without_fabrication() -> None:
    result = InMemoryKnowledgeStore().retrieve(
        query="anything",
        product_id="missing-product",
        knowledge_type=KnowledgeType.REVIEW_INSIGHT,
    )

    assert result.status is AgentStatus.INSUFFICIENT_EVIDENCE
    assert result.evidence == []
    assert result.data_gaps[0].code == "no_rag_evidence"


def test_in_memory_store_can_retrieve_all_peer_products_in_one_group() -> None:
    store = InMemoryKnowledgeStore()
    store.ingest(
        [
            KnowledgeDocument(
                document_id=f"peer-review-{index}",
                product_id=f"peer-{index}",
                knowledge_type=KnowledgeType.REVIEW_INSIGHT,
                content=f"Traceable peer review {index}",
                source_name="peer review fixture",
                data_origin=DataOrigin.REAL,
                metadata={"peer_group_id": "peer-group-1", "evidence_scope": "peer_product"},
            )
            for index in range(3)
        ]
    )

    result = store.retrieve(
        query="peer concerns",
        product_id="new-product-with-no-reviews",
        knowledge_type=KnowledgeType.REVIEW_INSIGHT,
        scope=RetrievalScope.PEER_GROUP,
        peer_group_id="peer-group-1",
    )

    assert result.status is AgentStatus.SUCCEEDED
    assert {item.evidence_id for item in result.evidence} == {
        "peer-review-0",
        "peer-review-1",
        "peer-review-2",
    }


class TinyEmbedding:
    @staticmethod
    def name() -> str:
        return "tradepilot-test-embedding"

    @staticmethod
    def build_from_config(config):  # type: ignore[no-untyped-def]
        del config
        return TinyEmbedding()

    def get_config(self) -> dict[str, object]:
        return {}

    def __call__(self, input):  # type: ignore[no-untyped-def]
        return [[float(len(text)), 1.0, 0.0] for text in input]

    def embed_query(self, input):  # type: ignore[no-untyped-def]
        return self(input)

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "l2"

    def supported_spaces(self) -> list[str]:
        return ["l2"]


def test_minimal_chroma_adapter_uses_injected_embedding_without_download(tmp_path: Path) -> None:
    store = ChromaKnowledgeStore(tmp_path, TinyEmbedding())
    documents = [
        KnowledgeDocument(
            document_id="chroma-demo-1",
            product_id="product-1",
            knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
            content="DEMO Chroma scaffold evidence.",
            source_name="TradePilot demo fixture",
            data_origin=DataOrigin.DEMO,
        ),
        KnowledgeDocument(
            document_id="chroma-demo-2",
            product_id="product-1",
            knowledge_type=KnowledgeType.REVIEW_INSIGHT,
            content="DEMO Chroma review evidence.",
            source_name="TradePilot demo fixture",
            data_origin=DataOrigin.DEMO,
        ),
    ]

    assert store.ingest(documents) == 2
    result = store.retrieve(
        query="scaffold evidence",
        product_id="product-1",
        knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
    )

    assert result.status is AgentStatus.SUCCEEDED
    assert result.evidence[0].evidence_id == "chroma-demo-1"
    assert {item.name for item in store.client.list_collections()} == COLLECTION_NAMES


def test_chroma_ingest_deduplicates_repeated_document_ids_within_one_batch(tmp_path: Path) -> None:
    store = ChromaKnowledgeStore(tmp_path, TinyEmbedding())
    first = KnowledgeDocument(
        document_id="duplicate-review",
        product_id="peer-1",
        knowledge_type=KnowledgeType.REVIEW_INSIGHT,
        content="Earlier duplicate content.",
        source_name="review fixture",
        data_origin=DataOrigin.REAL,
        metadata={"content_hash": "earlier"},
    )
    latest = first.model_copy(
        update={"content": "Latest duplicate content.", "metadata": {"content_hash": "latest"}}
    )

    report = store.ingest_with_report([first, latest])
    collection = store._collection(KnowledgeType.REVIEW_INSIGHT)
    stored = collection.get(ids=["duplicate-review"], include=["documents", "metadatas"])

    assert report.attempted == 2
    assert report.inserted_or_updated == 1
    assert stored["documents"] == ["Latest duplicate content."]
    assert stored["metadatas"][0]["content_hash"] == "latest"

    store.clear()
    assert store.client.list_collections() == []


def test_chroma_adapter_filters_peer_group_without_requiring_new_product_id(tmp_path: Path) -> None:
    store = ChromaKnowledgeStore(tmp_path, TinyEmbedding())
    store.ingest(
        [
            KnowledgeDocument(
                document_id=f"peer-doc-{group}-{index}",
                product_id=f"peer-{group}-{index}",
                knowledge_type=KnowledgeType.REVIEW_INSIGHT,
                content=f"Peer group {group} review {index}",
                source_name="peer review fixture",
                data_origin=DataOrigin.REAL,
                metadata={"peer_group_id": group, "evidence_scope": "peer_product"},
            )
            for group in ("wanted", "other")
            for index in range(2)
        ]
    )

    result = store.retrieve(
        query="review",
        product_id="new-product-with-no-reviews",
        knowledge_type=KnowledgeType.REVIEW_INSIGHT,
        scope=RetrievalScope.PEER_GROUP,
        peer_group_id="wanted",
    )

    assert result.status is AgentStatus.SUCCEEDED
    assert {item.metadata["peer_group_id"] for item in result.evidence} == {"wanted"}
    assert {item.metadata["evidence_scope"] for item in result.evidence} == {"peer_product"}
