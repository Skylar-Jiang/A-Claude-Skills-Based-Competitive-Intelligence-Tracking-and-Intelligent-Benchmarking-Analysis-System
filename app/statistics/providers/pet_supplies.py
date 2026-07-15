from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AgentStatus, DataOrigin
from app.db.models.core import CompetitorOffer, KnowledgeSource, Product
from app.schemas.common import DataGap
from app.schemas.product import ProductProfile
from app.statistics.contracts import StatisticsResult
from app.statistics.stub import ScaffoldStatisticsProvider

PET_METADATA_SOURCE_FILE = "data/filtered/meta_pet_supplies_prefiltered.jsonl"


def _to_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


class PetSuppliesStatisticsProvider:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.fallback = ScaffoldStatisticsProvider()

    def get_statistics(self, *, product: ProductProfile) -> StatisticsResult:
        if product.data_origin is not DataOrigin.REAL:
            return self.fallback.get_statistics(product=product)

        record = self.session.get(Product, product.product_id)
        if record is None:
            return self.fallback.get_statistics(product=product)

        metadata = record.metadata_json if isinstance(record.metadata_json, dict) else {}
        if metadata.get("source_file") != PET_METADATA_SOURCE_FILE:
            return self.fallback.get_statistics(product=product)

        offers = self.session.scalars(
            select(CompetitorOffer).where(CompetitorOffer.product_id == product.product_id)
        ).all()
        evidence_ids = [
            source_id
            for source_id in self.session.scalars(
                select(KnowledgeSource.source_id).where(KnowledgeSource.product_id == product.product_id)
            ).all()
        ]

        prices = [_to_decimal((offer.attributes_json or {}).get("price")) for offer in offers]
        prices = [price for price in prices if price is not None]
        ratings = [_to_decimal((offer.attributes_json or {}).get("average_rating")) for offer in offers]
        ratings = [rating for rating in ratings if rating is not None]
        rating_counts = [
            Decimal(str((offer.attributes_json or {}).get("rating_number")))
            for offer in offers
            if (offer.attributes_json or {}).get("rating_number") is not None
        ]

        if not offers:
            return StatisticsResult(
                product_id=product.product_id,
                status=AgentStatus.INSUFFICIENT_EVIDENCE,
                data_origin=product.data_origin,
                evidence_ids=evidence_ids,
                data_gaps=[
                    DataGap(
                        code="pet_supplies_offers_missing",
                        field="competitor_offers",
                        reason="No pet supplies offers exist for this imported product.",
                        required_for="statistics computation",
                    )
                ],
            )

        metrics: dict[str, Decimal] = {
            "offer_count": Decimal(len(offers)),
            "priced_offer_count": Decimal(len(prices)),
            "total_rating_count": sum(rating_counts, Decimal("0")),
        }
        if prices:
            metrics["avg_price"] = sum(prices, Decimal("0")) / Decimal(len(prices))
            metrics["min_price"] = min(prices)
            metrics["max_price"] = max(prices)
        if ratings:
            metrics["avg_rating"] = sum(ratings, Decimal("0")) / Decimal(len(ratings))

        return StatisticsResult(
            product_id=product.product_id,
            status=AgentStatus.SUCCEEDED,
            data_origin=product.data_origin,
            metrics=metrics,
            evidence_ids=evidence_ids,
        )
