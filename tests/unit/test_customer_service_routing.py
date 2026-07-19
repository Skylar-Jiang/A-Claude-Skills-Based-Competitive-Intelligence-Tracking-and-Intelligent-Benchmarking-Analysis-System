from app.core.enums import CustomerServiceIntent
from app.services.customer_service_agent_service import CustomerServiceAgentService


def test_customer_service_intent_classification_routes_core_paths() -> None:
    assert (
        CustomerServiceAgentService._classify_intent("解释一下为什么建议先做内容种草")
        is CustomerServiceIntent.EXPLAIN
    )
    assert (
        CustomerServiceAgentService._classify_intent("把目标用户改成大学生群体")
        is CustomerServiceIntent.MODIFY_STRATEGY
    )
    assert (
        CustomerServiceAgentService._classify_intent("把下一步写得更专业一点")
        is CustomerServiceIntent.LOCALIZED_EDIT
    )
    assert (
        CustomerServiceAgentService._classify_intent("把定位调整得更高端一些")
        is CustomerServiceIntent.MODIFY_POSITIONING
    )
    assert (
        CustomerServiceAgentService._classify_intent("把营销文案写得更专业一点")
        is CustomerServiceIntent.MODIFY_MARKETING_COPY
    )
    assert (
        CustomerServiceAgentService._classify_intent("把推广策略调整得更保守一些")
        is CustomerServiceIntent.MODIFY_PROMOTION_STRATEGY
    )
    assert (
        CustomerServiceAgentService._classify_intent("帮我改一下定位")
        is CustomerServiceIntent.CLARIFICATION_REQUIRED
    )
    assert (
        CustomerServiceAgentService._classify_intent("把整份报告全部重写并加上 30% 转化率预测")
        is CustomerServiceIntent.REJECT
    )


def test_customer_service_audience_rules_cover_four_named_segments() -> None:
    assert (
        CustomerServiceAgentService._audience_rules("大学生群体")["audience_label"]
        == "大学生群体"
    )
    assert (
        CustomerServiceAgentService._audience_rules("年轻白领")["audience_label"]
        == "年轻白领"
    )
    assert (
        CustomerServiceAgentService._audience_rules("新手养宠人群")["audience_label"]
        == "新手养宠人群"
    )
    assert (
        CustomerServiceAgentService._audience_rules("多宠家庭用户")["audience_label"]
        == "多宠家庭用户"
    )
