import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.enums import DataOrigin  # noqa: E402
from app.db.migrations import upgrade_database  # noqa: E402
from app.db.models.core import Product, Review  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from scripts.domain_imports.import_pet_supplies import deterministic_id  # noqa: E402

PET_METADATA_SOURCE_FILE = "data/filtered/meta_pet_supplies_prefiltered.jsonl"


@dataclass(slots=True)
class PruneSummary:
    retained_review_ids: int = 0
    scanned_reviews: int = 0
    deleted_reviews: int = 0
    kept_reviews: int = 0
    skipped_invalid_reviews: int = 0


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _normalize_text(value: object) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def _load_retained_review_ids(reviews_input_path: Path, summary: PruneSummary) -> set[str]:
    retained_review_ids: set[str] = set()
    with reviews_input_path.open("r", encoding="utf-8") as source:
        for line in source:
            raw_line = line.strip()
            if not raw_line:
                summary.skipped_invalid_reviews += 1
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                summary.skipped_invalid_reviews += 1
                continue
            if not isinstance(record, dict):
                summary.skipped_invalid_reviews += 1
                continue

            parent_asin = _normalize_text(record.get("parent_asin"))
            if not parent_asin:
                summary.skipped_invalid_reviews += 1
                continue

            review_id = deterministic_id(
                "review",
                parent_asin,
                _normalize_text(record.get("asin")),
                _normalize_text(record.get("user_id")),
                record.get("timestamp"),
                _normalize_text(record.get("title")),
                _normalize_text(record.get("text")),
            )
            retained_review_ids.add(review_id)

    summary.retained_review_ids = len(retained_review_ids)
    return retained_review_ids


def _load_pet_supplies_product_ids(session: Session) -> set[str]:
    product_ids: set[str] = set()
    statement = select(Product).where(Product.data_origin == DataOrigin.REAL.value)
    for product in session.scalars(statement):
        metadata = product.metadata_json if isinstance(product.metadata_json, dict) else {}
        if metadata.get("source_file") == PET_METADATA_SOURCE_FILE:
            product_ids.add(product.product_id)
    return product_ids


def prune_pet_supplies_reviews(session: Session, reviews_input_path: Path) -> PruneSummary:
    summary = PruneSummary()
    print("prune_pet_supplies_reviews: loading retained review ids", flush=True)
    retained_review_ids = _load_retained_review_ids(reviews_input_path, summary)
    print(f"prune_pet_supplies_reviews: retained_review_ids={len(retained_review_ids)}", flush=True)
    print("prune_pet_supplies_reviews: loading pet supplies product ids", flush=True)
    pet_product_ids = _load_pet_supplies_product_ids(session)
    print(f"prune_pet_supplies_reviews: pet_product_ids={len(pet_product_ids)}", flush=True)
    if not pet_product_ids:
        return summary

    stale_review_ids: list[str] = []
    statement = select(Review.review_id, Review.product_id).where(Review.data_origin == DataOrigin.REAL.value)
    print("prune_pet_supplies_reviews: scanning database reviews", flush=True)
    for review_id, product_id in session.execute(statement):
        if product_id not in pet_product_ids:
            continue
        summary.scanned_reviews += 1
        if summary.scanned_reviews % 50000 == 0:
            print(
                f"prune_pet_supplies_reviews: scanned_reviews={summary.scanned_reviews} "
                f"stale_candidates={len(stale_review_ids)}",
                flush=True,
            )
        if review_id in retained_review_ids:
            summary.kept_reviews += 1
            continue
        stale_review_ids.append(review_id)

    print(f"prune_pet_supplies_reviews: deleting stale reviews={len(stale_review_ids)}", flush=True)
    for chunk in _chunked(stale_review_ids, 500):
        session.execute(delete(Review).where(Review.review_id.in_(chunk)))
    summary.deleted_reviews = len(stale_review_ids)
    session.commit()
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prune pet supplies reviews that are absent from the latest filtered JSONL."
    )
    parser.add_argument(
        "--reviews-input",
        type=Path,
        default=Path("data/filtered/pet_supplies_reviews_prefiltered.jsonl"),
        help="Path to the filtered pet supplies reviews JSONL file.",
    )
    parser.add_argument(
        "--skip-upgrade",
        action="store_true",
        help="Skip running Alembic upgrade before pruning when the database schema is already up to date.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    if not args.skip_upgrade:
        upgrade_database(settings.database_url)
    with SessionLocal() as session:
        summary = prune_pet_supplies_reviews(session, args.reviews_input)

    print(f"retained_review_ids={summary.retained_review_ids}")
    print(f"scanned_reviews={summary.scanned_reviews}")
    print(f"deleted_reviews={summary.deleted_reviews}")
    print(f"kept_reviews={summary.kept_reviews}")
    print(f"skipped_invalid_reviews={summary.skipped_invalid_reviews}")


if __name__ == "__main__":
    main()
