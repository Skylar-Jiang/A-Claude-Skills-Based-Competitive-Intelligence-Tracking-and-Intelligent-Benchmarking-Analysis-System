import time
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
        assert started.status_code == 202
        run_id = started.json()["data"]["run_id"]
        for _ in range(200):
            run = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
            if run["report_id"]:
                break
            time.sleep(0.01)
        assert run["status"] == "succeeded"
        assert run["report_id"]

        fetched = client.get(f"/api/v1/analysis-runs/{run['run_id']}")
        report = client.get(f"/api/v1/reports/{run['report_id']}")
        metadata = client.get(f"/api/v1/analysis-runs/{run['run_id']}/metadata")
        events = client.get(f"/api/v1/analysis-runs/{run['run_id']}/events")
        markdown = client.get(f"/api/v1/reports/{run['report_id']}/markdown")
        report_json = client.get(f"/api/v1/reports/{run['report_id']}/json")
        assert fetched.json()["data"]["state"]["product_market_analysis"]["implementation_status"] == "scaffold"
        assert report.json()["data"]["is_demo"] is True
        assert metadata.json()["data"]["workflow_metadata"]["duration_ms"] >= 0
        assert events.headers["content-type"].startswith("text/event-stream")
        assert events.text.count("event: agent_completed") == 4
        assert "event: workflow_completed" in events.text
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert report_json.json()["report_id"] == run["report_id"]


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


def test_workflow_failure_is_persisted_and_returned_without_fallback(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    def fail_workflow(self, state):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider timeout")

    monkeypatch.setattr("app.services.analysis_service.TradePilotWorkflow.invoke", fail_workflow)
    with make_client(tmp_path) as client:
        product = client.post(
            "/api/v1/products",
            json={"name": "Failure fixture", "category": "demo-generic", "data_mode": "demo"},
        ).json()["data"]
        response = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product["product_id"], "data_mode": "demo"},
        )

        assert response.status_code == 202
        run_id = response.json()["data"]["run_id"]
        for _ in range(200):
            persisted = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
            if persisted["status"] == "failed":
                break
            time.sleep(0.01)

    assert persisted["status"] == "failed"
    assert persisted["current_node"] == "workflow_failed"
    assert persisted["state"]["error"]["type"] == "RuntimeError"


def test_openapi_contains_formal_v1_routes(tmp_path: Path) -> None:
    expected = {
        "/api/v1/health",
        "/api/v1/workflow/metadata",
        "/api/v1/products",
        "/api/v1/products/{product_id}",
        "/api/v1/products/{product_id}/files",
        "/api/v1/analysis-runs",
        "/api/v1/analysis-runs/{run_id}",
        "/api/v1/analysis-runs/{run_id}/metadata",
        "/api/v1/analysis-runs/{run_id}/status",
        "/api/v1/analysis-runs/{run_id}/timeline",
        "/api/v1/analysis-runs/{run_id}/agents",
        "/api/v1/analysis-runs/{run_id}/peers",
        "/api/v1/analysis-runs/{run_id}/evidence",
        "/api/v1/analysis-runs/{run_id}/audit",
        "/api/v1/analysis-runs/{run_id}/events",
        "/api/v1/analysis-runs/{run_id}/feedback",
        "/api/v1/reports/{report_id}",
        "/api/v1/reports/{report_id}/markdown",
        "/api/v1/reports/{report_id}/json",
        "/api/v1/reports/{report_id}/support",
        "/api/v1/reports/{report_id}/versions",
        "/api/v1/reports/{report_id}/rollback",
        "/api/v1/knowledge/rebuild",
        "/api/v1/conversations/{session_id}",
    }
    with make_client(tmp_path) as client:
        openapi = client.get("/openapi.json").json()

    assert set(openapi["paths"]) == expected
    serialized = str(openapi).lower()
    assert "cucumber" not in serialized
    assert "fresh wholesale" not in serialized


def test_every_v1_operation_declares_typed_success_and_unified_error_models(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        openapi = client.get("/openapi.json").json()

    operations = [
        operation
        for path in openapi["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post"}
    ]
    assert len(operations) == 24
    enveloped = []
    for operation in operations:
        success_status = next(
            status for status in ("200", "201", "202") if status in operation["responses"]
        )
        success_content = operation["responses"][success_status].get("content", {})
        success_schema = success_content.get("application/json", {}).get("schema", {})
        if "ApiResponse" not in success_schema.get("$ref", ""):
            continue
        enveloped.append(operation)
        error_schema = operation["responses"]["422"]["content"]["application/json"]["schema"]
        assert "ApiResponse" in success_schema["$ref"]
        assert "ApiResponse" in error_schema["$ref"]
    assert len(enveloped) == 21
