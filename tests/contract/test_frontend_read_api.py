import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                _env_file=None,
                database_url=f"sqlite:///{tmp_path / 'frontend.db'}",
                report_dir=tmp_path / "reports",
                upload_dir=tmp_path / "uploads",
                chroma_dir=tmp_path / "chroma",
            )
        )
    )


def _completed_demo_run(client: TestClient) -> dict[str, object]:
    product = client.post(
        "/api/v1/products",
        json={"name": "Frontend fixture", "category": "demo-generic", "data_mode": "demo"},
    ).json()["data"]
    created = client.post(
        "/api/v1/analysis-runs",
        json={"product_id": product["product_id"], "data_mode": "demo"},
    )
    assert created.status_code == 202
    run_id = created.json()["data"]["run_id"]
    for _ in range(200):
        run = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
        if run["status"] in {"succeeded", "manual_review", "failed"}:
            return run
        time.sleep(0.01)
    raise AssertionError("analysis run did not reach a terminal state")


def test_frontend_read_endpoints_are_repository_backed_and_typed(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        run = _completed_demo_run(client)
        assert run["status"] in {"succeeded", "manual_review"}
        run_id = str(run["run_id"])

        status = client.get(f"/api/v1/analysis-runs/{run_id}/status")
        timeline = client.get(f"/api/v1/analysis-runs/{run_id}/timeline")
        agents = client.get(f"/api/v1/analysis-runs/{run_id}/agents")
        peers = client.get(f"/api/v1/analysis-runs/{run_id}/peers")
        evidence = client.get(f"/api/v1/analysis-runs/{run_id}/evidence")
        audit = client.get(f"/api/v1/analysis-runs/{run_id}/audit")
        workflow = client.get("/api/v1/workflow/metadata")

    assert status.status_code == 200
    assert status.json()["data"]["report_id"] == run["report_id"]
    assert len(timeline.json()["data"]["stages"]) == 10
    assert {item["agent_name"] for item in agents.json()["data"]["agents"]} == {
        "ProductMarketAgent",
        "UserInsightAgent",
        "OperationsDecisionAgent",
        "EvidenceAuditAgent",
    }
    assert all("display_name" in item and "responsibility" in item for item in agents.json()["data"]["agents"])
    assert all("provider" in item and "model_name" in item for item in agents.json()["data"]["agents"])
    assert all(item["real_model_called"] is False for item in agents.json()["data"]["agents"])
    assert workflow.status_code == 200
    assert {node["node_name"] for node in workflow.json()["data"]["nodes"]} >= {
        "product_market_agent",
        "user_insight_agent",
        "evidence_audit_agent",
    }
    assert [
        node["parallel_group"]
        for node in workflow.json()["data"]["nodes"]
        if node["node_name"] in {"product_market_agent", "user_insight_agent"}
    ] == ["market_and_user", "market_and_user"]
    assert peers.json()["data"] == {
        "run_id": run_id,
        "peer_group_id": None,
        "selected_parent_asins": [],
        "peers": [],
    }
    assert evidence.json()["data"]["run_id"] == run_id
    assert isinstance(evidence.json()["data"]["evidence"], list)
    assert audit.json()["data"]["audit"]["status"] in {"pass", "warning", "rejected"}


def test_frontend_read_endpoints_return_unified_not_found_error(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        for suffix in ("status", "timeline", "agents", "peers", "evidence", "audit"):
            response = client.get(f"/api/v1/analysis-runs/missing/{suffix}")
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "resource_not_found"
