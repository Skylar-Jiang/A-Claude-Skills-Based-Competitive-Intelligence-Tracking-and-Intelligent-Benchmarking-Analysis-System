from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.adapters.demo import DemoDomainAdapter
from app.db.base import Base
from app.db.models.core import CompetitorOffer, KnowledgeSource, Review
from app.db.repositories.sqlalchemy import SqlAlchemyProductRepository
from app.rag.in_memory import InMemoryKnowledgeStore


def test_demo_seed_is_marked_and_idempotent() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = InMemoryKnowledgeStore()
        adapter = DemoDomainAdapter()
        product = adapter.seed(session, SqlAlchemyProductRepository(session), store)
        repeated = adapter.seed(session, SqlAlchemyProductRepository(session), store)

        assert product.product_id == repeated.product_id
        assert product.is_demo is True
        assert session.scalar(select(func.count()).select_from(CompetitorOffer)) == 3
        assert session.scalar(select(func.count()).select_from(Review)) == 10
        assert session.scalar(select(func.count()).select_from(KnowledgeSource)) == 2
        assert len(store.documents) == 2
