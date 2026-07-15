from pathlib import Path

from app.core.enums import DataOrigin, KnowledgeType
from app.rag.contracts import KnowledgeDocument
from app.rag.manifest import IndexManifest


def _document(*, document_id: str = "chunk-1", content_hash: str = "hash-1") -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id,
        product_id="product-1",
        knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
        content="Product text",
        source_name="source",
        data_origin=DataOrigin.REAL,
        metadata={
            "document_id": "doc-1",
            "chunk_id": document_id,
            "source_file": "data/filtered/meta.jsonl",
            "source_row": 1,
            "content_hash": content_hash,
            "chunk_config_version": "rag-chunk-v1",
        },
    )


def test_manifest_skips_successful_unchanged_chunk(tmp_path: Path) -> None:
    manifest = IndexManifest(tmp_path / "manifest.sqlite")
    document = _document()

    assert manifest.decide(collection="product_knowledge", document=document, embedding_model="bge").action == "insert"
    manifest.mark_success(collection="product_knowledge", document=document, embedding_model="bge")
    manifest.commit()

    assert manifest.decide(collection="product_knowledge", document=document, embedding_model="bge").action == "skip"
    manifest.close()


def test_manifest_updates_changed_hash_or_model(tmp_path: Path) -> None:
    manifest = IndexManifest(tmp_path / "manifest.sqlite")
    document = _document()
    manifest.mark_success(collection="product_knowledge", document=document, embedding_model="bge")
    manifest.commit()

    changed = _document(content_hash="hash-2")

    assert manifest.decide(collection="product_knowledge", document=changed, embedding_model="bge").action == "update"
    assert (
        manifest.decide(collection="product_knowledge", document=document, embedding_model="other").action
        == "update"
    )
    manifest.close()


def test_manifest_clear_collection_is_isolated(tmp_path: Path) -> None:
    manifest = IndexManifest(tmp_path / "manifest.sqlite")
    product = _document(document_id="product-chunk")
    review = _document(document_id="review-chunk")
    manifest.mark_success(collection="product_knowledge", document=product, embedding_model="bge")
    manifest.mark_success(collection="review_insight", document=review, embedding_model="bge")
    manifest.commit()

    manifest.clear_collection("product_knowledge")

    assert manifest.decide(collection="product_knowledge", document=product, embedding_model="bge").action == "insert"
    assert manifest.decide(collection="review_insight", document=review, embedding_model="bge").action == "skip"
    manifest.close()
