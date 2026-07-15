from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.enums import AgentStatus, DataMode, DataOrigin
from app.db.base import Base
from app.db.models.core import CompetitorOffer, KnowledgeSource, Product
from app.schemas.product import ProductCreate, ProductProfile
from app.statistics.providers.pet_supplies import PetSuppliesStatisticsProvider


def test_pet_supplies_provider_returns_sql_backed_metrics() -> None:
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
                name="Reflective Dog Harness",
                category="Harnesses",
                data_mode="real",
                data_origin="real",
                attributes_json={"parent_asin": "PARENT-1"},
                metadata_json={"source_file": "data/filtered/meta_pet_supplies_prefiltered.jsonl"},
                payload_json={},
            )
        )
        session.add(
            CompetitorOffer(
                offer_id="offer-1",
                product_id="pet-product-1",
                data_origin="real",
                attributes_json={"price": "24.95", "average_rating": "4.4", "rating_number": 166},
            )
        )
        session.add(
            KnowledgeSource(
                source_id="knowledge-1",
                product_id="pet-product-1",
                knowledge_type="product_knowledge",
                content="Title: Reflective Dog Harness",
                data_origin="real",
                metadata_json={"source_name": "Reflective Dog Harness"},
            )
        )
        session.commit()

        product = ProductProfile(
            product_id="pet-product-1",
            data_origin=DataOrigin.REAL,
            **ProductCreate(
                name="Reflective Dog Harness",
                category="Harnesses",
                data_mode=DataMode.REAL,
            ).model_dump(),
        )

        result = PetSuppliesStatisticsProvider(session).get_statistics(product=product)

        assert result.status is AgentStatus.SUCCEEDED
        assert result.product_id == "pet-product-1"
        assert result.data_origin is DataOrigin.REAL
        assert result.metrics["offer_count"] == Decimal("1")
        assert result.metrics["priced_offer_count"] == Decimal("1")
        assert result.metrics["avg_price"] == Decimal("24.95")
        assert result.metrics["min_price"] == Decimal("24.95")
        assert result.metrics["max_price"] == Decimal("24.95")
        assert result.metrics["avg_rating"] == Decimal("4.4")
        assert result.metrics["total_rating_count"] == Decimal("166")
        assert result.evidence_ids == ["knowledge-1"]


def test_pet_supplies_provider_returns_peer_group_statistics_for_unlisted_product() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for index, (price, rating, rating_number) in enumerate(
            [("20", "4.0", 100), ("30", "4.5", 200), (None, "5.0", 300)]
        ):
            product_id = f"peer-{index}"
            session.add(
                Product(
                    product_id=product_id,
                    name=f"Listed peer {index}",
                    category="Fountains",
                    data_mode="real",
                    data_origin="real",
                    attributes_json={"peer_group_id": "peer-group-1"},
                    metadata_json={"peer_group_id": "peer-group-1"},
                    payload_json={},
                )
            )
            session.add(
                CompetitorOffer(
                    offer_id=f"offer-{index}",
                    product_id=product_id,
                    data_origin="real",
                    attributes_json={
                        "peer_group_id": "peer-group-1",
                        "price": price,
                        "average_rating": rating,
                        "rating_number": rating_number,
                    },
                )
            )
            session.add(
                KnowledgeSource(
                    source_id=f"knowledge-{index}",
                    product_id=product_id,
                    knowledge_type="product_knowledge",
                    content=f"Listed peer {index}",
                    data_origin="real",
                    metadata_json={"peer_group_id": "peer-group-1"},
                )
            )
        session.commit()
        new_product = ProductProfile(
            product_id="unlisted-product",
            data_origin=DataOrigin.USER,
            **ProductCreate(
                name="New Cat Fountain",
                category="Fountains",
                data_mode=DataMode.REAL,
            ).model_dump(),
        )

        result = PetSuppliesStatisticsProvider(session).get_statistics(
            product=new_product,
            peer_group_id="peer-group-1",
        )

        assert result.status is AgentStatus.SUCCEEDED
        assert result.data_origin is DataOrigin.REAL
        assert result.metrics == {
            "peer_product_count": Decimal("3"),
            "priced_product_count": Decimal("2"),
            "min_price": Decimal("20"),
            "max_price": Decimal("30"),
            "avg_price": Decimal("25"),
            "median_price": Decimal("25"),
            "avg_rating": Decimal("4.5"),
            "total_rating_number": Decimal("600"),
        }
        assert set(result.evidence_ids) == {"knowledge-0", "knowledge-1", "knowledge-2"}
