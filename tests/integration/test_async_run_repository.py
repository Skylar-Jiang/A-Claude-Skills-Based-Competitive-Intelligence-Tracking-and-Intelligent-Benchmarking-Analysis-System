from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.enums import DataMode, DataOrigin, RunStageStatus
from app.db.base import Base
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository, SqlAlchemyProductRepository
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.product import ProductCreate


def _engine():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _run(session: Session) -> tuple[SqlAlchemyAnalysisRepository, str]:
    product = SqlAlchemyProductRepository(session).create(
        ProductCreate(name="Unlisted fountain", category="pet water fountain", data_mode=DataMode.REAL),
        data_origin=DataOrigin.USER,
    )
    repository = SqlAlchemyAnalysisRepository(session)
    run = repository.create_run(AnalysisRunCreate(product_id=product.product_id, data_mode=DataMode.REAL))
    return repository, run.run_id


def test_stages_and_events_are_ordered_and_replayable_after_event_id() -> None:
    engine = _engine()
    with Session(engine) as session:
        repository, run_id = _run(session)
        repository.initialize_stages(run_id, ["product_preparation", "peer_matching", "report_export"])
        repository.transition_stage(run_id, "product_preparation", RunStageStatus.RUNNING)
        started = repository.append_event(
            run_id,
            event_type="stage_started",
            stage_key="product_preparation",
            payload={"label": "Preparing product"},
        )
        repository.transition_stage(
            run_id,
            "product_preparation",
            RunStageStatus.SUCCEEDED,
            payload={"duration_ms": 12},
        )
        completed = repository.append_event(
            run_id,
            event_type="stage_completed",
            stage_key="product_preparation",
            payload={"duration_ms": 12},
        )

        assert completed.event_id > started.event_id
        assert [item.stage_key for item in repository.list_stages(run_id)] == [
            "product_preparation",
            "peer_matching",
            "report_export",
        ]
        assert [item.event_id for item in repository.list_events(run_id, after_event_id=started.event_id)] == [
            completed.event_id
        ]


def test_failure_payload_and_event_survive_a_new_database_session() -> None:
    engine = _engine()
    with Session(engine) as first:
        repository, run_id = _run(first)
        repository.initialize_stages(run_id, ["peer_matching"])
        repository.transition_stage(
            run_id,
            "peer_matching",
            RunStageStatus.FAILED,
            error={"code": "no_qualified_peers", "message": "No candidates passed the threshold"},
        )
        event = repository.append_event(
            run_id,
            event_type="workflow_failed",
            stage_key="peer_matching",
            payload={"error_code": "no_qualified_peers"},
        )

    with Session(engine) as second:
        repository = SqlAlchemyAnalysisRepository(second)
        stage = repository.list_stages(run_id)[0]
        replay = repository.list_events(run_id, after_event_id=0)

        assert stage.status is RunStageStatus.FAILED
        assert stage.error == {
            "code": "no_qualified_peers",
            "message": "No candidates passed the threshold",
        }
        assert replay[0].event_id == event.event_id
        assert replay[0].payload == {"error_code": "no_qualified_peers"}


def test_stage_and_event_writes_do_not_leave_an_implicit_read_transaction_open() -> None:
    engine = _engine()
    with Session(engine) as session:
        repository, run_id = _run(session)
        repository.initialize_stages(run_id, ["peer_matching"])
        session.rollback()

        repository.transition_stage(run_id, "peer_matching", RunStageStatus.RUNNING)
        assert session.in_transaction() is False

        repository.append_event(run_id, event_type="peer_selection_started")
        assert session.in_transaction() is False


def test_current_node_can_advance_without_replacing_persisted_run_state() -> None:
    engine = _engine()
    with Session(engine) as session:
        repository, run_id = _run(session)
        repository.update_run(
            run_id,
            status=repository.get_run(run_id).status,
            current_node="product_preparation",
            retry_count=0,
            state={"preserved": True},
        )

        repository.set_current_node(run_id, "evidence_audit_agent")
        run = repository.get_run(run_id)

    assert run.current_node == "evidence_audit_agent"
    assert run.state == {"preserved": True}
