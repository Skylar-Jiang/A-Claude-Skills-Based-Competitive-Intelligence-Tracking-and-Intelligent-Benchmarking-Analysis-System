from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.enums import DataOrigin, KnowledgeType
from app.db.migrations import upgrade_database
from app.db.models.core import CompetitorOffer, KnowledgeSource, Product, Review
from app.domain.peer_matching import CandidateProductSignature, PeerMatch, PeerMatcher, load_peer_match_config
from app.domain.product_catalog import ProductCatalog
from app.domain.review_lookup import IndexedReview, ReviewLookup
from app.rag.chroma import ChromaKnowledgeStore
from app.rag.contracts import KnowledgeDocument
from app.rag.utils import content_hash, stable_id
from app.schemas.product import ProductProfile

MANIFEST_VERSION = 1


@dataclass(slots=True)
class PeerDemoSubsetResult:
    new_product_id: str
    peer_group_id: str
    new_product_count: int
    new_product_review_count: int
    peer_product_count: int
    peer_review_count: int
    collection_counts: dict[str, int]
    catalog_scan_duration_ms: int
    review_lookup_duration_ms: int
    prefilter_count: int
    rerank_count: int
    excluded_accessory_count: int
    insufficient_peer_products: bool
    match_metadata: dict[str, Any]
    catalog_rebuilt: bool
    review_lookup_rebuilt: bool
    database_rebuilt: bool
    index_rebuilt: bool
    total_duration_ms: int
    fingerprint: str


def prepare_peer_group_demo_subset(
    *,
    new_product: ProductProfile,
    metadata_path: Path,
    reviews_path: Path,
    runtime_dir: Path,
    embedding_function: Any,
    config_path: Path,
    max_reviews: int = 300,
    vision_summary: str = "",
) -> PeerDemoSubsetResult:
    if max_reviews < 1:
        raise ValueError("max_reviews must be at least 1")
    if not metadata_path.is_file() or not reviews_path.is_file():
        raise FileNotFoundError("Real pet-supplies metadata and review JSONL files are required")

    started = time.perf_counter()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = runtime_dir / "cache"
    catalog = ProductCatalog.build(metadata_path, cache_dir / "product_catalog.sqlite")
    review_lookup = ReviewLookup.build(reviews_path, cache_dir / "review_lookup.sqlite")

    signature = CandidateProductSignature.from_product(new_product, vision_summary=vision_summary)
    matcher = PeerMatcher(embedding_function, load_peer_match_config(config_path))
    match_result = matcher.match(  # type: ignore[arg-type]
        signature,
        catalog.iter_products(),
        group_context=catalog.source_signature,
    )
    match_by_parent = {peer.parent_asin: peer for peer in match_result.peers}
    reviews = review_lookup.read(list(match_by_parent), max_total=max_reviews)
    reviews = [item for item in reviews if item.parent_asin in match_by_parent and _review_content(item.record)]

    fingerprint = _fingerprint(
        new_product=new_product,
        catalog_signature=catalog.source_signature,
        review_signature=review_lookup.source_signature,
        peers=match_result.peers,
        reviews=reviews,
        embedding_function=embedding_function,
    )
    manifest_path = runtime_dir / "peer_subset_manifest.json"
    manifest = _load_manifest(manifest_path)
    unchanged = manifest.get("version") == MANIFEST_VERSION and manifest.get("fingerprint") == fingerprint

    database_path = runtime_dir / "tradepilot_demo.db"
    database_rebuilt = not (unchanged and database_path.is_file())
    if database_rebuilt:
        database_path.unlink(missing_ok=True)
        _build_database(
            database_path=database_path,
            new_product=new_product,
            peers=match_result.peers,
            reviews=reviews,
            metadata_path=metadata_path,
            reviews_path=reviews_path,
        )

    store = ChromaKnowledgeStore(runtime_dir / "chroma", embedding_function)
    expected_counts = {
        KnowledgeType.PRODUCT_KNOWLEDGE.value: len(match_result.peers),
        KnowledgeType.REVIEW_INSIGHT.value: len(reviews),
    }
    current_counts = _collection_counts(store)
    index_rebuilt = not (unchanged and current_counts == expected_counts)
    if index_rebuilt:
        store.clear()
        store.ingest(
            build_peer_documents(
                peers=match_result.peers,
                reviews=reviews,
                metadata_path=metadata_path,
                reviews_path=reviews_path,
            )
        )
    collection_counts = _collection_counts(store)

    result = PeerDemoSubsetResult(
        new_product_id=new_product.product_id,
        peer_group_id=match_result.peer_group_id,
        new_product_count=1,
        new_product_review_count=0,
        peer_product_count=len(match_result.peers),
        peer_review_count=len(reviews),
        collection_counts=collection_counts,
        catalog_scan_duration_ms=catalog.scan_duration_ms,
        review_lookup_duration_ms=review_lookup.build_duration_ms,
        prefilter_count=match_result.prefilter_count,
        rerank_count=match_result.rerank_count,
        excluded_accessory_count=match_result.excluded_accessory_count,
        insufficient_peer_products=match_result.insufficient_peer_products,
        match_metadata=match_result.match_metadata,
        catalog_rebuilt=catalog.rebuilt,
        review_lookup_rebuilt=review_lookup.rebuilt,
        database_rebuilt=database_rebuilt,
        index_rebuilt=index_rebuilt,
        total_duration_ms=round((time.perf_counter() - started) * 1000),
        fingerprint=fingerprint,
    )
    manifest_path.write_text(
        json.dumps({"version": MANIFEST_VERSION, **asdict(result)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _build_database(
    *,
    database_path: Path,
    new_product: ProductProfile,
    peers: list[PeerMatch],
    reviews: list[IndexedReview],
    metadata_path: Path,
    reviews_path: Path,
) -> None:
    database_url = f"sqlite:///{database_path.resolve().as_posix()}"
    upgrade_database(database_url)
    engine = create_engine(database_url)
    with Session(engine) as session:
        persist_peer_selection(
            session=session,
            new_product=new_product,
            peers=peers,
            reviews=reviews,
            metadata_path=metadata_path,
            reviews_path=reviews_path,
        )
    engine.dispose()


def persist_peer_selection(
    *,
    session: Session,
    new_product: ProductProfile,
    peers: list[PeerMatch],
    reviews: list[IndexedReview],
    metadata_path: Path,
    reviews_path: Path,
) -> None:
    match_by_parent = {peer.parent_asin: peer for peer in peers}
    peer_group_id = peers[0].peer_group_id
    payload = new_product.model_dump(
        mode="json",
        exclude={"product_id", "data_origin", "file_references", "data_gaps"},
    )
    session.merge(
        Product(
            product_id=new_product.product_id,
            name=new_product.name,
            category=new_product.category,
            data_mode=new_product.data_mode.value,
            data_origin=new_product.data_origin.value,
            attributes_json={**new_product.attributes, "peer_group_id": peer_group_id},
            metadata_json={"evidence_scope": "candidate_product", "peer_group_id": peer_group_id},
            payload_json=payload,
        )
    )
    for peer in peers:
        product = peer.product
        peer_metadata = _peer_metadata(peer, metadata_path)
        peer_payload = _peer_payload(peer)
        session.merge(
            Product(
                product_id=peer.peer_product_id,
                name=product.title[:200],
                category=(
                    product.categories[-1] if product.categories else product.main_category or "pet-supplies"
                )[:120],
                data_mode="real",
                data_origin="real",
                attributes_json=peer_payload["attributes"],
                metadata_json=peer_metadata,
                payload_json=peer_payload,
            )
        )
        session.merge(
            CompetitorOffer(
                offer_id=stable_id("peer-offer", peer.parent_asin),
                product_id=peer.peer_product_id,
                data_origin="real",
                attributes_json={
                    "parent_asin": peer.parent_asin,
                    "price": str(product.price) if product.price is not None else None,
                    "average_rating": product.average_rating,
                    "rating_number": product.rating_number,
                    "peer_group_id": peer.peer_group_id,
                    "match_score": peer.match_score,
                },
            )
        )
        session.merge(
            KnowledgeSource(
                source_id=stable_id("peer-knowledge", peer.parent_asin),
                product_id=peer.peer_product_id,
                knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE.value,
                content=_peer_content(peer),
                data_origin="real",
                metadata_json=peer_metadata,
            )
        )
    for item in reviews:
        peer = match_by_parent[item.parent_asin]
        metadata = {
            **_peer_metadata(peer, reviews_path, source_row=item.source_row),
            "review_title": str(item.record.get("title") or ""),
            "rating": item.record.get("rating"),
            "verified_purchase": bool(item.record.get("verified_purchase")),
        }
        session.merge(
            Review(
                review_id=_review_id(item),
                product_id=peer.peer_product_id,
                content=_review_content(item.record),
                data_origin="real",
                metadata_json=metadata,
            )
        )
    session.commit()


def build_peer_documents(
    *,
    peers: list[PeerMatch],
    reviews: list[IndexedReview],
    metadata_path: Path,
    reviews_path: Path,
) -> list[KnowledgeDocument]:
    documents: list[KnowledgeDocument] = []
    match_by_parent = {peer.parent_asin: peer for peer in peers}
    for peer in peers:
        content = _peer_content(peer)
        documents.append(
            KnowledgeDocument(
                document_id=stable_id("peer-product-document", peer.parent_asin, content_hash(content)),
                product_id=peer.peer_product_id,
                knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
                content=content,
                source_name=peer.product.title,
                source_uri=f"{metadata_path}#L{peer.product.source_line}",
                data_origin=DataOrigin.REAL,
                metadata={
                    **_peer_metadata(peer, metadata_path),
                    "content_hash": content_hash(content),
                },
            )
        )
    for item in reviews:
        peer = match_by_parent[item.parent_asin]
        content = _review_content(item.record)
        review_id = _review_id(item)
        documents.append(
            KnowledgeDocument(
                document_id=stable_id("peer-review-document", review_id, content_hash(content)),
                product_id=peer.peer_product_id,
                knowledge_type=KnowledgeType.REVIEW_INSIGHT,
                content=content,
                source_name=f"同类商品评论样本 {peer.parent_asin}",
                source_uri=f"{reviews_path}#L{item.source_row}",
                data_origin=DataOrigin.REAL,
                metadata={
                    **_peer_metadata(peer, reviews_path, source_row=item.source_row),
                    "review_id": review_id,
                    "content_hash": content_hash(content),
                },
            )
        )
    return documents


def _peer_payload(peer: PeerMatch) -> dict[str, object]:
    product = peer.product
    return {
        "name": product.title[:200],
        "category": (product.categories[-1] if product.categories else product.main_category or "pet-supplies")[:120],
        "description": product.description,
        "attributes": {
            "parent_asin": peer.parent_asin,
            "details": product.details,
            "categories": product.categories,
            "main_category": product.main_category,
            "average_rating": product.average_rating,
            "rating_number": product.rating_number,
            "price": str(product.price) if product.price is not None else None,
            "peer_group_id": peer.peer_group_id,
            "match_score": peer.match_score,
            "match_reason": peer.match_reason,
            "match_method": peer.match_method,
            "image_url": product.image_url,
        },
        "materials": [],
        "dimensions": {},
        "features": product.features,
        "use_scenarios": [],
        "target_market": "amazon_us",
        "target_audience": product.target_species,
        "target_price": str(product.price) if product.price is not None else None,
        "target_currency": "USD" if product.price is not None else None,
        "known_risks": [],
        "data_mode": "real",
    }


def _peer_content(peer: PeerMatch) -> str:
    product = peer.product
    sections = [f"Title: {product.title}"]
    if product.description:
        sections.append(f"Description: {product.description}")
    if product.features:
        sections.append("Features:\n- " + "\n- ".join(product.features))
    if product.details:
        sections.append("Details:\n- " + "\n- ".join(f"{key}: {value}" for key, value in product.details.items()))
    sections.append(
        "Structured facts: "
        f"price={product.price}; average_rating={product.average_rating}; rating_number={product.rating_number}"
    )
    return "\n\n".join(sections)


def _peer_metadata(peer: PeerMatch, source_path: Path, *, source_row: int | None = None) -> dict[str, object]:
    return {
        "evidence_scope": "peer_product",
        "peer_group_id": peer.peer_group_id,
        "peer_product_id": peer.peer_product_id,
        "parent_asin": peer.parent_asin,
        "match_score": peer.match_score,
        "match_reason": peer.match_reason,
        "is_accessory": peer.is_accessory,
        "match_method": peer.match_method,
        "source_file": str(source_path),
        "source_row": source_row if source_row is not None else peer.product.source_line,
    }


def _review_content(record: dict[str, Any]) -> str:
    title = " ".join(str(record.get("title") or "").split())
    text = " ".join(str(record.get("text") or "").split())
    return f"{title}\n\n{text}".strip()


def _review_id(item: IndexedReview) -> str:
    record = item.record
    return stable_id(
        "peer-review",
        item.parent_asin,
        record.get("asin") or "",
        record.get("user_id") or "",
        record.get("timestamp") or "",
        record.get("title") or "",
        record.get("text") or "",
    )


def _fingerprint(
    *,
    new_product: ProductProfile,
    catalog_signature: str,
    review_signature: str,
    peers: list[PeerMatch],
    reviews: list[IndexedReview],
    embedding_function: Any,
) -> str:
    payload = {
        "version": MANIFEST_VERSION,
        "new_product": new_product.model_dump(mode="json"),
        "catalog_signature": catalog_signature,
        "review_signature": review_signature,
        "embedding": getattr(embedding_function, "name", lambda: type(embedding_function).__name__)(),
        "peers": [peer.model_dump(mode="json") for peer in peers],
        "reviews": [review.model_dump(mode="json") for review in reviews],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_manifest(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _collection_counts(store: ChromaKnowledgeStore) -> dict[str, int]:
    return {name: int(item["count"]) for name, item in store.status().items()}
