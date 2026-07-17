import sqlite3
import time
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.enums import DataMode, DataOrigin, RunStageStatus
from app.core.exceptions import LLMNotConfiguredError
from app.db.migrations import upgrade_database
from app.db.models.core import Product
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository, SqlAlchemyProductRepository
from app.main import create_app
from app.rag.in_memory import InMemoryKnowledgeStore
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.product import ProductCreate
from app.services.analysis_service import AnalysisService


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'async.db'}",
        report_dir=tmp_path / "reports",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
        run_worker_count=1,
    )


def test_analysis_creation_returns_202_before_background_execution_finishes(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    entered = Event()
    release = Event()

    def blocked_execute(self, run_id):  # type: ignore[no-untyped-def]
        entered.set()
        release.wait(timeout=5)
        raise RuntimeError("controlled background failure")

    monkeypatch.setattr("app.services.analysis_service.AnalysisService.execute", blocked_execute)
    with TestClient(create_app(_settings(tmp_path))) as client:
        product = client.post(
            "/api/v1/products",
            json={"name": "Async product", "category": "demo-generic", "data_mode": "demo"},
        ).json()["data"]
        started_at = time.perf_counter()
        response = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product["product_id"], "data_mode": "demo"},
        )
        elapsed = time.perf_counter() - started_at

        assert response.status_code == 202
        assert elapsed < 1
        run = response.json()["data"]
        assert run["run_id"]
        assert run["status"] in {"pending", "running"}
        assert entered.wait(timeout=2)

        timeline = client.get(f"/api/v1/analysis-runs/{run['run_id']}/timeline")
        assert timeline.status_code == 200
        assert [item["stage_key"] for item in timeline.json()["data"]["stages"]] == [
            "product_preparation",
            "image_understanding",
            "peer_matching",
            "rag_preparation",
            "statistics",
            "product_market_agent",
            "user_insight_agent",
            "operations_decision_agent",
            "evidence_audit_agent",
            "report_export",
        ]
        release.set()


def test_background_failure_is_persisted_without_demo_or_mock_fallback(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    def failed_execute(self, run_id):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider timeout")

    monkeypatch.setattr("app.services.analysis_service.AnalysisService.execute", failed_execute)
    with TestClient(create_app(_settings(tmp_path))) as client:
        product = client.post(
            "/api/v1/products",
            json={"name": "Failure product", "category": "demo-generic", "data_mode": "demo"},
        ).json()["data"]
        response = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product["product_id"], "data_mode": "demo"},
        )
        run_id = response.json()["data"]["run_id"]

        for _ in range(100):
            run = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
            if run["status"] == "failed":
                break
            time.sleep(0.01)

        assert run["status"] == "failed"
        assert run["current_node"] == "workflow_failed"
        assert run["state"]["error"]["type"] == "RuntimeError"
        assert run["state"]["fallback_used"] is False


def test_background_failure_marks_the_running_stage_failed(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    def fail_during_peer_matching(self, run_id):  # type: ignore[no-untyped-def]
        self._stage(run_id, "peer_matching", RunStageStatus.RUNNING)
        raise ValueError("controlled peer matching failure")

    monkeypatch.setattr(
        "app.services.analysis_service.AnalysisService.execute",
        fail_during_peer_matching,
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        product = client.post(
            "/api/v1/products",
            json={"name": "Stage failure", "category": "demo", "data_mode": "demo"},
        ).json()["data"]
        response = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product["product_id"], "data_mode": "demo"},
        )
        run_id = response.json()["data"]["run_id"]
        for _ in range(200):
            run = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
            if run["status"] == "failed":
                break
            time.sleep(0.01)
        timeline = client.get(f"/api/v1/analysis-runs/{run_id}/timeline").json()["data"]

    peer_stage = next(item for item in timeline["stages"] if item["stage_key"] == "peer_matching")
    assert peer_stage["status"] == "failed"
    assert peer_stage["error"]["message"] == "controlled peer matching failure"


def test_background_dispatcher_creates_a_worker_owned_knowledge_store(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    stores: list[InMemoryKnowledgeStore] = []
    used: list[InMemoryKnowledgeStore] = []

    def store_factory() -> InMemoryKnowledgeStore:
        store = InMemoryKnowledgeStore()
        stores.append(store)
        return store

    def capture_execute(self, run_id):  # type: ignore[no-untyped-def]
        used.append(self.knowledge_store)
        raise RuntimeError("stop after capturing worker store")

    monkeypatch.setattr("app.services.analysis_service.AnalysisService.execute", capture_execute)
    app = create_app(_settings(tmp_path), knowledge_store_factory=store_factory)
    with TestClient(app) as client:
        product = client.post(
            "/api/v1/products",
            json={"name": "Worker store", "category": "demo", "data_mode": "demo"},
        ).json()["data"]
        response = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product["product_id"], "data_mode": "demo"},
        )
        run_id = response.json()["data"]["run_id"]
        for _ in range(100):
            run = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
            if run["status"] == "failed":
                break
            time.sleep(0.01)

    assert len(stores) == 2
    assert used == [stores[1]]
    assert stores[0] is not stores[1]


def test_file_sqlite_uses_wal_for_status_reads_during_background_writes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/products",
            json={"name": "Concurrent SQLite", "category": "demo", "data_mode": "demo"},
        )
        assert response.status_code == 201
        with sqlite3.connect(tmp_path / "async.db") as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000


def test_background_database_failure_rolls_back_before_persisting_failed_status(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    def failed_commit(self, run_id):  # type: ignore[no-untyped-def]
        self.products.session.add(Product(product_id="invalid-row"))
        self.products.session.commit()

    monkeypatch.setattr("app.services.analysis_service.AnalysisService.execute", failed_commit)
    with TestClient(create_app(_settings(tmp_path))) as client:
        product = client.post(
            "/api/v1/products",
            json={"name": "Failed transaction", "category": "demo", "data_mode": "demo"},
        ).json()["data"]
        response = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product["product_id"], "data_mode": "demo"},
        )
        run_id = response.json()["data"]["run_id"]
        for _ in range(200):
            run = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
            if run["status"] == "failed":
                break
            time.sleep(0.01)

    assert run["status"] == "failed"
    assert run["state"]["error"]["type"] == "IntegrityError"


def test_demo_dispatch_uses_memory_when_real_chroma_credentials_are_missing(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(
        update={"rag_use_chroma": True, "embedding_model": "text-embedding-v4"}
    )
    with TestClient(create_app(settings)) as client:
        product = client.post(
            "/api/v1/products",
            json={"name": "Demo without Qwen", "category": "demo", "data_mode": "demo"},
        ).json()["data"]
        response = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product["product_id"], "data_mode": "demo"},
        )
        run_id = response.json()["data"]["run_id"]
        for _ in range(200):
            run = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
            if run["status"] == "succeeded":
                break
            time.sleep(0.01)

    assert response.status_code == 202
    assert run["status"] == "succeeded"


def test_worker_store_initialization_failure_is_persisted(tmp_path: Path) -> None:
    calls = 0

    def store_factory():  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            return InMemoryKnowledgeStore()
        raise LLMNotConfiguredError("embedding credentials missing")

    with TestClient(create_app(_settings(tmp_path), knowledge_store_factory=store_factory)) as client:
        product = client.post(
            "/api/v1/products",
            json={"name": "Factory failure", "category": "demo", "data_mode": "demo"},
        ).json()["data"]
        response = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product["product_id"], "data_mode": "demo"},
        )
        run_id = response.json()["data"]["run_id"]
        for _ in range(200):
            run = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
            if run["status"] == "failed":
                break
            time.sleep(0.01)
        timeline = client.get(f"/api/v1/analysis-runs/{run_id}/timeline").json()["data"]

    assert run["status"] == "failed"
    assert run["current_node"] == "workflow_failed"
    assert run["state"]["error"]["code"] == "llm_not_configured"
    assert timeline["stages"][0]["status"] == "failed"


def test_startup_recovers_previously_pending_runs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    upgrade_database(settings.database_url)
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        product = SqlAlchemyProductRepository(session).create(
            ProductCreate(name="Recovered demo", category="demo", data_mode=DataMode.DEMO),
            data_origin=DataOrigin.DEMO,
        )
        repository = SqlAlchemyAnalysisRepository(session)
        pending = repository.create_run(
            AnalysisRunCreate(product_id=product.product_id, data_mode=DataMode.DEMO)
        )
        repository.initialize_stages(pending.run_id, AnalysisService.STAGE_KEYS)
    engine.dispose()

    with TestClient(create_app(settings)) as client:
        for _ in range(200):
            run = client.get(f"/api/v1/analysis-runs/{pending.run_id}").json()["data"]
            if run["status"] == "succeeded":
                break
            time.sleep(0.01)

    assert run["status"] == "succeeded"
