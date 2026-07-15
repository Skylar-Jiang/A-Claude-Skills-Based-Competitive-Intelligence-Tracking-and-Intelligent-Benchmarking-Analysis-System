import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models.core import CompetitorOffer, KnowledgeSource, Product, Review
from app.demo_subset import prepare_real_demo_subset


class TinyEmbedding:
    @staticmethod
    def name() -> str:
        return "tradepilot-subset-test-embedding"

    @staticmethod
    def build_from_config(config):  # type: ignore[no-untyped-def]
        del config
        return TinyEmbedding()

    def get_config(self) -> dict[str, object]:
        return {}

    def __call__(self, input):  # type: ignore[no-untyped-def]
        return [[float(len(text)), 1.0, 0.0] for text in input]

    def embed_query(self, input):  # type: ignore[no-untyped-def]
        return self(input if isinstance(input, list) else [input])

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "l2"

    def supported_spaces(self) -> list[str]:
        return ["l2"]


def _write_jsonl(path: Path, rows: list[dict[str, object] | str]) -> None:
    lines = [row if isinstance(row, str) else json.dumps(row) for row in rows]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_prepare_subset_builds_one_product_two_collections_and_skips_unchanged(tmp_path: Path) -> None:
    metadata_path = tmp_path / "meta_pet_supplies_prefiltered.jsonl"
    reviews_path = tmp_path / "pet_supplies_reviews_prefiltered.jsonl"
    _write_jsonl(
        metadata_path,
        [
            {
                "title": "Automatic Cat Water Fountain",
                "main_category": "Pet Supplies",
                "average_rating": 4.5,
                "rating_number": 800,
                "features": ["Visible water window", "Quiet pump"],
                "description": ["Circulating drinking fountain for cats."],
                "price": 29.99,
                "images": [{"large": "https://example.test/fountain.jpg", "variant": "MAIN"}],
                "store": "Example Pet",
                "categories": ["Pet Supplies", "Cats", "Fountains"],
                "details": {"Color": "White"},
                "parent_asin": "FOUNTAIN-1",
            },
            "this row must not be read after the query match",
        ],
    )
    _write_jsonl(
        reviews_path,
        [
            {
                "rating": 5.0,
                "title": "Cat drinks more",
                "text": "The visible water window is helpful.",
                "asin": "A-1",
                "parent_asin": "FOUNTAIN-1",
                "user_id": "U-1",
                "timestamp": 1,
                "verified_purchase": True,
            },
            {
                "rating": 3.0,
                "title": "Pump needs cleaning",
                "text": "The pump is quiet but needs regular cleaning.",
                "asin": "A-1",
                "parent_asin": "FOUNTAIN-1",
                "user_id": "U-2",
                "timestamp": 2,
                "verified_purchase": True,
            },
            "this row must not be read after max_reviews",
        ],
    )
    runtime_dir = tmp_path / "demo"
    database_path = runtime_dir / "tradepilot_demo.db"
    chroma_dir = runtime_dir / "chroma"

    first = prepare_real_demo_subset(
        metadata_path=metadata_path,
        reviews_path=reviews_path,
        runtime_dir=runtime_dir,
        query="cat water fountain",
        max_reviews=2,
        review_scan_limit=2,
        embedding_function=TinyEmbedding(),
    )
    second = prepare_real_demo_subset(
        metadata_path=metadata_path,
        reviews_path=reviews_path,
        runtime_dir=runtime_dir,
        query="cat water fountain",
        max_reviews=2,
        review_scan_limit=2,
        embedding_function=TinyEmbedding(),
    )

    assert first.parent_asin == "FOUNTAIN-1"
    assert first.product_count == 1
    assert first.review_count == 2
    assert first.image_url == "https://example.test/fountain.jpg"
    assert first.collection_counts["product_knowledge"] >= 1
    assert first.collection_counts["review_insight"] == 2
    assert first.database_rebuilt is True
    assert first.index_rebuilt is True
    assert first.database_duration_ms >= 0
    assert first.index_duration_ms >= 0
    assert first.review_rows_scanned == 2
    assert second.database_rebuilt is False
    assert second.index_rebuilt is False
    assert second.fingerprint == first.fingerprint

    engine = create_engine(f"sqlite:///{database_path}")
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Product)) == 1
        assert session.scalar(select(func.count()).select_from(CompetitorOffer)) == 1
        assert session.scalar(select(func.count()).select_from(KnowledgeSource)) == 1
        assert session.scalar(select(func.count()).select_from(Review)) == 2
    engine.dispose()
    assert chroma_dir.exists()


def test_prepare_subset_falls_back_to_an_eligible_real_product(tmp_path: Path) -> None:
    metadata_path = tmp_path / "meta_pet_supplies_prefiltered.jsonl"
    reviews_path = tmp_path / "pet_supplies_reviews_prefiltered.jsonl"
    _write_jsonl(
        metadata_path,
        [
            {"title": "Incomplete", "parent_asin": "BAD"},
            {
                "title": "Reflective Dog Harness",
                "main_category": "Pet Supplies",
                "average_rating": 4.4,
                "rating_number": 200,
                "features": ["Reflective trim"],
                "description": ["Harness for daily walks."],
                "price": 24.95,
                "categories": ["Pet Supplies", "Dogs", "Harnesses"],
                "parent_asin": "HARNESS-1",
            },
        ],
    )
    _write_jsonl(
        reviews_path,
        [
            {
                "rating": 5.0,
                "title": "Visible at night",
                "text": "The reflective trim is easy to see.",
                "asin": "H-1",
                "parent_asin": "HARNESS-1",
                "user_id": "U-1",
                "timestamp": 1,
            }
        ],
    )

    result = prepare_real_demo_subset(
        metadata_path=metadata_path,
        reviews_path=reviews_path,
        runtime_dir=tmp_path / "demo",
        query="no matching product",
        max_reviews=5,
        embedding_function=TinyEmbedding(),
    )

    assert result.parent_asin == "HARNESS-1"
    assert result.review_count == 1
    assert result.product_count == 1


def test_prepare_subset_cli_defaults_to_isolated_demo_runtime() -> None:
    from scripts.prepare_real_demo_subset import build_parser

    args = build_parser().parse_args([])

    assert args.runtime_dir == Path("data/demo")
    assert args.query == "cat water fountain"
    assert args.max_reviews == 300
    assert args.review_scan_limit == 100_000
