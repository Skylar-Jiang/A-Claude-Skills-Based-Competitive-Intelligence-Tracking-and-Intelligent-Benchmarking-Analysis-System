from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.background.contracts import (
    BackgroundEvidence,
    BackgroundQuery,
    BackgroundResult,
)
from app.background.registry import BackgroundProviderRegistry
from app.core.config import Settings
from app.core.enums import DataMode, DataOrigin
from app.db.base import Base
from app.db.repositories.sqlalchemy import SqlAlchemyProductRepository
from app.rag.in_memory import InMemoryKnowledgeStore
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.product import ProductCreate
from app.services.analysis_service import AnalysisService


class RecordingProvider:
    name = "recording-provider"

    def __init__(self) -> None:
        self.queries: list[BackgroundQuery] = []

    def query(self, query: BackgroundQuery) -> BackgroundResult:
        self.queries.append(query)
        return BackgroundResult(
            provider=self.name,
            query=query,
            evidence=[
                BackgroundEvidence(
                    evidence_id="background-1",
                    context_type="platform_policy",
                    content="Fixture-only platform context.",
                    source_name="Fake source",
                    source_uri="fixture://background-1",
                    effective_date=date(2026, 7, 1),
                    jurisdiction="US",
                    confidence=0.9,
                )
            ],
        )


def test_fake_background_provider_is_queried_once_and_persisted_with_provenance(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    provider = RecordingProvider()
    registry = BackgroundProviderRegistry()
    registry.register(provider)
    with Session(engine) as session:
        product = SqlAlchemyProductRepository(session).create(
            ProductCreate(
                name="Unlisted fountain",
                category="pet water fountain",
                target_market="United States",
                data_mode=DataMode.DEMO,
            ),
            data_origin=DataOrigin.DEMO,
        )
        service = AnalysisService(
            session=session,
            knowledge_store=InMemoryKnowledgeStore(),
            report_dir=tmp_path,
            settings=Settings(_env_file=None, database_url="sqlite://"),
            background_registry=registry,
        )
        run = service.start(
            AnalysisRunCreate(
                product_id=product.product_id,
                data_mode=DataMode.DEMO,
                target_market="United States",
                jurisdiction="US",
                platform="Amazon",
                background_context_types=["platform_policy"],
                effective_date=date(2026, 7, 1),
                query_date=date(2026, 7, 15),
                user_constraints={"launch_window": "Q4"},
            )
        )

    assert len(provider.queries) == 1
    query = provider.queries[0]
    assert query.product_name == "Unlisted fountain"
    assert query.product_type == "pet water fountain"
    assert query.platform == "Amazon"
    assert query.user_constraints == {"launch_window": "Q4"}
    assert run.state["background_context"]["provider"] == "recording-provider"
    assert any(item["evidence_id"] == "background-1" for item in run.state["rag_evidence"])


def test_no_background_provider_keeps_context_empty(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        product = SqlAlchemyProductRepository(session).create(
            ProductCreate(name="No provider", category="fountain", data_mode=DataMode.DEMO),
            data_origin=DataOrigin.DEMO,
        )
        service = AnalysisService(
            session=session,
            knowledge_store=InMemoryKnowledgeStore(),
            report_dir=tmp_path,
            settings=Settings(_env_file=None, database_url="sqlite://"),
        )
        run = service.start(AnalysisRunCreate(product_id=product.product_id, data_mode=DataMode.DEMO))

    assert run.state["background_context"] is None
