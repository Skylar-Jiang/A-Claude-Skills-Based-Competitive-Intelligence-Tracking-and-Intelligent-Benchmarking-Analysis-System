import json
from pathlib import Path

import pytest

from app.core.enums import DataMode, DataOrigin
from app.core.exceptions import DataPreparationRequiredError
from app.domain.peer_data import prepare_peer_data, select_peer_group_from_prepared
from app.domain.product_catalog import ProductCatalog
from app.domain.review_lookup import ReviewLookup
from app.schemas.product import ProductCreate, ProductProfile


class RecordingEmbedding:
    def __init__(self) -> None:
        self.document_count = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_count += len(texts)
        return [[1.0, float(len(text) % 11)] for text in texts]


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _new_product() -> ProductProfile:
    return ProductProfile(
        product_id="new-product",
        data_origin=DataOrigin.USER,
        **ProductCreate(
            name="Quiet Cat Water Fountain",
            category="Pet Supplies > Cats > Fountains",
            description="Automatic indoor cat fountain.",
            attributes={"details": {"Target Species": "Cat"}},
            features=["quiet operation", "easy clean reservoir"],
            use_scenarios=["indoor cat hydration"],
            data_mode=DataMode.REAL,
        ).model_dump(),
    )


def _metadata(index: int) -> dict[str, object]:
    return {
        "parent_asin": f"PEER-{index}",
        "title": f"Complete Cat Water Fountain {index}",
        "description": ["Automatic indoor cat fountain."],
        "features": ["quiet operation", "easy clean reservoir"],
        "details": {"Target Species": "Cat"},
        "categories": ["Pet Supplies", "Cats", "Fountains"],
        "main_category": "Pet Supplies",
        "price": 30 + index,
        "average_rating": 4.2,
        "rating_number": 100 + index,
    }


def _review(parent_asin: str, index: int) -> dict[str, object]:
    return {
        "parent_asin": parent_asin,
        "user_id": f"user-{parent_asin}-{index}",
        "timestamp": index,
        "rating": 4,
        "title": "Peer review",
        "text": "Cleaning and noise matter.",
    }


def test_online_selection_requires_explicit_preparation_and_never_rebuilds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_path = tmp_path / "metadata.jsonl"
    reviews_path = tmp_path / "reviews.jsonl"
    _write_jsonl(metadata_path, [_metadata(index) for index in range(12)])
    _write_jsonl(
        reviews_path,
        [_review(f"PEER-{index}", review) for index in range(12) for review in range(5)],
    )
    cache_dir = tmp_path / "cache"
    embedding = RecordingEmbedding()

    with pytest.raises(DataPreparationRequiredError, match="prepare_peer_data"):
        select_peer_group_from_prepared(
            new_product=_new_product(),
            metadata_path=metadata_path,
            reviews_path=reviews_path,
            cache_dir=cache_dir,
            embedding_function=embedding,
            config_path=Path("config/peer_matching.yaml"),
        )

    prepared = prepare_peer_data(
        metadata_path=metadata_path,
        reviews_path=reviews_path,
        cache_dir=cache_dir,
    )
    assert prepared.catalog_rebuilt is True
    assert prepared.review_lookup_rebuilt is True

    def unexpected_build(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("online selection must not build or rebuild offline caches")

    monkeypatch.setattr(ProductCatalog, "build", unexpected_build)
    monkeypatch.setattr(ReviewLookup, "build", unexpected_build)
    monkeypatch.setattr(ProductCatalog, "iter_products", unexpected_build)
    selected = select_peer_group_from_prepared(
        new_product=_new_product(),
        metadata_path=metadata_path,
        reviews_path=reviews_path,
        cache_dir=cache_dir,
        embedding_function=embedding,
        config_path=Path("config/peer_matching.yaml"),
    )

    assert len(selected.match_result.peers) == 12
    assert len(selected.selected_parent_asins) == 12
    assert len(selected.reviews) == 60
    assert embedding.document_count == selected.match_result.prefilter_count + 1
    assert selected.match_result.insufficient_peer_products is False
    assert selected.match_result.match_metadata["matcher_version"] == "peer-matcher-v2"
    assert selected.match_result.match_metadata["embedding_model"] == "RecordingEmbedding"
    assert selected.match_result.match_metadata["minimum_semantic_score"] == 0.45


def test_prepared_cache_source_change_requires_explicit_rebuild(tmp_path: Path) -> None:
    metadata_path = tmp_path / "metadata.jsonl"
    reviews_path = tmp_path / "reviews.jsonl"
    _write_jsonl(metadata_path, [_metadata(index) for index in range(12)])
    _write_jsonl(reviews_path, [_review("PEER-0", 0)])
    cache_dir = tmp_path / "cache"
    prepare_peer_data(metadata_path=metadata_path, reviews_path=reviews_path, cache_dir=cache_dir)
    metadata_path.write_text(
        metadata_path.read_text(encoding="utf-8") + json.dumps(_metadata(13)) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DataPreparationRequiredError, match="stale"):
        select_peer_group_from_prepared(
            new_product=_new_product(),
            metadata_path=metadata_path,
            reviews_path=reviews_path,
            cache_dir=cache_dir,
            embedding_function=RecordingEmbedding(),
            config_path=Path("config/peer_matching.yaml"),
        )
