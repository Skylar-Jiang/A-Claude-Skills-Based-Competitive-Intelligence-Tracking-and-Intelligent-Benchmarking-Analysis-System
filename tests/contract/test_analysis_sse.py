import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.enums import DataMode, DataOrigin, RunStatus
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository, SqlAlchemyProductRepository
from app.main import create_app
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.product import ProductCreate


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'sse.db'}",
        report_dir=tmp_path / "reports",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        sse_poll_interval_seconds=0.01,
        sse_heartbeat_seconds=0.02,
    )
    return TestClient(create_app(settings))


def _persist_completed_run(client: TestClient) -> tuple[str, list[int]]:
    with client.app.state.session_factory() as session:
        product = SqlAlchemyProductRepository(session).create(
            ProductCreate(name="SSE fixture", category="demo", data_mode=DataMode.DEMO),
            data_origin=DataOrigin.DEMO,
        )
        repository = SqlAlchemyAnalysisRepository(session)
        run = repository.create_run(
            AnalysisRunCreate(product_id=product.product_id, data_mode=DataMode.DEMO)
        )
        first = repository.append_event(
            run.run_id,
            event_type="stage_started",
            stage_key="product_preparation",
            payload={"status": "running"},
        )
        second = repository.append_event(
            run.run_id,
            event_type="agent_completed",
            stage_key="product_market_agent",
            payload={"status": "succeeded", "duration_ms": 50},
        )
        third = repository.append_event(
            run.run_id,
            event_type="workflow_completed",
            payload={"status": "succeeded"},
        )
        repository.update_run(
            run.run_id,
            status=RunStatus.SUCCEEDED,
            current_node="persist_and_export",
            retry_count=0,
            state={},
        )
    return run.run_id, [first.event_id, second.event_id, third.event_id]


def test_sse_uses_persisted_monotonic_ids_and_closes_after_terminal_event(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        run_id, event_ids = _persist_completed_run(client)
        response = client.get(f"/api/v1/analysis-runs/{run_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [int(value) for value in re.findall(r"^id: (\d+)$", response.text, re.MULTILINE)] == event_ids
    assert "event: stage_started" in response.text
    assert "event: agent_completed" in response.text
    assert "event: workflow_completed" in response.text


def test_sse_last_event_id_replays_only_later_events_without_duplicates(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        run_id, event_ids = _persist_completed_run(client)
        response = client.get(
            f"/api/v1/analysis-runs/{run_id}/events",
            headers={"Last-Event-ID": str(event_ids[0])},
        )

    replayed = [int(value) for value in re.findall(r"^id: (\d+)$", response.text, re.MULTILINE)]
    assert replayed == event_ids[1:]
    assert response.text.count(f"id: {event_ids[1]}") == 1
    assert response.headers["cache-control"] == "no-cache"
