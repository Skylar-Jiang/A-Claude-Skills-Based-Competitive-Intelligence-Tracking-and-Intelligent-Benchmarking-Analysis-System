from tests.integration.test_report_support_api import _client, _report_id


def _run_customer_service_update(client, report_id: str, message: str, personality: str = "professional"):  # type: ignore[no-untyped-def]
    original_report = client.get(f"/api/v1/reports/{report_id}").json()["data"]
    response = client.post(
        f"/api/v1/reports/{report_id}/customer-service/messages",
        json={
            "message": message,
            "personality": personality,
        },
    )
    payload = response.json()["data"]
    versions = client.get(f"/api/v1/reports/{payload['report_id']}/versions")
    conversation = client.get(
        f"/api/v1/reports/{payload['report_id']}/customer-service/conversations/{payload['conversation_id']}"
    )
    updated_report = client.get(f"/api/v1/reports/{payload['report_id']}").json()["data"]
    return original_report, response, payload, versions, conversation, updated_report


def _assert_common_targeted_regeneration(payload, versions, conversation) -> None:  # type: ignore[no-untyped-def]
    assert payload["action_taken"] == "targeted_regeneration"
    assert payload["report_version"] == 2
    assert set(payload["affected_modules"]) == {
        "user_persona",
        "product_positioning",
        "marketing_copy",
        "promotion_strategy",
    }
    assert "launch-marketing-strategy" in payload["changed_section_ids"]
    assert [item["version"] for item in versions.json()["data"]["versions"]] == [1, 2]
    assert conversation.status_code == 200


def test_customer_service_explain_returns_same_report_and_history(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        response = client.post(
            f"/api/v1/reports/{report_id}/customer-service/messages",
            json={
                "message": "为什么建议优先做内容种草？",
                "personality": "simple",
            },
        )
        payload = response.json()["data"]
        conversation = client.get(
            f"/api/v1/reports/{report_id}/customer-service/conversations/{payload['conversation_id']}"
        )

    assert response.status_code == 200
    assert payload["action_taken"] == "explain"
    assert payload["report_id"] == report_id
    assert payload["changed_section_ids"] == []
    assert conversation.status_code == 200
    assert conversation.json()["data"]["personality"] == "simple"
    assert [item["role"] for item in conversation.json()["data"]["messages"]] == ["user", "assistant"]


def test_customer_service_targeted_regeneration_creates_student_focused_new_report_version(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        original_report, response, payload, versions, conversation, updated_report = _run_customer_service_update(
            client,
            report_id,
            "如果目标用户调整为大学生群体，方案应该如何变化？",
        )

    assert response.status_code == 200
    _assert_common_targeted_regeneration(payload, versions, conversation)
    assert "target_audience=大学生群体" in conversation.json()["data"]["confirmed_requirements"]

    original_strategy = original_report["sections"]["launch_marketing_strategy"]
    strategy = updated_report["sections"]["launch_marketing_strategy"]
    assert strategy["target_segments"] == ["大学生群体"]
    assert "宿舍友好型" in strategy["positioning"]
    assert "小红书" in str(strategy["channel_strategy"])
    assert "宿舍" in str(strategy["messaging_strategy"])
    assert "大学生养宠人群" in strategy["customer_service_persona_focus"]
    assert strategy["evidence_ids"] == original_strategy["evidence_ids"]
    assert strategy["customer_service_adjustment"]["evidence_ids"] == original_strategy["evidence_ids"]
    for item in original_strategy["launch_actions"]:
        assert item in strategy["launch_actions"]
    conclusion_evidence_ids = updated_report["sections"]["data_supported_conclusions"][-1]["evidence_ids"]
    assert conclusion_evidence_ids == original_strategy["evidence_ids"]
    assert updated_report["sections"]["data_supported_conclusions"][-1]["conclusion"]
    for item in original_report["sections"]["next_actions"]:
        assert item in updated_report["sections"]["next_actions"]


def test_customer_service_targeted_regeneration_supports_young_white_collar_audience(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        _, response, payload, versions, conversation, updated_report = _run_customer_service_update(
            client,
            report_id,
            "如果目标用户改成年轻白领，方案怎么调整？",
        )

    assert response.status_code == 200
    _assert_common_targeted_regeneration(payload, versions, conversation)
    assert "target_audience=年轻白领" in conversation.json()["data"]["confirmed_requirements"]
    strategy = updated_report["sections"]["launch_marketing_strategy"]
    assert strategy["target_segments"] == ["年轻白领"]
    assert "品质型饮水机方案" in strategy["positioning"]
    assert "微信生态" in str(strategy["channel_strategy"])
    assert "下班后无需频繁打理" in str(strategy["messaging_strategy"])


def test_customer_service_targeted_regeneration_supports_beginner_pet_owner_audience(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        _, response, payload, versions, conversation, updated_report = _run_customer_service_update(
            client,
            report_id,
            "如果目标用户调整为新手养宠人群，方案怎么改？",
        )

    assert response.status_code == 200
    _assert_common_targeted_regeneration(payload, versions, conversation)
    assert "target_audience=新手养宠人群" in conversation.json()["data"]["confirmed_requirements"]
    strategy = updated_report["sections"]["launch_marketing_strategy"]
    assert strategy["target_segments"] == ["新手养宠人群"]
    assert "新手友好型饮水机方案" in strategy["positioning"]
    assert "避坑" in str(strategy["channel_strategy"])
    assert "安装简单" in str(strategy["messaging_strategy"])


def test_customer_service_targeted_regeneration_supports_multi_pet_household_audience(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        _, response, payload, versions, conversation, updated_report = _run_customer_service_update(
            client,
            report_id,
            "如果目标用户改成多宠家庭用户，方案应该怎么变？",
        )

    assert response.status_code == 200
    _assert_common_targeted_regeneration(payload, versions, conversation)
    assert "target_audience=多宠家庭用户" in conversation.json()["data"]["confirmed_requirements"]
    strategy = updated_report["sections"]["launch_marketing_strategy"]
    assert strategy["target_segments"] == ["多宠家庭用户"]
    assert "稳定供水方案" in strategy["positioning"]
    assert "多猫家庭" in str(strategy["channel_strategy"])
    assert "多宠共用场景" in str(strategy["messaging_strategy"])


def test_customer_service_positioning_edit_only_updates_positioning_scope(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        original_report, response, payload, versions, conversation, updated_report = _run_customer_service_update(
            client,
            report_id,
            "把定位调整得更高端一些",
        )

    assert response.status_code == 200
    assert payload["action_taken"] == "positioning_edit"
    assert payload["report_version"] == 2
    assert payload["affected_modules"] == ["product_positioning"]
    assert payload["changed_section_ids"] == ["launch-marketing-strategy"]
    assert [item["version"] for item in versions.json()["data"]["versions"]] == [1, 2]
    strategy = updated_report["sections"]["launch_marketing_strategy"]
    original_strategy = original_report["sections"]["launch_marketing_strategy"]
    assert "客服本轮要求定位更偏高端" in strategy["positioning"]
    assert strategy["target_segments"] == original_strategy["target_segments"]
    assert strategy["messaging_strategy"] == original_strategy["messaging_strategy"]
    assert strategy["channel_strategy"] == original_strategy["channel_strategy"]
    assert conversation.json()["data"]["last_intent"] == "modify_positioning"


def test_customer_service_marketing_copy_edit_only_updates_copy_scope(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        original_report, response, payload, versions, conversation, updated_report = _run_customer_service_update(
            client,
            report_id,
            "把营销文案写得更专业一点",
        )

    assert response.status_code == 200
    assert payload["action_taken"] == "marketing_copy_edit"
    assert payload["report_version"] == 2
    assert payload["affected_modules"] == ["marketing_copy"]
    assert payload["changed_section_ids"] == ["launch-marketing-strategy"]
    assert [item["version"] for item in versions.json()["data"]["versions"]] == [1, 2]
    strategy = updated_report["sections"]["launch_marketing_strategy"]
    original_strategy = original_report["sections"]["launch_marketing_strategy"]
    assert "客服本轮要求文案更偏专业" in str(strategy["messaging_strategy"])
    assert strategy["target_segments"] == original_strategy["target_segments"]
    assert strategy["positioning"] == original_strategy["positioning"]
    assert strategy["channel_strategy"] == original_strategy["channel_strategy"]
    assert conversation.json()["data"]["last_intent"] == "modify_marketing_copy"


def test_customer_service_promotion_strategy_edit_only_updates_channel_scope(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        original_report, response, payload, versions, conversation, updated_report = _run_customer_service_update(
            client,
            report_id,
            "把推广策略调整得更保守一些",
        )

    assert response.status_code == 200
    assert payload["action_taken"] == "promotion_strategy_edit"
    assert payload["report_version"] == 2
    assert payload["affected_modules"] == ["promotion_strategy"]
    assert payload["changed_section_ids"] == ["launch-marketing-strategy"]
    assert [item["version"] for item in versions.json()["data"]["versions"]] == [1, 2]
    strategy = updated_report["sections"]["launch_marketing_strategy"]
    original_strategy = original_report["sections"]["launch_marketing_strategy"]
    assert "客服本轮要求推广策略更偏保守" in str(strategy["channel_strategy"])
    assert strategy["target_segments"] == original_strategy["target_segments"]
    assert strategy["positioning"] == original_strategy["positioning"]
    assert strategy["messaging_strategy"] == original_strategy["messaging_strategy"]
    assert conversation.json()["data"]["last_intent"] == "modify_promotion_strategy"


def test_customer_service_clarification_returns_pending_questions_without_new_version(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        response = client.post(
            f"/api/v1/reports/{report_id}/customer-service/messages",
            json={
                "message": "帮我改一下定位",
                "personality": "companion",
            },
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["action_taken"] == "clarification_required"
    assert payload["report_version"] == 1
    assert payload["pending_questions"]


def test_customer_service_rejects_full_rewrite_style_request_without_new_version(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with _client(tmp_path) as client:
        report_id = _report_id(client)
        response = client.post(
            f"/api/v1/reports/{report_id}/customer-service/messages",
            json={
                "message": "把整份报告全部重写并加上 30% 转化率预测",
                "personality": "innovative",
            },
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["action_taken"] == "reject"
    assert payload["report_version"] == 1
    assert payload["changed_section_ids"] == []
