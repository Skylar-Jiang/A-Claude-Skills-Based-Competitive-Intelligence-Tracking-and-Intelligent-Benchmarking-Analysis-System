from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.peer_matching import (
    CandidateProductSignature,
    PeerMatcher,
    PeerMatchResult,
    load_peer_match_config,
)
from app.domain.product_catalog import ProductCatalog
from app.domain.review_lookup import IndexedReview, ReviewLookup
from app.schemas.product import ProductProfile


@dataclass(slots=True)
class PeerDataPreparationResult:
    catalog_rebuilt: bool
    review_lookup_rebuilt: bool
    catalog_rows: int
    review_rows: int
    catalog_duration_ms: int
    review_lookup_duration_ms: int
    total_duration_ms: int


@dataclass(slots=True)
class OnlinePeerSelection:
    match_result: PeerMatchResult
    selected_parent_asins: list[str]
    reviews: list[IndexedReview]
    match_duration_ms: int
    review_read_duration_ms: int
    total_duration_ms: int


def prepare_peer_data(
    *,
    metadata_path: Path,
    reviews_path: Path,
    cache_dir: Path,
) -> PeerDataPreparationResult:
    started = time.perf_counter()
    catalog = ProductCatalog.build(metadata_path, cache_dir / "product_catalog.sqlite")
    review_lookup = ReviewLookup.build(reviews_path, cache_dir / "review_lookup.sqlite")
    return PeerDataPreparationResult(
        catalog_rebuilt=catalog.rebuilt,
        review_lookup_rebuilt=review_lookup.rebuilt,
        catalog_rows=catalog.row_count,
        review_rows=review_lookup.review_count,
        catalog_duration_ms=catalog.scan_duration_ms,
        review_lookup_duration_ms=review_lookup.build_duration_ms,
        total_duration_ms=round((time.perf_counter() - started) * 1000),
    )


def select_peer_group_from_prepared(
    *,
    new_product: ProductProfile,
    metadata_path: Path,
    reviews_path: Path,
    cache_dir: Path,
    embedding_function: Any,
    config_path: Path,
    max_reviews: int = 300,
    vision_summary: str = "",
) -> OnlinePeerSelection:
    started = time.perf_counter()
    catalog = ProductCatalog.open_prepared(metadata_path, cache_dir / "product_catalog.sqlite")
    review_lookup = ReviewLookup.open_prepared(reviews_path, cache_dir / "review_lookup.sqlite")
    signature = CandidateProductSignature.from_product(new_product, vision_summary=vision_summary)
    match_started = time.perf_counter()
    result = PeerMatcher(embedding_function, load_peer_match_config(config_path)).match(
        signature,
        catalog.iter_candidates(signature),  # type: ignore[arg-type]
        group_context=catalog.source_signature,
    )
    match_duration_ms = round((time.perf_counter() - match_started) * 1000)
    selected_parent_asins = [peer.parent_asin for peer in result.peers]
    review_started = time.perf_counter()
    reviews = review_lookup.read(selected_parent_asins, max_total=max_reviews)
    review_read_duration_ms = round((time.perf_counter() - review_started) * 1000)
    return OnlinePeerSelection(
        match_result=result,
        selected_parent_asins=selected_parent_asins,
        reviews=reviews,
        match_duration_ms=match_duration_ms,
        review_read_duration_ms=review_read_duration_ms,
        total_duration_ms=round((time.perf_counter() - started) * 1000),
    )
