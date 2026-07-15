from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import ErrorCode
from app.core.exceptions import TradePilotError
from app.demo_peer_subset import build_peer_documents, persist_peer_selection
from app.domain.peer_data import OnlinePeerSelection, select_peer_group_from_prepared
from app.rag.contracts import KnowledgeStore
from app.schemas.common import DataGap
from app.schemas.product import ProductProfile


@dataclass(slots=True)
class PreparedPeerGroupContext:
    peer_group_id: str
    selected_peer_products: list[dict[str, object]]
    selected_parent_asins: list[str]
    review_count: int
    match_method: str
    match_limitations: list[str]
    match_data_gaps: list[DataGap]
    match_metadata: dict[str, object]
    prefilter_count: int
    rerank_count: int
    excluded_accessory_count: int
    match_duration_ms: int
    review_read_duration_ms: int
    total_duration_ms: int
    documents_ingested: int
    database_persist_duration_ms: int
    rag_document_build_duration_ms: int
    rag_ingest_duration_ms: int
    peer_group_service_total_duration_ms: int


class PeerGroupService:
    """Online peer selection that only opens explicit, already-prepared offline caches."""

    def __init__(
        self,
        *,
        session: Session,
        knowledge_store: KnowledgeStore,
        settings: Settings,
    ) -> None:
        self.session = session
        self.knowledge_store = knowledge_store
        self.settings = settings

    def build_context(self, product: ProductProfile, *, vision_summary: str = "") -> PreparedPeerGroupContext:
        service_started = perf_counter()
        embedding_function = getattr(self.knowledge_store, "embedding_function", None)
        if embedding_function is None:
            raise TradePilotError(
                code=ErrorCode.KNOWLEDGE_UNAVAILABLE,
                message="Real peer-group analysis requires the configured Chroma embedding function",
                status_code=503,
            )
        selection = select_peer_group_from_prepared(
            new_product=product,
            metadata_path=self.settings.peer_metadata_path,
            reviews_path=self.settings.peer_reviews_path,
            cache_dir=self.settings.peer_cache_dir,
            embedding_function=embedding_function,
            config_path=self.settings.peer_match_config_path,
            max_reviews=self.settings.peer_max_reviews,
            vision_summary=vision_summary,
        )
        database_started = perf_counter()
        self._persist(product, selection)
        database_persist_duration_ms = round((perf_counter() - database_started) * 1000)
        document_build_started = perf_counter()
        documents = build_peer_documents(
            peers=selection.match_result.peers,
            reviews=selection.reviews,
            metadata_path=self.settings.peer_metadata_path,
            reviews_path=self.settings.peer_reviews_path,
        )
        rag_document_build_duration_ms = round((perf_counter() - document_build_started) * 1000)
        rag_ingest_started = perf_counter()
        documents_ingested = self.knowledge_store.ingest(documents)
        rag_ingest_duration_ms = round((perf_counter() - rag_ingest_started) * 1000)
        limitations = []
        if selection.match_result.insufficient_peer_products:
            limitations.append(
                f"仅 {len(selection.match_result.peers)} 个同类市场商品达到配置的规则与语义门槛；"
                "未使用低质量候选补足理想样本数。"
            )
        if len(selection.reviews) < 50:
            limitations.append(
                "同类商品评论样本少于 50 条；仅可描述样本中出现的关注点，不可推断精确比例。"
            )
        return PreparedPeerGroupContext(
            peer_group_id=selection.match_result.peer_group_id,
            selected_peer_products=[
                {
                    "peer_product_id": peer.peer_product_id,
                    "parent_asin": peer.parent_asin,
                    "match_score": peer.match_score,
                    "match_reason": peer.match_reason,
                    "match_method": peer.match_method,
                    "title": peer.product.title,
                    "features": peer.product.features,
                    "details": peer.product.details,
                    "categories": peer.product.categories,
                    "price": str(peer.product.price) if peer.product.price is not None else None,
                    "average_rating": peer.product.average_rating,
                    "rating_number": peer.product.rating_number,
                }
                for peer in selection.match_result.peers
            ],
            selected_parent_asins=selection.selected_parent_asins,
            review_count=len(selection.reviews),
            match_method="rules+candidate_embedding",
            match_limitations=limitations,
            match_data_gaps=selection.match_result.data_gaps,
            match_metadata=selection.match_result.match_metadata,
            prefilter_count=selection.match_result.prefilter_count,
            rerank_count=selection.match_result.rerank_count,
            excluded_accessory_count=selection.match_result.excluded_accessory_count,
            match_duration_ms=selection.match_duration_ms,
            review_read_duration_ms=selection.review_read_duration_ms,
            total_duration_ms=selection.total_duration_ms,
            documents_ingested=documents_ingested,
            database_persist_duration_ms=database_persist_duration_ms,
            rag_document_build_duration_ms=rag_document_build_duration_ms,
            rag_ingest_duration_ms=rag_ingest_duration_ms,
            peer_group_service_total_duration_ms=round((perf_counter() - service_started) * 1000),
        )

    def _persist(self, product: ProductProfile, selection: OnlinePeerSelection) -> None:
        persist_peer_selection(
            session=self.session,
            new_product=product,
            peers=selection.match_result.peers,
            reviews=selection.reviews,
            metadata_path=self.settings.peer_metadata_path,
            reviews_path=self.settings.peer_reviews_path,
        )
