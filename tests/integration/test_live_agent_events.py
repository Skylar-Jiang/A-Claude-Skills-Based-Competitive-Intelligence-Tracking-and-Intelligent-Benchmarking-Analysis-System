from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.enums import DataMode, DataOrigin
from app.db.base import Base
from app.db.repositories.sqlalchemy import SqlAlchemyProductRepository
from app.rag.in_memory import InMemoryKnowledgeStore
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.product import ProductCreate
from app.services.analysis_service import AnalysisService


def test_workflow_persists_agent_started_and_completed_events_during_execution(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        product = SqlAlchemyProductRepository(session).create(
            ProductCreate(name="Event fixture", category="demo", data_mode=DataMode.DEMO),
            data_origin=DataOrigin.DEMO,
        )
        service = AnalysisService(
            session=session,
            knowledge_store=InMemoryKnowledgeStore(),
            report_dir=tmp_path,
            settings=Settings(_env_file=None, database_url="sqlite://"),
        )
        run = service.start(AnalysisRunCreate(product_id=product.product_id, data_mode=DataMode.DEMO))
        events = service.list_events(run.run_id)

    agent_events = [event for event in events if event.event_type.startswith("agent_")]
    assert {(event.event_type, event.stage_key) for event in agent_events} == {
        ("agent_started", "product_market_agent"),
        ("agent_completed", "product_market_agent"),
        ("agent_started", "user_insight_agent"),
        ("agent_completed", "user_insight_agent"),
        ("agent_started", "operations_decision_agent"),
        ("agent_completed", "operations_decision_agent"),
        ("agent_started", "evidence_audit_agent"),
        ("agent_completed", "evidence_audit_agent"),
    }
    assert all(event.payload.get("status") in {"running", "succeeded"} for event in agent_events)
