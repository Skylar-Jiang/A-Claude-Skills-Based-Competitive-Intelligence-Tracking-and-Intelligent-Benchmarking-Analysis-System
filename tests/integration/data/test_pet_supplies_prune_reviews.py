import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.core import Product, Review
from scripts.domain_imports.import_pet_supplies import deterministic_id
from scripts.domain_imports.prune_pet_supplies_reviews import prune_pet_supplies_reviews


def test_prune_pet_supplies_reviews_deletes_only_reviews_missing_from_latest_json(tmp_path: Path) -> None:
    reviews_input_path = tmp_path / "reviews.jsonl"
    reviews_input_path.write_text(
        json.dumps(
            {
                "rating": 5.0,
                "title": "Keep me",
                "text": "Still in the new filtered file.",
                "asin": "ASIN-1",
                "parent_asin": "PET-PARENT-1",
                "user_id": "USER-1",
                "timestamp": 1,
            }
        ),
        encoding="utf-8",
    )

    keep_review_id = deterministic_id(
        "review", "PET-PARENT-1", "ASIN-1", "USER-1", 1, "Keep me", "Still in the new filtered file."
    )
    drop_review_id = deterministic_id(
        "review", "PET-PARENT-1", "ASIN-2", "USER-2", 2, "Drop me", "Old full import residue."
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            Product(
                product_id="pet-product-1",
                name="Pet Product",
                category="pet-supplies",
                data_mode="real",
                data_origin="real",
                attributes_json={"parent_asin": "PET-PARENT-1"},
                metadata_json={"source_file": "data/filtered/meta_pet_supplies_prefiltered.jsonl"},
                payload_json={},
            )
        )
        session.add(
            Product(
                product_id="other-product-1",
                name="Other Product",
                category="other",
                data_mode="real",
                data_origin="real",
                attributes_json={"parent_asin": "OTHER-PARENT-1"},
                metadata_json={"source_file": "data/filtered/other_domain.jsonl"},
                payload_json={},
            )
        )
        session.add(
            Review(
                review_id=keep_review_id,
                product_id="pet-product-1",
                content="keep",
                data_origin="real",
                metadata_json={},
            )
        )
        session.add(
            Review(
                review_id=drop_review_id,
                product_id="pet-product-1",
                content="drop",
                data_origin="real",
                metadata_json={},
            )
        )
        session.add(
            Review(
                review_id="other-review-1",
                product_id="other-product-1",
                content="other",
                data_origin="real",
                metadata_json={},
            )
        )
        session.commit()

        summary = prune_pet_supplies_reviews(session, reviews_input_path)

        assert summary.retained_review_ids == 1
        assert summary.scanned_reviews == 2
        assert summary.deleted_reviews == 1
        assert summary.kept_reviews == 1
        assert summary.skipped_invalid_reviews == 0

        assert session.get(Review, keep_review_id) is not None
        assert session.get(Review, drop_review_id) is None
        assert session.get(Review, "other-review-1") is not None
        assert session.scalar(select(func.count()).select_from(Review)) == 2
