from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.enums import AuditStatus, DataMode, DataOrigin, ImplementationStatus
from app.db.base import Base
from app.db.models.core import Report
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository, SqlAlchemyProductRepository
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.common import utc_now
from app.schemas.product import ProductCreate
from app.schemas.report import FinalReport


def _report(report_id: str, run_id: str, version: int, path: Path, **updates) -> FinalReport:  # type: ignore[no-untyped-def]
    return FinalReport(
        report_id=report_id,
        run_id=run_id,
        version=version,
        audit_status=AuditStatus.PASS,
        data_origin=DataOrigin.USER,
        implementation_status=ImplementationStatus.PRODUCTION,
        is_demo=False,
        disclaimer="evidence grounded",
        sections={"new_product_overview": {"name": "new product"}},
        markdown_path=str(path.with_suffix(".md")),
        json_path=str(path.with_suffix(".json")),
        created_at=utc_now(),
        **updates,
    )


def test_report_versions_are_immutable_ordered_snapshots_with_lineage(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        product = SqlAlchemyProductRepository(session).create(
            ProductCreate(name="Version fixture", category="fountain", data_mode=DataMode.REAL),
            data_origin=DataOrigin.USER,
        )
        repository = SqlAlchemyAnalysisRepository(session)
        run = repository.create_run(
            AnalysisRunCreate(product_id=product.product_id, data_mode=DataMode.REAL)
        )
        first = _report("report-v1", run.run_id, 1, tmp_path / "v1")
        second = _report(
            "report-v2",
            run.run_id,
            2,
            tmp_path / "v2",
            parent_report_id=first.report_id,
            changed_section_ids=["prelaunch-considerations"],
        )
        for report in (first, second):
            session.add(
                Report(
                    report_id=report.report_id,
                    run_id=run.run_id,
                    version=report.version,
                    parent_report_id=report.parent_report_id,
                    changed_section_ids_json=report.changed_section_ids,
                    change_json={},
                    format="json+markdown",
                    file_path=report.json_path,
                    is_demo=False,
                    metadata_json=report.model_dump(mode="json"),
                )
            )
        session.commit()

        versions = repository.list_report_versions(run.run_id)
        latest = repository.get_latest_report(run.run_id)
        historical = repository.get_report(first.report_id)

    assert [item.version for item in versions] == [1, 2]
    assert latest.report_id == "report-v2"
    assert latest.parent_report_id == "report-v1"
    assert latest.changed_section_ids == ["prelaunch-considerations"]
    assert historical.report_id == "report-v1"
