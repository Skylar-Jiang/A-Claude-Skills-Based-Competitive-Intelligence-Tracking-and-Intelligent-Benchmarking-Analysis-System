import json
from decimal import Decimal
from pathlib import Path

import chromadb
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.enums import DataMode, DataOrigin
from app.db.models.core import CompetitorOffer, Product, Review
from app.demo_peer_subset import prepare_peer_group_demo_subset
from app.schemas.product import ProductCreate, ProductProfile


class TinyEmbedding:
    @staticmethod
    def name() -> str:
        return "tradepilot-peer-subset-test-embedding"

    @staticmethod
    def build_from_config(config):  # type: ignore[no-untyped-def]
        del config
        return TinyEmbedding()

    def get_config(self) -> dict[str, object]:
        return {}

    def __call__(self, input):  # type: ignore[no-untyped-def]
        return self.embed_documents(input if isinstance(input, list) else [input])

    def embed_query(self, input):  # type: ignore[no-untyped-def]
        return self(input)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            [
                1.0 if "fountain" in text.casefold() else 0.0,
                1.0 if "cat" in text.casefold() else 0.0,
                float(len(text) % 19) / 19,
            ]
            for text in texts
        ]

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "l2"

    def supported_spaces(self) -> list[str]:
        return ["l2"]


def _new_product() -> ProductProfile:
    return ProductProfile(
        product_id="new-fountain-1",
        data_origin=DataOrigin.USER,
        **ProductCreate(
            name="Quiet Cat Water Fountain",
            category="Pet Supplies > Cats > Fountains",
            description="New automatic circulating fountain for indoor cats.",
            attributes={"details": {"Target Species": "Cat"}, "capacity": "2.5 L"},
            features=["quiet operation", "visible water level", "easy-clean reservoir"],
            use_scenarios=["indoor cat hydration"],
            target_market="amazon_us",
            target_audience=["cat owners"],
            target_price=Decimal("39.99"),
            target_currency="USD",
            data_mode=DataMode.REAL,
        ).model_dump(),
    )


def _peer_metadata(index: int) -> dict[str, object]:
    parent_asin = f"PEER-{index:02d}"
    return {
        "parent_asin": parent_asin,
        "title": f"Ceramic Cat Water Fountain Model {index}",
        "description": ["Complete automatic drinking fountain for indoor cats."],
        "features": ["quiet operation", "visible water level", "removable reservoir"],
        "details": {"Target Species": "Cat", "Capacity": f"{2 + index / 10:.1f} Liters"},
        "categories": ["Pet Supplies", "Cats", "Fountains"],
        "main_category": "Pet Supplies",
        "price": 29.99 + index,
        "average_rating": 4.1 + index / 100,
        "rating_number": 500 + index,
        "images": [{"variant": "MAIN", "large": f"https://example.test/{parent_asin}.jpg"}],
    }


def _accessory_metadata(index: int) -> dict[str, object]:
    parent_asin = f"ACCESSORY-{index:02d}"
    return {
        "parent_asin": parent_asin,
        "title": f"Replacement Filter for Cat Water Fountain {index}",
        "description": ["Filter cartridge only."],
        "features": ["replacement filter"],
        "details": {"Target Species": "Cat"},
        "categories": ["Pet Supplies", "Cats", "Fountain Accessories"],
        "main_category": "Pet Supplies",
        "price": 9.99,
        "average_rating": 4.5,
        "rating_number": 100,
    }


def _review(parent_asin: str, index: int) -> dict[str, object]:
    return {
        "parent_asin": parent_asin,
        "asin": f"ASIN-{parent_asin}",
        "user_id": f"USER-{parent_asin}-{index}",
        "timestamp": index,
        "rating": 3.0 + index % 3,
        "title": f"Peer review {index}",
        "text": f"Original peer review {index}: cleaning and noise matter.",
        "verified_purchase": True,
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_peer_subset_has_one_unreviewed_new_product_and_traceable_real_peers(tmp_path: Path) -> None:
    metadata_path = tmp_path / "metadata.jsonl"
    reviews_path = tmp_path / "reviews.jsonl"
    peers = [_peer_metadata(index) for index in range(12)]
    accessories = [_accessory_metadata(index) for index in range(2)]
    _write_jsonl(metadata_path, [*peers, *accessories])
    review_rows = [
        _review(str(product["parent_asin"]), review_index)
        for product in [*peers, *accessories]
        for review_index in range(5)
    ]
    _write_jsonl(reviews_path, [*review_rows, review_rows[0]])
    runtime_dir = tmp_path / "demo"

    first = prepare_peer_group_demo_subset(
        new_product=_new_product(),
        metadata_path=metadata_path,
        reviews_path=reviews_path,
        runtime_dir=runtime_dir,
        embedding_function=TinyEmbedding(),
        config_path=Path("config/peer_matching.yaml"),
        max_reviews=300,
    )
    second = prepare_peer_group_demo_subset(
        new_product=_new_product(),
        metadata_path=metadata_path,
        reviews_path=reviews_path,
        runtime_dir=runtime_dir,
        embedding_function=TinyEmbedding(),
        config_path=Path("config/peer_matching.yaml"),
        max_reviews=300,
    )

    assert first.new_product_id == "new-fountain-1"
    assert first.new_product_count == 1
    assert first.new_product_review_count == 0
    assert first.peer_product_count == 12
    assert first.peer_review_count == 60
    assert first.excluded_accessory_count == 2
    assert first.prefilter_count == 12
    assert first.rerank_count == 12
    assert first.insufficient_peer_products is False
    assert first.match_metadata["matcher_version"] == "peer-matcher-v2"
    assert first.match_metadata["embedding_model"] == "tradepilot-peer-subset-test-embedding"
    assert first.collection_counts == {"product_knowledge": 12, "review_insight": 60}
    assert first.catalog_rebuilt is True
    assert first.review_lookup_rebuilt is True
    assert first.database_rebuilt is True
    assert first.index_rebuilt is True
    assert first.total_duration_ms >= 0
    assert second.catalog_rebuilt is False
    assert second.review_lookup_rebuilt is False
    assert second.database_rebuilt is False
    assert second.index_rebuilt is False

    database_path = runtime_dir / "tradepilot_demo.db"
    engine = create_engine(f"sqlite:///{database_path}")
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Product)) == 13
        assert session.scalar(select(func.count()).select_from(Product).where(Product.data_origin == "user")) == 1
        assert session.scalar(select(func.count()).select_from(CompetitorOffer)) == 12
        assert session.scalar(select(func.count()).select_from(Review)) == 60
        assert (
            session.scalar(select(func.count()).select_from(Review).where(Review.product_id == "new-fountain-1"))
            == 0
        )
        names = set(session.scalars(select(Product.name)))
        assert all("Replacement Filter" not in name for name in names)
    engine.dispose()

    client = chromadb.PersistentClient(path=str(runtime_dir / "chroma"))
    review_metadata = client.get_collection("review_insight").get(include=["metadatas"])["metadatas"]
    assert review_metadata
    assert {item["evidence_scope"] for item in review_metadata} == {"peer_product"}
    assert {item["peer_group_id"] for item in review_metadata} == {first.peer_group_id}
    assert all(item["peer_product_id"] and item["parent_asin"] for item in review_metadata)
    assert all(item["source_file"] == str(reviews_path) for item in review_metadata)
    assert all(int(item["source_row"]) > 0 for item in review_metadata)
