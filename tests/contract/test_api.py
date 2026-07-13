from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        report_dir=tmp_path / "reports",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
    )
    return TestClient(create_app(settings))


def test_demo_api_flow_uses_unified_envelopes(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["success"] is True
        assert health.json()["meta"]["api_version"] == "v1"

        created = client.post(
            "/api/v1/products",
            json={
                "name": "DEMO Portable Organizer",
                "category": "demo-generic",
                "data_mode": "demo",
            },
        )
        assert created.status_code == 201
        product_id = created.json()["data"]["product_id"]

        started = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product_id, "data_mode": "demo"},
        )
        assert started.status_code == 201
        run = started.json()["data"]
        assert run["status"] == "succeeded"
        assert run["report_id"]

        fetched = client.get(f"/api/v1/analysis-runs/{run['run_id']}")
        report = client.get(f"/api/v1/reports/{run['report_id']}")
        assert fetched.json()["data"]["state"]["product_market_analysis"]["implementation_status"] == "scaffold"
        assert report.json()["data"]["is_demo"] is True


def test_real_mode_without_model_configuration_is_explicit_503(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": "missing-real-product", "data_mode": "real"},
        )

    assert response.status_code == 503
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "llm_not_configured"


def test_mock_and_configured_real_never_fall_back_to_demo(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        mock = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": "missing-mock-product", "data_mode": "mock"},
        )
    configured = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'configured.db'}",
        report_dir=tmp_path / "configured-reports",
        upload_dir=tmp_path / "configured-uploads",
        chroma_dir=tmp_path / "configured-chroma",
        openai_api_key="test-only-placeholder",
        model_analysis="test-only-placeholder",
    )
    with TestClient(create_app(configured)) as client:
        real = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": "missing-real-product", "data_mode": "real"},
        )

    assert mock.status_code == 503
    assert real.status_code == 503
    assert mock.json()["error"]["code"] == "workflow_failed"
    assert real.json()["error"]["code"] == "workflow_failed"
    assert "fallback" in mock.json()["error"]["message"]
    assert "fallback" in real.json()["error"]["message"]


def test_openapi_contains_only_the_ten_formal_v1_routes(tmp_path: Path) -> None:
    expected = {
        "/api/v1/health",
        "/api/v1/products",
        "/api/v1/products/{product_id}",
        "/api/v1/products/{product_id}/files",
        "/api/v1/analysis-runs",
        "/api/v1/analysis-runs/{run_id}",
        "/api/v1/analysis-runs/{run_id}/feedback",
        "/api/v1/reports/{report_id}",
        "/api/v1/knowledge/rebuild",
        "/api/v1/conversations/{session_id}",
    }
    with make_client(tmp_path) as client:
        openapi = client.get("/openapi.json").json()

    assert set(openapi["paths"]) == expected
    serialized = str(openapi).lower()
    assert "cucumber" not in serialized
    assert "fresh wholesale" not in serialized
