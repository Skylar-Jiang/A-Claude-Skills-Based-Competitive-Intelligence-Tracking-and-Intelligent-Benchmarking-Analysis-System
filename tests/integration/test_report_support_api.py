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
                database_url=f"sqlite:///{tmp_path / 'support.db'}",
                report_dir=tmp_path / "reports",
                upload_dir=tmp_path / "uploads",
                chroma_dir=tmp_path / "chroma",
            )
        )
    )


def _report_id(client: TestClient, name: str = "Support fixture") -> str:
    product = client.post(
        "/api/v1/products",
        json={"name": name, "category": "demo", "data_mode": "demo"},
    ).json()["data"]
    run_id = client.post(
        "/api/v1/analysis-runs",
        json={"product_id": product["product_id"], "data_mode": "demo"},
    ).json()["data"]["run_id"]
    for _ in range(200):
        run = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
        if run["report_id"]:
            return str(run["report_id"])
        time.sleep(0.01)
    raise AssertionError("report was not created")


def test_report_history_lists_each_run_with_its_latest_immutable_version(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first_report_id = _report_id(client, "History product A")
        second_report_id = _report_id(client, "History product B")
        edited = client.post(
            f"/api/v1/reports/{first_report_id}/support",
            json={
                "action": "edit",
                "section_id": "next-actions",
                "message": "Clarify the next action.",
                "replacement": ["补充可追溯证据后再发布。"],
            },
        ).json()["data"]

        response = client.get("/api/v1/reports")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["total"] == 2
    reports = {item["product_name"]: item for item in payload["reports"]}
    assert reports["History product A"]["report_id"] == edited["report_id"]
    assert reports["History product A"]["version"] == 2
    assert reports["History product A"]["version_count"] == 2
    assert reports["History product B"]["report_id"] == second_report_id
    assert reports["History product B"]["version"] == 1
    assert reports["History product B"]["version_count"] == 1


def test_report_support_explains_with_section_evidence_limitations_and_history(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        response = client.post(
            f"/api/v1/reports/{report_id}/support",
            json={
                "action": "explain",
                "section_id": "executive-summary",
                "message": "Explain the strategy and its limitations.",
            },
        )
        payload = response.json()["data"]
        conversation = client.get(f"/api/v1/conversations/{payload['conversation_id']}")

    assert response.status_code == 200
    assert payload["report_id"] == report_id
    assert payload["report_version"] == 1
    assert payload["section_id"] == "executive-summary"
    assert isinstance(payload["evidence_ids"], list)
    assert isinstance(payload["limitations"], list)
    assert "version 1" in payload["response"]
    assert conversation.status_code == 200
    assert [item["role"] for item in conversation.json()["data"]["messages"]] == [
        "user",
        "assistant",
    ]
    assert conversation.json()["data"]["messages"][1]["metadata"]["action"] == "explain"


def test_localized_edit_creates_immutable_version_and_rejects_unseen_numbers(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        edited = client.post(
            f"/api/v1/reports/{report_id}/support",
            json={
                "action": "edit",
                "section_id": "next-actions",
                "message": "Make this action wording clearer without changing the analysis.",
                "replacement": ["补充可追溯证据后再发布。"],
            },
        )
        edited_payload = edited.json()["data"]
        rejected = client.post(
            f"/api/v1/reports/{edited_payload['report_id']}/support",
            json={
                "action": "edit",
                "section_id": "next-actions",
                "message": "Add a fabricated exact target.",
                "replacement": ["销量目标为 9999 件。"],
                "conversation_id": "rejected-edit-conversation",
            },
        )
        rejection_history = client.get("/api/v1/conversations/rejected-edit-conversation")
        versions = client.get(f"/api/v1/reports/{edited_payload['report_id']}/versions")

    assert edited.status_code == 200
    assert edited_payload["report_version"] == 2
    assert edited_payload["changed_section_ids"] == ["next-actions"]
    assert edited_payload["before"] != edited_payload["after"]
    assert "--- version-1" in edited_payload["unified_diff"]
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "validation_error"
    assert [item["metadata"]["audit_decision"] for item in rejection_history.json()["data"]["messages"]] == [
        "pending",
        "rejected",
    ]
    assert [item["version"] for item in versions.json()["data"]["versions"]] == [1, 2]


def test_report_support_rejects_scope_misattribution_unknown_evidence_and_broad_edits(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        misattributed = client.post(
            f"/api/v1/reports/{report_id}/support",
            json={
                "action": "edit",
                "section_id": "next-actions",
                "message": "Misattribute peer reviews.",
                "replacement": ["当前商品用户反馈很好。"],
            },
        )
        unknown_evidence = client.post(
            f"/api/v1/reports/{report_id}/support",
            json={
                "action": "edit",
                "section_id": "next-actions",
                "message": "Use an unknown citation.",
                "replacement": [{"text": "保持审慎。", "evidence_ids": ["missing-evidence"]}],
            },
        )
        broad_edit = client.post(
            f"/api/v1/reports/{report_id}/support",
            json={
                "action": "edit",
                "section_id": "executive-summary",
                "message": "Replace a non-editable analytical section.",
                "replacement": ["替换全部结论。"],
            },
        )

    assert [item.status_code for item in (misattributed, unknown_evidence, broad_edit)] == [422, 422, 422]
