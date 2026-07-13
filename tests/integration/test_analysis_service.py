from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.adapters.demo import DemoDomainAdapter
from app.core.config import Settings
from app.core.enums import DataMode, RunStatus
from app.db.base import Base
from app.db.models.core import AgentOutput, EvidenceReferenceRecord, Report
from app.db.repositories.sqlalchemy import SqlAlchemyProductRepository
from app.rag.in_memory import InMemoryKnowledgeStore
from app.schemas.analysis import AnalysisRunCreate
from app.services.analysis_service import AnalysisService


def test_analysis_service_persists_four_outputs_evidence_state_and_report(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = InMemoryKnowledgeStore()
        product = DemoDomainAdapter().seed(
            session, SqlAlchemyProductRepository(session), store
        )
        service = AnalysisService(
            session=session,
            knowledge_store=store,
            report_dir=tmp_path,
            settings=Settings(_env_file=None, database_url="sqlite://"),
        )

        run = service.start(
            AnalysisRunCreate(product_id=product.product_id, data_mode=DataMode.DEMO)
        )

        assert run.status is RunStatus.SUCCEEDED
        assert run.report_id is not None
        assert run.state["current_node"] == "persist_and_export"
        assert run.state["report_id"] == run.report_id
        assert run.state["report_paths"]["json"].endswith(".json")
        assert set(run.state["node_status"]) == {
            "input_validator",
            "product_normalizer",
            "product_market_agent",
            "user_insight_agent",
            "operations_decision_agent",
            "evidence_audit_agent",
            "persist_and_export",
        }
        assert session.scalar(select(func.count()).select_from(AgentOutput)) == 4
        assert session.scalar(select(func.count()).select_from(EvidenceReferenceRecord)) == 2
        assert session.scalar(select(func.count()).select_from(Report)) == 1
        report = service.get_report(run.report_id)
        assert Path(report.json_path).exists()
        assert report.is_demo is True
