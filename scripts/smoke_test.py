import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.adapters.demo import DemoDomainAdapter  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.enums import DataMode, RunStatus  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models.core import AgentOutput, EvidenceReferenceRecord, Report  # noqa: E402
from app.db.repositories.sqlalchemy import SqlAlchemyProductRepository  # noqa: E402
from app.rag.in_memory import InMemoryKnowledgeStore  # noqa: E402
from app.schemas.analysis import AnalysisRunCreate  # noqa: E402
from app.services.analysis_service import AnalysisService  # noqa: E402


def main() -> None:
    with TemporaryDirectory(prefix="tradepilot-smoke-") as temp:
        root = Path(temp)
        engine = create_engine(f"sqlite:///{root / 'smoke.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            store = InMemoryKnowledgeStore()
            product = DemoDomainAdapter().seed(
                session,
                SqlAlchemyProductRepository(session),
                store,
            )
            service = AnalysisService(
                session=session,
                knowledge_store=store,
                report_dir=root / "reports",
                settings=Settings(
                    _env_file=None,
                    database_url=f"sqlite:///{root / 'smoke.db'}",
                ),
            )
            run = service.start(
                AnalysisRunCreate(product_id=product.product_id, data_mode=DataMode.DEMO)
            )
            report = service.get_report(run.report_id or "")
            json_payload = json.loads(Path(report.json_path).read_text(encoding="utf-8"))
            markdown = Path(report.markdown_path).read_text(encoding="utf-8")
            counts = {
                "agent_outputs": session.scalar(select(func.count()).select_from(AgentOutput)),
                "evidence_references": session.scalar(
                    select(func.count()).select_from(EvidenceReferenceRecord)
                ),
                "reports": session.scalar(select(func.count()).select_from(Report)),
            }
            assert run.status is RunStatus.SUCCEEDED
            assert counts == {"agent_outputs": 4, "evidence_references": 2, "reports": 1}
            assert json_payload["data_origin"] == "demo"
            assert json_payload["implementation_status"] == "scaffold"
            assert "DEMO" in markdown and "Scaffold" in markdown
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "data_origin": "demo",
                        "implementation_status": "scaffold",
                        "product_id": product.product_id,
                        "run_id": run.run_id,
                        "report_id": report.report_id,
                        **counts,
                    },
                    ensure_ascii=False,
                )
            )
        engine.dispose()


if __name__ == "__main__":
    main()
