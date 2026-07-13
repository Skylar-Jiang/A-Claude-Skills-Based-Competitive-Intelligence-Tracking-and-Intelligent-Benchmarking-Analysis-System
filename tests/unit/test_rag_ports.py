from pathlib import Path

from app.core.enums import AgentStatus, DataOrigin, KnowledgeType
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
