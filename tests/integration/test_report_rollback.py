from tests.integration.test_report_support_api import _client, _report_id


def test_rollback_creates_a_new_version_without_mutating_history(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        edited = client.post(
            f"/api/v1/reports/{report_id}/support",
            json={
                "action": "edit",
                "section_id": "next-actions",
                "message": "Clarify this section.",
                "replacement": ["补充证据后发布。"],
            },
        ).json()["data"]
        rolled_back = client.post(
            f"/api/v1/reports/{edited['report_id']}/rollback",
            json={"target_version": 1, "reason": "Restore the audited original."},
        )
        versions = client.get(f"/api/v1/reports/{rolled_back.json()['data']['report_id']}/versions")

    payload = rolled_back.json()["data"]
    assert rolled_back.status_code == 200
    assert payload["version"] == 3
    assert payload["parent_report_id"] == edited["report_id"]
    assert payload["sections"]["next_actions"] != ["补充证据后发布。"]
    assert [item["version"] for item in versions.json()["data"]["versions"]] == [1, 2, 3]
