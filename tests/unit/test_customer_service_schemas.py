from app.core.enums import (
    CustomerServiceAction,
    CustomerServiceIntent,
    CustomerServicePersonality,
)
from app.schemas.customer_service import (
    CustomerServiceMessageRequest,
    CustomerServiceMessageResponse,
)


def test_customer_service_message_request_uses_four_personalities() -> None:
    payload = CustomerServiceMessageRequest(
        message="如果目标用户调整为大学生群体，方案应该如何变化？",
        personality=CustomerServicePersonality.PROFESSIONAL,
    )

    assert payload.personality is CustomerServicePersonality.PROFESSIONAL
    assert {item.value for item in CustomerServicePersonality} == {
        "simple",
        "professional",
        "companion",
        "innovative",
    }


def test_customer_service_response_contains_incremental_update_fields() -> None:
    response = CustomerServiceMessageResponse(
        conversation_id="conv-1",
        intent=CustomerServiceIntent.MODIFY_STRATEGY,
        affected_modules=["user_persona", "product_positioning"],
        action_taken=CustomerServiceAction.TARGETED_REGENERATION,
        reply="已根据大学生群体调整方案。",
        report_id="report-2",
        report_version=2,
        changed_section_ids=["launch-marketing-strategy"],
        change_summary=["更新画像", "调整定位"],
        pending_questions=[],
    )

    assert response.report_version == 2
    assert response.action_taken is CustomerServiceAction.TARGETED_REGENERATION
