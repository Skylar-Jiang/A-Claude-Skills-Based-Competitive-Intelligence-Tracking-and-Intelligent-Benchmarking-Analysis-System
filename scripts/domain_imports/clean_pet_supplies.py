import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.enums import DataOrigin, KnowledgeType  # noqa: E402
from app.db.migrations import upgrade_database  # noqa: E402
from app.db.models.core import CompetitorOffer, KnowledgeSource, Product, Review  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


@dataclass(slots=True)
class CleanSummary:
    scanned_products: int = 0
    updated_products: int = 0
    scanned_offers: int = 0
    updated_offers: int = 0
    scanned_reviews: int = 0
    updated_reviews: int = 0
    scanned_knowledge_sources: int = 0
    updated_knowledge_sources: int = 0


@dataclass(slots=True)
class ProgressTracker:
    label: str
    total_items: int
    interval: int = 10000
    processed_items: int = 0
    started_at: float = 0.0

    def start(self) -> None:
        self.started_at = perf_counter()

    def advance(self) -> None:
        self.processed_items += 1
        if self.processed_items == 1 or self.processed_items % self.interval == 0:
            self.render()

    def render(self, *, final: bool = False) -> None:
        percent = 0.0 if self.total_items == 0 else min(self.processed_items / self.total_items, 1.0)
        filled = int(percent * 20)
        bar = "#" * filled + "-" * (20 - filled)
        elapsed = max(perf_counter() - self.started_at, 0.001)
        rate = self.processed_items / elapsed
        suffix = "\n" if final else "\r"
        print(
            f"{self.label}: [{bar}] {percent * 100:6.2f}% "
            f"items={self.processed_items}/{self.total_items} rate={rate:,.1f}/s",
            end=suffix,
            flush=True,
        )


def _count_records(session: Session, model: type[object], *, extra_filters: tuple[object, ...] = ()) -> int:
    statement = (
        select(func.count())
        .select_from(model)
        .where(model.data_origin == DataOrigin.REAL.value, *extra_filters)
    )
    return int(session.scalar(statement) or 0)


def _has_non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_text(value: object, *, limit: int | None = None) -> str:
    if isinstance(value, str):
        normalized = " ".join(value.split())
    else:
        normalized = ""
    if limit is not None:
        return normalized[:limit]
    return normalized


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _normalize_text(item)
        if text:
            normalized.append(text)
    return normalized


def _normalize_categories(value: object) -> list[str]:
    categories = _normalize_string_list(value)
    deduped: list[str] = []
    for category in categories:
        if category not in deduped:
            deduped.append(category)
    return deduped


def _normalize_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, str):
            normalized[key] = _normalize_text(item)
        else:
            normalized[key] = item
    return normalized


def _normalize_decimal(value: object) -> str | None:
    if value is None or value == "":
        return None
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _normalize_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_bool(value: object) -> bool:
    return bool(value)


def _extract_materials(details: dict[str, object]) -> list[str]:
    material = details.get("Material")
    if not _has_non_empty_text(material):
        return []
    return [_normalize_text(material)]


def _extract_dimensions(details: dict[str, object]) -> dict[str, object]:
    dimensions: dict[str, object] = {}
    product_dimensions = _normalize_text(details.get("Product Dimensions"))
    package_dimensions = _normalize_text(details.get("Package Dimensions"))
    if product_dimensions:
        dimensions["product_dimensions"] = product_dimensions
    if package_dimensions:
        dimensions["package_dimensions"] = package_dimensions
    return dimensions


def _extract_target_audience(categories: list[str], details: dict[str, object]) -> list[str]:
    audience: list[str] = []
    if len(categories) > 1:
        audience.append(categories[1])
    target_species = details.get("Target Species")
    if _has_non_empty_text(target_species):
        for part in str(target_species).split(","):
            normalized = _normalize_text(part)
            if normalized and normalized not in audience:
                audience.append(normalized)
    return audience


def _derive_species(categories: list[str], details: dict[str, object]) -> list[str]:
    species: list[str] = []
    if len(categories) > 1 and categories[1] not in species:
        species.append(categories[1])
    target_species = details.get("Target Species")
    if _has_non_empty_text(target_species):
        for part in str(target_species).split(","):
            normalized = _normalize_text(part)
            if normalized and normalized not in species:
                species.append(normalized)
    return species


def _build_product_knowledge_content_from_payload(payload: dict[str, object]) -> str:
    title = _normalize_text(payload.get("name"))
    features = _normalize_string_list(payload.get("features"))
    description = _normalize_text(payload.get("description"))
    attributes = _normalize_dict(payload.get("attributes"))
    details = _normalize_dict(attributes.get("details"))

    sections = [f"Title: {title}"] if title else []
    if features:
        sections.append("Features:\n- " + "\n- ".join(features))
    if description:
        sections.append(f"Description:\n{description}")
    if details:
        detail_lines = [f"{key}: {value}" for key, value in details.items() if _has_non_empty_text(value)]
        if detail_lines:
            sections.append("Details:\n- " + "\n- ".join(detail_lines))
    return "\n\n".join(sections)


def clean_products(session: Session, summary: CleanSummary) -> None:
    statement = select(Product).where(Product.data_origin == DataOrigin.REAL.value)
    total = _count_records(session, Product)
    tracker = ProgressTracker(label="clean_products", total_items=total, interval=5000)
    tracker.start()
    for product in session.scalars(statement):
        tracker.advance()
        summary.scanned_products += 1
        payload = _normalize_dict(product.payload_json)
        base_attributes = _normalize_dict(product.attributes_json)
        payload_attributes = _normalize_dict(payload.get("attributes"))
        attributes = {**base_attributes, **payload_attributes}
        details = _normalize_dict(attributes.get("details"))
        categories = _normalize_categories(attributes.get("categories"))
        brand = _normalize_text(details.get("Brand")) or _normalize_text(attributes.get("brand")) or _normalize_text(
            attributes.get("store")
        )
        price = _normalize_decimal(attributes.get("price") or payload.get("target_price"))
        average_rating = _normalize_decimal(attributes.get("average_rating"))
        rating_number = _normalize_int(attributes.get("rating_number"))
        image_count = _normalize_int(attributes.get("image_count")) or 0
        video_count = _normalize_int(attributes.get("video_count")) or 0

        normalized_attributes = {
            **attributes,
            "parent_asin": _normalize_text(attributes.get("parent_asin")),
            "store": _normalize_text(attributes.get("store")),
            "brand": brand,
            "main_category": _normalize_text(attributes.get("main_category")) or "Pet Supplies",
            "categories": categories,
            "details": details,
            "image_count": image_count,
            "video_count": video_count,
            "price": price,
            "average_rating": average_rating,
            "rating_number": rating_number,
            "species": _derive_species(categories, details),
            "subcategory_path": categories[1:] if len(categories) > 1 else [],
        }

        normalized_category = (
            _normalize_text(payload.get("category") or product.category, limit=120) or "pet-supplies"
        )[:120]

        normalized_payload = {
            "name": _normalize_text(payload.get("name") or product.name, limit=200),
            "category": normalized_category,
            "description": _normalize_text(payload.get("description")),
            "attributes": normalized_attributes,
            "materials": _extract_materials(details),
            "dimensions": _extract_dimensions(details),
            "features": _normalize_string_list(payload.get("features")),
            "use_scenarios": _normalize_string_list(payload.get("use_scenarios")),
            "target_market": _normalize_text(payload.get("target_market")) or "amazon_us",
            "target_audience": _extract_target_audience(categories, details),
            "target_price": price,
            "target_currency": "USD" if price is not None else None,
            "known_risks": _normalize_string_list(payload.get("known_risks")),
            "data_mode": payload.get("data_mode") or product.data_mode,
        }

        normalized_metadata = {
            **_normalize_dict(product.metadata_json),
            "clean_stage": "pet_supplies_normalized",
        }

        changed = (
            product.name != normalized_payload["name"]
            or product.category != normalized_payload["category"]
            or product.attributes_json != normalized_attributes
            or product.payload_json != normalized_payload
            or product.metadata_json != normalized_metadata
        )
        if changed:
            product.name = normalized_payload["name"]
            product.category = normalized_payload["category"]
            product.attributes_json = normalized_attributes
            product.payload_json = normalized_payload
            product.metadata_json = normalized_metadata
            summary.updated_products += 1
    tracker.render(final=True)


def clean_offers(session: Session, summary: CleanSummary) -> None:
    statement = select(CompetitorOffer).where(CompetitorOffer.data_origin == DataOrigin.REAL.value)
    total = _count_records(session, CompetitorOffer)
    tracker = ProgressTracker(label="clean_offers", total_items=total, interval=5000)
    tracker.start()
    for offer in session.scalars(statement):
        tracker.advance()
        summary.scanned_offers += 1
        attributes = _normalize_dict(offer.attributes_json)
        categories = _normalize_categories(attributes.get("categories"))
        normalized = {
            **attributes,
            "parent_asin": _normalize_text(attributes.get("parent_asin")),
            "store": _normalize_text(attributes.get("store")),
            "brand": _normalize_text(attributes.get("brand")) or _normalize_text(attributes.get("store")),
            "main_category": _normalize_text(attributes.get("main_category")) or "Pet Supplies",
            "categories": categories,
            "price": _normalize_decimal(attributes.get("price")),
            "average_rating": _normalize_decimal(attributes.get("average_rating")),
            "rating_number": _normalize_int(attributes.get("rating_number")),
            "subcategory_path": categories[1:] if len(categories) > 1 else [],
        }
        if offer.attributes_json != normalized:
            offer.attributes_json = normalized
            summary.updated_offers += 1
    tracker.render(final=True)


def clean_reviews(session: Session, summary: CleanSummary) -> None:
    statement = select(Review).where(Review.data_origin == DataOrigin.REAL.value)
    total = _count_records(session, Review)
    tracker = ProgressTracker(label="clean_reviews", total_items=total, interval=50000)
    tracker.start()
    for review in session.scalars(statement):
        tracker.advance()
        summary.scanned_reviews += 1
        metadata = _normalize_dict(review.metadata_json)
        normalized_content = _normalize_text(review.content)
        normalized_metadata = {
            **metadata,
            "review_title": _normalize_text(metadata.get("review_title")),
            "asin": _normalize_text(metadata.get("asin")),
            "parent_asin": _normalize_text(metadata.get("parent_asin")),
            "user_id": _normalize_text(metadata.get("user_id")),
            "helpful_vote": _normalize_int(metadata.get("helpful_vote")) or 0,
            "verified_purchase": _normalize_bool(metadata.get("verified_purchase")),
            "rating": _normalize_decimal(metadata.get("rating")),
            "image_count": _normalize_int(metadata.get("image_count")) or 0,
            "clean_stage": "pet_supplies_normalized",
        }
        if review.content != normalized_content or review.metadata_json != normalized_metadata:
            review.content = normalized_content
            review.metadata_json = normalized_metadata
            summary.updated_reviews += 1
    tracker.render(final=True)


def clean_product_knowledge_sources(session: Session, summary: CleanSummary) -> None:
    statement = select(KnowledgeSource).where(
        KnowledgeSource.data_origin == DataOrigin.REAL.value,
        KnowledgeSource.knowledge_type == KnowledgeType.PRODUCT_KNOWLEDGE.value,
    )
    total = _count_records(
        session,
        KnowledgeSource,
        extra_filters=(KnowledgeSource.knowledge_type == KnowledgeType.PRODUCT_KNOWLEDGE.value,),
    )
    tracker = ProgressTracker(label="clean_knowledge", total_items=total, interval=5000)
    tracker.start()
    for source in session.scalars(statement):
        tracker.advance()
        summary.scanned_knowledge_sources += 1
        product = session.get(Product, source.product_id) if source.product_id else None
        source_metadata = _normalize_dict(source.metadata_json)
        normalized_metadata = {
            **source_metadata,
            "source_name": _normalize_text(source_metadata.get("source_name")),
            "parent_asin": _normalize_text(source_metadata.get("parent_asin")),
            "clean_stage": "pet_supplies_normalized",
        }
        normalized_content = source.content
        if product is not None:
            normalized_content = _build_product_knowledge_content_from_payload(_normalize_dict(product.payload_json))
            if not normalized_metadata["source_name"]:
                normalized_metadata["source_name"] = product.name
            if not normalized_metadata["parent_asin"]:
                normalized_metadata["parent_asin"] = _normalize_text(product.attributes_json.get("parent_asin"))
        if source.content != normalized_content or source.metadata_json != normalized_metadata:
            source.content = normalized_content
            source.metadata_json = normalized_metadata
            summary.updated_knowledge_sources += 1
    tracker.render(final=True)


def clean_pet_supplies(session: Session) -> CleanSummary:
    summary = CleanSummary()
    clean_products(session, summary)
    clean_offers(session, summary)
    clean_reviews(session, summary)
    clean_product_knowledge_sources(session, summary)
    session.commit()
    return summary


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Normalize imported pet supplies records in the TradePilot database.")


def main() -> None:
    build_parser().parse_args()
    settings = get_settings()
    upgrade_database(settings.database_url)
    print("clean_pet_supplies: starting", flush=True)
    with SessionLocal() as session:
        print("clean_pet_supplies: session opened", flush=True)
        summary = clean_pet_supplies(session)

    print("clean_pet_supplies: finished", flush=True)
    print(f"scanned_products={summary.scanned_products}")
    print(f"updated_products={summary.updated_products}")
    print(f"scanned_offers={summary.scanned_offers}")
    print(f"updated_offers={summary.updated_offers}")
    print(f"scanned_reviews={summary.scanned_reviews}")
    print(f"updated_reviews={summary.updated_reviews}")
    print(f"scanned_knowledge_sources={summary.scanned_knowledge_sources}")
    print(f"updated_knowledge_sources={summary.updated_knowledge_sources}")


if __name__ == "__main__":
    main()
