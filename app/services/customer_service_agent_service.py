import json
import re
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.enums import (
    CustomerServiceAction,
    CustomerServiceIntent,
    CustomerServicePersonality,
    ErrorCode,
)
from app.core.exceptions import TradePilotError
from app.db.repositories.sqlalchemy import SqlAlchemyAnalysisRepository
from app.schemas.common import utc_now
from app.schemas.customer_service import (
    CustomerServiceConversationMessageRead,
    CustomerServiceConversationRead,
    CustomerServiceMessageRequest,
    CustomerServiceMessageResponse,
)
from app.schemas.report import FinalReport, ReportSupportRequest
from app.services.conversation_service import ConversationService
from app.services.report_exporter import ReportExporter
from app.services.report_support_service import ReportSupportService

AUDIENCE_PATTERN = re.compile(
    r"(?:目标用户|用户群体|客群|受众).{0,8}?(?:改成|调整为|改为|变成)([^，。；,!?？]{2,24})"
)
POSITIONING_DIRECTION_PATTERN = re.compile(
    r"(?:定位).{0,8}?(?:改成|调整为|改为|变成|更偏|偏向|更)([^，。；,!?？]{2,24})"
)
MARKETING_COPY_DIRECTION_PATTERN = re.compile(
    r"(?:营销文案|文案|表达).{0,8}?(?:改成|调整为|改为|变成|更偏|偏向|更|写得)([^，。；,!?？]{2,24})"
)
PROMOTION_DIRECTION_PATTERN = re.compile(
    r"(?:推广策略|渠道策略|投放策略|推广渠道|投放渠道).{0,8}?(?:改成|调整为|改为|变成|更偏|偏向|更)([^，。；,!?？]{2,24})"
)
FULL_REWRITE_PATTERN = re.compile(r"(整份报告|全部重写|整个报告)")
UNSUPPORTED_NUMERIC_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%\b")

STUDENT_AUDIENCE_KEYWORD = "大学生"
WHITE_COLLAR_KEYWORDS = ("白领", "上班族", "职场", "通勤")
BEGINNER_PET_OWNER_KEYWORDS = ("新手养宠", "养宠新手", "第一次养宠", "初次养宠")
MULTI_PET_KEYWORDS = ("多宠", "多猫", "多狗", "多只宠物", "多宠家庭")
DEFAULT_AUDIENCE_LABEL = "新的目标用户群体"

STUDENT_AUDIENCE_RULES = {
    "audience_label": "大学生群体",
    "persona_summary": "以预算敏感、宿舍生活、颜值偏好和社交分享意愿较强的大学生养宠人群为核心客群。",
    "positioning": "将产品定位为宿舍友好型、高颜值、易清洁、适合学生预算内做升级选择的饮水机方案。",
    "messaging": [
        "文案优先强调宿舍场景下的安静运行、清洁省心和日常打理负担低。",
        "表达上突出高颜值、桌面友好、适合拍照分享和提升养宠仪式感。",
        "价格沟通避免纯高端叙事，改为更容易被学生接受的性价比升级表达。",
    ],
    "channels": [
        "优先覆盖小红书、抖音、B站等大学生高频内容平台。",
        "增加宿舍养宠、学生党好物、颜值桌搭等内容切入场景。",
        "优先考虑校园KOC、学生博主和低门槛样品种草。",
    ],
    "launch_actions": [
        "补一版面向大学生群体的详情页首屏，突出宿舍友好、安静、省心清洁。",
        "围绕学生党预算、颜值偏好和宿舍养宠场景制作短视频种草素材。",
        "测试带有校园宿舍、学生养宠、平价升级关键词的首轮内容投放。",
    ],
    "next_actions": [
        "验证大学生群体对当前价格带的接受度，必要时补充学生友好型组合或优惠表达。",
        "补充宿舍场景素材，强化安静运行、桌面占用小和清洁省心的使用感知。",
    ],
    "conclusion": "本轮改版将方案重点切向大学生群体，策略表达将更强调预算敏感、宿舍场景、颜值表达和内容传播效率。",
    "insight_note": "后续用户洞察应重点关注大学生群体对预算、宿舍使用限制、颜值设计和社交分享属性的敏感度。",
}

WHITE_COLLAR_AUDIENCE_RULES = {
    "audience_label": "年轻白领",
    "persona_summary": "以注重生活品质、居家整洁感、时间效率和产品设计感的年轻白领养宠人群为核心客群。",
    "positioning": "将产品定位为适合都市居家环境的品质型饮水机方案，强调安静、省心维护和家居融合度。",
    "messaging": [
        "文案突出下班后无需频繁打理、清洁维护成本低和使用体验稳定。",
        "强调静音运行、材质质感和家居桌面融入感，避免廉价塑料感叙事。",
        "价格表达更强调长期省心、品质升级和日常效率，而不是单纯低价。",
    ],
    "channels": [
        "优先覆盖小红书、抖音和微信生态中的品质生活与都市养宠内容场景。",
        "增加居家收纳、桌面美学、上班族养宠效率工具等内容切入。",
        "优先考虑家居生活方式博主、都市养宠KOC和精致生活类测评。",
    ],
    "launch_actions": [
        "补一版面向年轻白领的详情页首屏，突出静音、质感和低维护负担。",
        "围绕都市租房、独居养宠、下班后轻维护等场景制作内容素材。",
        "测试品质升级、家居融合和效率养宠三个角度的首轮投放表达。",
    ],
    "next_actions": [
        "验证年轻白领对当前价格带和材质质感表达的接受度。",
        "补充更贴近都市家居环境的静音与外观展示素材。",
    ],
    "conclusion": "本轮改版将方案重点切向年轻白领，策略表达将更强调品质感、时间效率、家居融合和长期省心。",
    "insight_note": "后续用户洞察应重点关注年轻白领对静音、清洁效率、材质质感和家居融入度的敏感点。",
}

BEGINNER_PET_OWNER_RULES = {
    "audience_label": "新手养宠人群",
    "persona_summary": "以缺少养宠经验、担心踩坑、重视易上手和安全感的新手养宠用户为核心客群。",
    "positioning": "将产品定位为新手友好型饮水机方案，强调简单上手、好清洁、低学习成本和使用安全感。",
    "messaging": [
        "文案优先强调安装简单、清洁步骤少、换芯维护更容易理解。",
        "突出低水位提醒、清洁省心和使用稳定，降低新手的决策焦虑。",
        "表达上减少复杂术语，更多使用容易理解的结果型语言。",
    ],
    "channels": [
        "优先覆盖小红书、抖音、B站中的新手养宠教程与避坑类内容场景。",
        "增加第一次养猫、第一次养狗、养宠入门装备清单等内容切入。",
        "优先考虑新手科普向博主、宠物用品避坑内容和教程型KOC。",
    ],
    "launch_actions": [
        "补一版面向新手养宠人群的详情页首屏，突出简单上手和低维护负担。",
        "制作安装演示、清洁步骤和滤芯更换说明等降低门槛的内容素材。",
        "测试新手避坑、入门推荐和低学习成本三类首轮投放角度。",
    ],
    "next_actions": [
        "补充更直观的安装、清洁和滤芯更换说明素材。",
        "验证新手用户对低水位提醒和日常维护成本表达的反馈。",
    ],
    "conclusion": "本轮改版将方案重点切向新手养宠人群，策略表达将更强调简单上手、低学习成本和使用安全感。",
    "insight_note": "后续用户洞察应重点关注新手养宠用户对易上手、维护复杂度、提醒功能和踩坑风险的敏感点。",
}

MULTI_PET_AUDIENCE_RULES = {
    "audience_label": "多宠家庭用户",
    "persona_summary": "以多只宠物共同饮水、补水频率更高、重视容量与稳定性的多宠家庭用户为核心客群。",
    "positioning": "将产品定位为适合多宠家庭的稳定供水方案，强调容量、补水频率控制、清洁效率和连续使用稳定性。",
    "messaging": [
        "文案优先强调多宠共用场景下的容量表现、补水压力更低和连续使用稳定性。",
        "突出易清洁和毛发友好设计，减少多宠环境下的维护负担。",
        "表达上强调实际家庭使用效率，而不是单宠精致化表达。",
    ],
    "channels": [
        "优先覆盖多猫家庭、多狗家庭、家庭养宠效率工具等内容场景。",
        "增加多宠日常维护、毛发管理、饮水频率管理等内容切入。",
        "优先考虑多宠博主、家庭养宠经验分享和实用测评类KOC。",
    ],
    "launch_actions": [
        "补一版面向多宠家庭用户的详情页首屏，突出容量、稳定供水和低维护负担。",
        "制作双猫、多宠家庭和高频饮水场景下的连续使用素材。",
        "测试多宠共用、少加水、少打理三类首轮内容表达。",
    ],
    "next_actions": [
        "验证多宠家庭对容量和补水周期表达的接受度。",
        "补充多宠环境下的毛发管理和清洁效率素材。",
    ],
    "conclusion": "本轮改版将方案重点切向多宠家庭用户，策略表达将更强调容量、稳定供水、低维护负担和多宠共用效率。",
    "insight_note": "后续用户洞察应重点关注多宠家庭对容量、补水频率、毛发管理和连续使用稳定性的敏感点。",
}


class CustomerServiceAgentService:
    def __init__(self, session: Session) -> None:
        self.reports = SqlAlchemyAnalysisRepository(session)
        self.conversations = ConversationService(session)
        self.report_support = ReportSupportService(session)

    def handle_message(
        self,
        report_id: str,
        request: CustomerServiceMessageRequest,
    ) -> CustomerServiceMessageResponse:
        report = self.reports.get_report(report_id)
        latest = self.reports.get_latest_report(report.run_id)
        if latest.report_id != report.report_id:
            raise TradePilotError(
                ErrorCode.VALIDATION_ERROR,
                "Customer service requests must target the latest report version",
                422,
            )
        conversation_id = request.conversation_id or str(uuid4())
        intent = self._classify_intent(request.message)
        if intent is CustomerServiceIntent.EXPLAIN:
            return self._handle_explain(report, request, conversation_id)
        if intent is CustomerServiceIntent.CLARIFICATION_REQUIRED:
            return self._handle_clarification(report, request, conversation_id)
        if intent is CustomerServiceIntent.REJECT:
            return self._handle_reject(report, request, conversation_id)
        if intent is CustomerServiceIntent.LOCALIZED_EDIT:
            return self._handle_localized_edit(report, request, conversation_id)
        if intent is CustomerServiceIntent.MODIFY_POSITIONING:
            return self._handle_positioning_edit(report, request, conversation_id)
        if intent is CustomerServiceIntent.MODIFY_MARKETING_COPY:
            return self._handle_marketing_copy_edit(report, request, conversation_id)
        if intent is CustomerServiceIntent.MODIFY_PROMOTION_STRATEGY:
            return self._handle_promotion_strategy_edit(report, request, conversation_id)
        return self._handle_targeted_regeneration(report, request, conversation_id)

    def get_conversation(self, report_id: str, conversation_id: str) -> CustomerServiceConversationRead:
        report = self.reports.get_report(report_id)
        payload = self.conversations.get(conversation_id)
        metadata = dict(payload["metadata"])
        if metadata.get("report_id") != report.report_id and metadata.get("run_id") != report.run_id:
            raise TradePilotError(
                ErrorCode.VALIDATION_ERROR,
                "Conversation does not belong to this report",
                422,
            )
        personality = metadata.get("personality", CustomerServicePersonality.PROFESSIONAL.value)
        return CustomerServiceConversationRead(
            conversation_id=conversation_id,
            report_id=str(metadata.get("report_id") or report.report_id),
            personality=CustomerServicePersonality(str(personality)),
            confirmed_requirements=list(metadata.get("confirmed_requirements", [])),
            pending_questions=list(metadata.get("pending_questions", [])),
            last_intent=(
                CustomerServiceIntent(str(metadata["last_intent"]))
                if metadata.get("last_intent")
                else None
            ),
            last_affected_modules=list(metadata.get("last_affected_modules", [])),
            latest_report_id=(
                str(metadata["latest_report_id"]) if metadata.get("latest_report_id") else None
            ),
            latest_report_version=(
                int(metadata["latest_report_version"])
                if metadata.get("latest_report_version") is not None
                else None
            ),
            modification_history=list(metadata.get("modification_history", [])),
            messages=[
                CustomerServiceConversationMessageRead(
                    message_id=str(item["message_id"]),
                    role=str(item["role"]),
                    content=str(item["content"]),
                    metadata=dict(item["metadata"]),
                )
                for item in payload["messages"]
            ],
        )

    @staticmethod
    def _classify_intent(message: str) -> CustomerServiceIntent:
        text = message.strip()
        if FULL_REWRITE_PATTERN.search(text) or UNSUPPORTED_NUMERIC_PATTERN.search(text):
            return CustomerServiceIntent.REJECT
        if any(token in text for token in ("为什么", "为何", "解释", "说明")):
            return CustomerServiceIntent.EXPLAIN
        if CustomerServiceAgentService._has_audience_signal(text):
            return CustomerServiceIntent.MODIFY_STRATEGY
        if CustomerServiceAgentService._has_promotion_signal(text):
            return CustomerServiceIntent.MODIFY_PROMOTION_STRATEGY
        if CustomerServiceAgentService._has_marketing_copy_signal(text):
            return CustomerServiceIntent.MODIFY_MARKETING_COPY
        if any(token in text for token in ("改一下定位", "调整一下定位", "改改定位")):
            return CustomerServiceIntent.CLARIFICATION_REQUIRED
        if CustomerServiceAgentService._has_positioning_signal(text):
            return CustomerServiceIntent.MODIFY_POSITIONING
        if any(token in text for token in ("下一步", "注意事项", "假设")) and any(
            token in text for token in ("润色", "改写", "更专业", "更通俗", "更简洁")
        ):
            return CustomerServiceIntent.LOCALIZED_EDIT
        return CustomerServiceIntent.CLARIFICATION_REQUIRED

    def _handle_explain(
        self,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        conversation_id: str,
    ) -> CustomerServiceMessageResponse:
        section_id = self._pick_section_id(report, request.message, default="launch-marketing-strategy")
        result = self.report_support.support(
            report.report_id,
            ReportSupportRequest(
                action="explain",
                section_id=section_id,
                message=request.message,
                conversation_id=conversation_id,
            ),
        )
        reply = self._style_reply(
            request.personality,
            base=str(result["response"]),
            summary="我保留了证据范围和限制说明，没有改动报告内容。",
        )
        self._merge_metadata(
            conversation_id,
            report=report,
            personality=request.personality,
            intent=CustomerServiceIntent.EXPLAIN,
            affected_modules=[],
            pending_questions=[],
            summary=[],
            latest_report_id=report.report_id,
            latest_report_version=report.version,
        )
        return CustomerServiceMessageResponse(
            conversation_id=conversation_id,
            intent=CustomerServiceIntent.EXPLAIN,
            affected_modules=[],
            action_taken=CustomerServiceAction.EXPLAIN,
            reply=reply,
            report_id=report.report_id,
            report_version=report.version,
            changed_section_ids=[],
            change_summary=[],
            pending_questions=[],
        )

    def _handle_clarification(
        self,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        conversation_id: str,
    ) -> CustomerServiceMessageResponse:
        pending_questions = ["你希望新的产品定位更偏高端、性价比，还是功能专业型？"]
        reply = self._style_reply(
            request.personality,
            base="我可以继续调整定位，但这次信息还不够。",
            summary="请先告诉我你想强调的定位方向，我再生成下一版报告。",
        )
        self._record_dialogue(
            conversation_id,
            report=report,
            request=request,
            reply=reply,
            intent=CustomerServiceIntent.CLARIFICATION_REQUIRED,
            action=CustomerServiceAction.CLARIFICATION_REQUIRED,
            affected_modules=["product_positioning"],
            changed_section_ids=[],
            change_summary=[],
            pending_questions=pending_questions,
            latest_report_id=report.report_id,
            latest_report_version=report.version,
        )
        return CustomerServiceMessageResponse(
            conversation_id=conversation_id,
            intent=CustomerServiceIntent.CLARIFICATION_REQUIRED,
            affected_modules=["product_positioning"],
            action_taken=CustomerServiceAction.CLARIFICATION_REQUIRED,
            reply=reply,
            report_id=report.report_id,
            report_version=report.version,
            changed_section_ids=[],
            change_summary=[],
            pending_questions=pending_questions,
        )

    def _handle_reject(
        self,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        conversation_id: str,
    ) -> CustomerServiceMessageResponse:
        reply = self._style_reply(
            request.personality,
            base="这次需求超出了当前客服改版范围。",
            summary="我不能直接整份重写报告，也不能加入没有证据支持的新转化率或预测数字。",
        )
        self._record_dialogue(
            conversation_id,
            report=report,
            request=request,
            reply=reply,
            intent=CustomerServiceIntent.REJECT,
            action=CustomerServiceAction.REJECT,
            affected_modules=[],
            changed_section_ids=[],
            change_summary=[],
            pending_questions=[],
            latest_report_id=report.report_id,
            latest_report_version=report.version,
        )
        return CustomerServiceMessageResponse(
            conversation_id=conversation_id,
            intent=CustomerServiceIntent.REJECT,
            affected_modules=[],
            action_taken=CustomerServiceAction.REJECT,
            reply=reply,
            report_id=report.report_id,
            report_version=report.version,
            changed_section_ids=[],
            change_summary=[],
            pending_questions=[],
        )

    def _handle_localized_edit(
        self,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        conversation_id: str,
    ) -> CustomerServiceMessageResponse:
        latest = self.reports.get_latest_report(report.run_id)
        replacement = list(latest.sections.get("next_actions") or [])
        if not replacement:
            replacement = ["先完成关键验证，再按证据更新上线动作。"]
        replacement = [self._rewrite_line(item, request.message) for item in replacement]
        result = self.report_support.support(
            report.report_id,
            ReportSupportRequest(
                action="edit",
                section_id="next-actions",
                message=request.message,
                replacement=replacement,
                conversation_id=conversation_id,
            ),
        )
        reply = self._style_reply(
            request.personality,
            base="我已经按你的要求做了局部改写。",
            summary="这次只调整了表达方式，没有改动分析范围和证据边界。",
        )
        self._merge_metadata(
            conversation_id,
            report=latest,
            personality=request.personality,
            intent=CustomerServiceIntent.LOCALIZED_EDIT,
            affected_modules=["marketing_copy"],
            pending_questions=[],
            summary=["润色了下一步行动的表达方式"],
            latest_report_id=str(result["report_id"]),
            latest_report_version=int(result["report_version"]),
            changed_section_ids=list(result.get("changed_section_ids", [])),
        )
        return CustomerServiceMessageResponse(
            conversation_id=conversation_id,
            intent=CustomerServiceIntent.LOCALIZED_EDIT,
            affected_modules=["marketing_copy"],
            action_taken=CustomerServiceAction.LOCALIZED_EDIT,
            reply=reply,
            report_id=str(result["report_id"]),
            report_version=int(result["report_version"]),
            changed_section_ids=list(result.get("changed_section_ids", [])),
            change_summary=["润色了下一步行动的表达方式"],
            pending_questions=[],
        )

    def _handle_positioning_edit(
        self,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        conversation_id: str,
    ) -> CustomerServiceMessageResponse:
        direction = self._extract_positioning_direction(request.message)
        if direction is None:
            return self._handle_targeted_clarification(
                report,
                request,
                conversation_id,
                question="你希望新的产品定位更偏高端、性价比，还是功能专业型？",
                summary="请先告诉我你想强调的定位方向，我再生成下一版报告。",
            )
        return self._handle_single_strategy_field_update(
            report,
            request,
            conversation_id,
            intent=CustomerServiceIntent.MODIFY_POSITIONING,
            action=CustomerServiceAction.POSITIONING_EDIT,
            field_name="positioning",
            affected_modules=["product_positioning"],
            change_summary=[f"将产品定位调整为更偏{direction}的表达"],
            reply_base="我已经按你的要求收紧了产品定位表达。",
            reply_summary="这次只调整了定位内容，没有联动重写用户画像、营销文案和推广策略。",
            update_field=lambda strategy, instruction: strategy.__setitem__(
                "positioning",
                self._append_text(strategy.get("positioning"), f"客服本轮要求定位更偏{instruction}。"),
            ),
        )

    def _handle_marketing_copy_edit(
        self,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        conversation_id: str,
    ) -> CustomerServiceMessageResponse:
        direction = self._extract_marketing_copy_direction(request.message)
        if direction is None:
            return self._handle_targeted_clarification(
                report,
                request,
                conversation_id,
                question="你希望营销文案更偏专业、通俗、种草，还是更强调某个卖点？",
                summary="请先告诉我你想调整的文案方向，我再生成下一版报告。",
            )
        return self._handle_single_strategy_field_update(
            report,
            request,
            conversation_id,
            intent=CustomerServiceIntent.MODIFY_MARKETING_COPY,
            action=CustomerServiceAction.MARKETING_COPY_EDIT,
            field_name="messaging_strategy",
            affected_modules=["marketing_copy"],
            change_summary=[f"将营销文案调整为更偏{direction}的表达"],
            reply_base="我已经按你的要求调整了营销文案表达。",
            reply_summary="这次只改了文案方向，没有联动重写用户画像、产品定位和推广策略。",
            update_field=lambda strategy, instruction: strategy.__setitem__(
                "messaging_strategy",
                self._merge_rule_value(
                    strategy.get("messaging_strategy"),
                    [f"客服本轮要求文案更偏{instruction}，请保持既有证据边界。"],
                ),
            ),
        )

    def _handle_promotion_strategy_edit(
        self,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        conversation_id: str,
    ) -> CustomerServiceMessageResponse:
        direction = self._extract_promotion_direction(request.message)
        if direction is None:
            return self._handle_targeted_clarification(
                report,
                request,
                conversation_id,
                question="你希望推广策略更偏保守投放、内容种草，还是更强调某个平台和渠道？",
                summary="请先告诉我你想调整的推广方向，我再生成下一版报告。",
            )
        return self._handle_single_strategy_field_update(
            report,
            request,
            conversation_id,
            intent=CustomerServiceIntent.MODIFY_PROMOTION_STRATEGY,
            action=CustomerServiceAction.PROMOTION_STRATEGY_EDIT,
            field_name="channel_strategy",
            affected_modules=["promotion_strategy"],
            change_summary=[f"将推广策略调整为更偏{direction}的表达"],
            reply_base="我已经按你的要求调整了推广策略。",
            reply_summary="这次只改了渠道和投放表达，没有联动重写用户画像、产品定位和营销文案。",
            update_field=lambda strategy, instruction: strategy.__setitem__(
                "channel_strategy",
                self._merge_rule_value(
                    strategy.get("channel_strategy"),
                    [f"客服本轮要求推广策略更偏{instruction}，请在现有证据范围内执行。"],
                ),
            ),
        )

    def _handle_targeted_regeneration(
        self,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        conversation_id: str,
    ) -> CustomerServiceMessageResponse:
        latest = self.reports.get_latest_report(report.run_id)
        audience = self._extract_audience(request.message)
        rules = self._audience_rules(audience)
        sections = deepcopy(latest.sections)
        changed_section_ids: list[str] = []

        strategy = deepcopy(sections.get("launch_marketing_strategy") or {})
        strategy_evidence_ids = self._section_evidence_ids(strategy)
        if not strategy_evidence_ids:
            raise TradePilotError(
                ErrorCode.VALIDATION_ERROR,
                "Targeted customer-service regeneration requires existing report evidence bindings",
                422,
            )
        if strategy:
            strategy["target_segments"] = [str(rules["audience_label"])]
            strategy["positioning"] = str(rules["positioning"])
            strategy["messaging_strategy"] = self._merge_rule_value(
                strategy.get("messaging_strategy"),
                list(rules["messaging"]),
            )
            strategy["channel_strategy"] = self._merge_rule_value(
                strategy.get("channel_strategy"),
                list(rules["channels"]),
            )
            strategy["launch_actions"] = self._replace_or_extend_list(
                strategy.get("launch_actions"),
                list(rules["launch_actions"]),
            )
            strategy["customer_service_persona_focus"] = str(rules["persona_summary"])
            strategy["customer_service_adjustment"] = {
                "request": request.message,
                "audience_label": str(rules["audience_label"]),
                "evidence_ids": strategy_evidence_ids,
                "changed_fields": [
                    "target_segments",
                    "positioning",
                    "messaging_strategy",
                    "channel_strategy",
                    "launch_actions",
                ],
            }
            sections["launch_marketing_strategy"] = strategy
            changed_section_ids.append("launch-marketing-strategy")

        insights = deepcopy(sections.get("peer_market_user_insights"))
        if insights is not None:
            sections["peer_market_user_insights"] = self._merge_rule_value(
                insights,
                [str(rules["insight_note"])],
            )
            changed_section_ids.append("peer-market-user-insights")

        conclusions = deepcopy(sections.get("data_supported_conclusions") or [])
        sections["data_supported_conclusions"] = self._augment_list(
            conclusions,
            [
                {
                    "conclusion": str(rules["conclusion"]),
                    "source": "customer_service_agent",
                    "evidence_ids": strategy_evidence_ids,
                }
            ],
        )
        changed_section_ids.append("data-supported-conclusions")

        actions = deepcopy(sections.get("next_actions") or [])
        sections["next_actions"] = self._replace_or_extend_list(actions, list(rules["next_actions"]))
        changed_section_ids.append("next-actions")

        updated = self._new_snapshot(
            source=latest.model_copy(update={"sections": sections}),
            version=latest.version + 1,
            parent_report_id=latest.report_id,
            changed_section_ids=changed_section_ids,
        )
        self._write(updated)
        self.reports.save_report_version(
            updated,
            change={
                "action": "customer_service_targeted_regeneration",
                "request": request.message,
                "conversation_id": conversation_id,
                "affected_modules": [
                    "user_persona",
                    "product_positioning",
                    "marketing_copy",
                    "promotion_strategy",
                ],
                "changed_section_ids": changed_section_ids,
                "audience_rules": rules,
                "evidence_ids": strategy_evidence_ids,
            },
        )
        summary = self._change_summary_for_rules(rules)
        reply = self._style_reply(
            request.personality,
            base=f"我已经按{rules['audience_label']}重组了方案重点。",
            summary="这次生成了新的报告版本，并把画像、定位、文案和推广策略都切到了更适合该人群的表达。",
        )
        self._record_dialogue(
            conversation_id,
            report=report,
            request=request,
            reply=reply,
            intent=CustomerServiceIntent.MODIFY_STRATEGY,
            action=CustomerServiceAction.TARGETED_REGENERATION,
            affected_modules=[
                "user_persona",
                "product_positioning",
                "marketing_copy",
                "promotion_strategy",
            ],
            changed_section_ids=changed_section_ids,
            change_summary=summary,
            pending_questions=[],
            latest_report_id=updated.report_id,
            latest_report_version=updated.version,
            confirmed_requirements=[f"target_audience={rules['audience_label']}"],
        )
        return CustomerServiceMessageResponse(
            conversation_id=conversation_id,
            intent=CustomerServiceIntent.MODIFY_STRATEGY,
            affected_modules=[
                "user_persona",
                "product_positioning",
                "marketing_copy",
                "promotion_strategy",
            ],
            action_taken=CustomerServiceAction.TARGETED_REGENERATION,
            reply=reply,
            report_id=updated.report_id,
            report_version=updated.version,
            changed_section_ids=changed_section_ids,
            change_summary=summary,
            pending_questions=[],
        )

    def _handle_single_strategy_field_update(
        self,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        conversation_id: str,
        *,
        intent: CustomerServiceIntent,
        action: CustomerServiceAction,
        field_name: str,
        affected_modules: list[str],
        change_summary: list[str],
        reply_base: str,
        reply_summary: str,
        update_field,
    ) -> CustomerServiceMessageResponse:
        latest = self.reports.get_latest_report(report.run_id)
        sections = deepcopy(latest.sections)
        strategy = deepcopy(sections.get("launch_marketing_strategy") or {})
        strategy_evidence_ids = self._section_evidence_ids(strategy)
        if not strategy or not strategy_evidence_ids:
            raise TradePilotError(
                ErrorCode.VALIDATION_ERROR,
                "Customer-service field updates require existing launch strategy evidence bindings",
                422,
            )

        update_field(strategy, self._extract_requested_direction(request.message) or request.message)
        adjustment = dict(strategy.get("customer_service_adjustment") or {})
        adjustment.update(
            {
                "request": request.message,
                "evidence_ids": strategy_evidence_ids,
                "changed_fields": self._replace_or_extend_list(
                    adjustment.get("changed_fields"),
                    [field_name],
                ),
            }
        )
        strategy["customer_service_adjustment"] = adjustment
        sections["launch_marketing_strategy"] = strategy
        changed_section_ids = ["launch-marketing-strategy"]

        updated = self._new_snapshot(
            source=latest.model_copy(update={"sections": sections}),
            version=latest.version + 1,
            parent_report_id=latest.report_id,
            changed_section_ids=changed_section_ids,
        )
        self._write(updated)
        self.reports.save_report_version(
            updated,
            change={
                "action": action.value,
                "request": request.message,
                "conversation_id": conversation_id,
                "affected_modules": affected_modules,
                "changed_section_ids": changed_section_ids,
                "evidence_ids": strategy_evidence_ids,
            },
        )
        reply = self._style_reply(
            request.personality,
            base=reply_base,
            summary=reply_summary,
        )
        self._record_dialogue(
            conversation_id,
            report=report,
            request=request,
            reply=reply,
            intent=intent,
            action=action,
            affected_modules=affected_modules,
            changed_section_ids=changed_section_ids,
            change_summary=change_summary,
            pending_questions=[],
            latest_report_id=updated.report_id,
            latest_report_version=updated.version,
        )
        return CustomerServiceMessageResponse(
            conversation_id=conversation_id,
            intent=intent,
            affected_modules=affected_modules,
            action_taken=action,
            reply=reply,
            report_id=updated.report_id,
            report_version=updated.version,
            changed_section_ids=changed_section_ids,
            change_summary=change_summary,
            pending_questions=[],
        )

    def _handle_targeted_clarification(
        self,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        conversation_id: str,
        *,
        question: str,
        summary: str,
    ) -> CustomerServiceMessageResponse:
        pending_questions = [question]
        reply = self._style_reply(
            request.personality,
            base="我可以继续调整，但这次信息还不够。",
            summary=summary,
        )
        self._record_dialogue(
            conversation_id,
            report=report,
            request=request,
            reply=reply,
            intent=CustomerServiceIntent.CLARIFICATION_REQUIRED,
            action=CustomerServiceAction.CLARIFICATION_REQUIRED,
            affected_modules=[],
            changed_section_ids=[],
            change_summary=[],
            pending_questions=pending_questions,
            latest_report_id=report.report_id,
            latest_report_version=report.version,
        )
        return CustomerServiceMessageResponse(
            conversation_id=conversation_id,
            intent=CustomerServiceIntent.CLARIFICATION_REQUIRED,
            affected_modules=[],
            action_taken=CustomerServiceAction.CLARIFICATION_REQUIRED,
            reply=reply,
            report_id=report.report_id,
            report_version=report.version,
            changed_section_ids=[],
            change_summary=[],
            pending_questions=pending_questions,
        )

    def _record_dialogue(
        self,
        conversation_id: str,
        *,
        report: FinalReport,
        request: CustomerServiceMessageRequest,
        reply: str,
        intent: CustomerServiceIntent,
        action: CustomerServiceAction,
        affected_modules: list[str],
        changed_section_ids: list[str],
        change_summary: list[str],
        pending_questions: list[str],
        latest_report_id: str,
        latest_report_version: int,
        confirmed_requirements: list[str] | None = None,
    ) -> None:
        base_metadata = {
            "kind": "customer_service",
            "run_id": report.run_id,
            "report_id": report.report_id,
            "personality": request.personality.value,
        }
        self.conversations.add_message(
            conversation_id,
            role="user",
            content=request.message,
            metadata={
                "intent": intent.value,
                "action_taken": action.value,
                "affected_modules": affected_modules,
            },
            conversation_metadata=base_metadata,
        )
        self.conversations.add_message(
            conversation_id,
            role="assistant",
            content=reply,
            metadata={
                "intent": intent.value,
                "action_taken": action.value,
                "changed_section_ids": changed_section_ids,
                "change_summary": change_summary,
                "pending_questions": pending_questions,
                "result_report_id": latest_report_id,
                "result_report_version": latest_report_version,
            },
        )
        self._merge_metadata(
            conversation_id,
            report=report,
            personality=request.personality,
            intent=intent,
            affected_modules=affected_modules,
            pending_questions=pending_questions,
            summary=change_summary,
            latest_report_id=latest_report_id,
            latest_report_version=latest_report_version,
            changed_section_ids=changed_section_ids,
            confirmed_requirements=confirmed_requirements or [],
        )

    def _merge_metadata(
        self,
        conversation_id: str,
        *,
        report: FinalReport,
        personality: CustomerServicePersonality,
        intent: CustomerServiceIntent,
        affected_modules: list[str],
        pending_questions: list[str],
        summary: list[str],
        latest_report_id: str,
        latest_report_version: int,
        changed_section_ids: list[str] | None = None,
        confirmed_requirements: list[str] | None = None,
    ) -> None:
        current = self.conversations.get(conversation_id)
        metadata = dict(current["metadata"])
        history = list(metadata.get("modification_history", []))
        if summary or changed_section_ids:
            history.append(
                {
                    "timestamp": utc_now().isoformat(),
                    "intent": intent.value,
                    "changed_section_ids": changed_section_ids or [],
                    "change_summary": summary,
                }
            )
        merged_requirements = list(
            dict.fromkeys([*metadata.get("confirmed_requirements", []), *(confirmed_requirements or [])])
        )
        self.conversations.update_metadata(
            conversation_id,
            {
                "kind": "customer_service",
                "run_id": report.run_id,
                "report_id": report.report_id,
                "personality": personality.value,
                "confirmed_requirements": merged_requirements,
                "pending_questions": pending_questions,
                "last_intent": intent.value,
                "last_affected_modules": affected_modules,
                "latest_report_id": latest_report_id,
                "latest_report_version": latest_report_version,
                "modification_history": history,
            },
        )

    @staticmethod
    def _pick_section_id(report: FinalReport, message: str, *, default: str) -> str:
        if "注意事项" in message:
            return "prelaunch-considerations"
        if "假设" in message:
            return "reasoned-hypotheses"
        if "策略" in message:
            return "launch-marketing-strategy"
        if default in {item.section_id for item in report.section_index.values()}:
            return default
        return next(iter(report.section_index.values())).section_id

    @staticmethod
    def _extract_audience(message: str) -> str:
        match = AUDIENCE_PATTERN.search(message)
        if match:
            return match.group(1).strip()
        if STUDENT_AUDIENCE_KEYWORD in message:
            return STUDENT_AUDIENCE_RULES["audience_label"]
        if any(keyword in message for keyword in WHITE_COLLAR_KEYWORDS):
            return WHITE_COLLAR_AUDIENCE_RULES["audience_label"]
        if any(keyword in message for keyword in BEGINNER_PET_OWNER_KEYWORDS):
            return BEGINNER_PET_OWNER_RULES["audience_label"]
        if any(keyword in message for keyword in MULTI_PET_KEYWORDS):
            return MULTI_PET_AUDIENCE_RULES["audience_label"]
        return DEFAULT_AUDIENCE_LABEL

    @staticmethod
    def _extract_positioning_direction(message: str) -> str | None:
        return CustomerServiceAgentService._extract_pattern_value(
            message,
            POSITIONING_DIRECTION_PATTERN,
            fallback_tokens=("高端", "性价比", "专业", "年轻", "学生", "品质"),
        )

    @staticmethod
    def _extract_marketing_copy_direction(message: str) -> str | None:
        return CustomerServiceAgentService._extract_pattern_value(
            message,
            MARKETING_COPY_DIRECTION_PATTERN,
            fallback_tokens=("专业", "通俗", "简洁", "种草", "高端", "年轻"),
        )

    @staticmethod
    def _extract_promotion_direction(message: str) -> str | None:
        return CustomerServiceAgentService._extract_pattern_value(
            message,
            PROMOTION_DIRECTION_PATTERN,
            fallback_tokens=("保守", "激进", "种草", "抖音", "小红书", "B站", "微信"),
        )

    @staticmethod
    def _extract_requested_direction(message: str) -> str | None:
        return (
            CustomerServiceAgentService._extract_positioning_direction(message)
            or CustomerServiceAgentService._extract_marketing_copy_direction(message)
            or CustomerServiceAgentService._extract_promotion_direction(message)
        )

    @staticmethod
    def _extract_pattern_value(
        message: str,
        pattern: re.Pattern[str],
        *,
        fallback_tokens: tuple[str, ...],
    ) -> str | None:
        match = pattern.search(message)
        if match:
            return match.group(1).strip()
        for token in fallback_tokens:
            if token in message:
                return token
        return None

    @staticmethod
    def _has_audience_signal(message: str) -> bool:
        return bool(AUDIENCE_PATTERN.search(message)) or any(
            token in message
            for token in (
                "目标用户",
                "用户群体",
                "大学生",
                "白领",
                "上班族",
                "新手养宠",
                "养宠新手",
                "多宠",
                "多猫",
                "多狗",
            )
        )

    @staticmethod
    def _has_positioning_signal(message: str) -> bool:
        return "定位" in message

    @staticmethod
    def _has_marketing_copy_signal(message: str) -> bool:
        return any(token in message for token in ("营销文案", "文案")) and "目标用户" not in message

    @staticmethod
    def _has_promotion_signal(message: str) -> bool:
        return any(token in message for token in ("推广策略", "渠道策略", "投放策略", "推广渠道", "投放渠道"))

    @staticmethod
    def _audience_rules(audience: str) -> dict[str, object]:
        if STUDENT_AUDIENCE_KEYWORD in audience:
            return dict(STUDENT_AUDIENCE_RULES)
        if (
            any(keyword in audience for keyword in WHITE_COLLAR_KEYWORDS)
            or audience == WHITE_COLLAR_AUDIENCE_RULES["audience_label"]
        ):
            return dict(WHITE_COLLAR_AUDIENCE_RULES)
        if (
            any(keyword in audience for keyword in BEGINNER_PET_OWNER_KEYWORDS)
            or audience == BEGINNER_PET_OWNER_RULES["audience_label"]
        ):
            return dict(BEGINNER_PET_OWNER_RULES)
        if (
            any(keyword in audience for keyword in MULTI_PET_KEYWORDS)
            or audience == MULTI_PET_AUDIENCE_RULES["audience_label"]
        ):
            return dict(MULTI_PET_AUDIENCE_RULES)
        return {
            "audience_label": audience,
            "persona_summary": f"当前版本新增面向{audience}的人群视角。",
            "positioning": f"将产品定位调整为更贴近{audience}使用场景和购买动机的表达。",
            "messaging": [f"文案重点改为更贴近{audience}的语言、场景和决策关注点。"],
            "channels": [f"渠道优先覆盖{audience}更常出现的内容平台和决策场景。"],
            "launch_actions": [
                f"补一版面向{audience}的详情页和首发素材。",
                f"验证{audience}对当前价格、表达和渠道策略的接受度。",
            ],
            "next_actions": [
                f"补充面向{audience}的文案和素材版本。",
                f"优先验证{audience}的场景适配度和价格接受度。",
            ],
            "conclusion": f"本轮改版将方案重点切向{audience}，属于基于既有证据的策略重组，不代表新增市场事实。",
            "insight_note": f"后续用户洞察应重点关注{audience}对价格、表达和场景适配度的敏感点。",
        }

    @staticmethod
    def _change_summary_for_rules(rules: dict[str, object]) -> list[str]:
        audience_label = str(rules["audience_label"])
        if audience_label == STUDENT_AUDIENCE_RULES["audience_label"]:
            return [
                "将用户画像重心切换为大学生群体",
                "产品定位改为宿舍友好、颜值与性价比兼顾的学生向表达",
                "营销文案改为更强调安静、省心清洁和社交分享场景",
                "推广策略切向校园内容平台、学生KOC和宿舍场景种草",
            ]
        if audience_label == WHITE_COLLAR_AUDIENCE_RULES["audience_label"]:
            return [
                "将用户画像重心切换为年轻白领",
                "产品定位改为品质感、静音和家居融合兼顾的都市向表达",
                "营销文案更强调省心维护、质感和生活效率",
                "推广策略切向品质生活内容场景和都市养宠KOC",
            ]
        if audience_label == BEGINNER_PET_OWNER_RULES["audience_label"]:
            return [
                "将用户画像重心切换为新手养宠人群",
                "产品定位改为更强调简单上手和低学习成本",
                "营销文案更强调好清洁、低焦虑和使用安全感",
                "推广策略切向新手教程、避坑和入门内容场景",
            ]
        if audience_label == MULTI_PET_AUDIENCE_RULES["audience_label"]:
            return [
                "将用户画像重心切换为多宠家庭用户",
                "产品定位改为更强调容量、稳定供水和低维护负担",
                "营销文案更强调多宠共用效率和连续使用稳定性",
                "推广策略切向多宠家庭内容场景和实用型KOC",
            ]
        return [
            f"将用户画像重心切换为{audience_label}",
            "同步更新产品定位表达",
            "同步更新营销文案方向",
            "同步更新推广策略与行动建议",
        ]

    @staticmethod
    def _style_reply(
        personality: CustomerServicePersonality,
        *,
        base: str,
        summary: str,
    ) -> str:
        if personality is CustomerServicePersonality.SIMPLE:
            return f"{base}{summary}"
        if personality is CustomerServicePersonality.PROFESSIONAL:
            return f"{base}本次调整严格限定在现有证据和报告结构范围内。{summary}"
        if personality is CustomerServicePersonality.COMPANION:
            return f"{base}我先帮你把这一步稳妥处理好。{summary}"
        return f"{base}这次我也顺手把可延展的优化方向一起收拢出来了。{summary}"

    @staticmethod
    def _append_text(value: object, addition: str) -> str:
        text = str(value or "").strip()
        if not text:
            return addition
        return f"{text} {addition}"

    @staticmethod
    def _augment_list(value: object, additions: list[object]) -> list[object]:
        items = list(value) if isinstance(value, list) else ([] if value is None else [value])
        items.extend(additions)
        return items

    @staticmethod
    def _replace_or_extend_list(value: object, additions: list[object]) -> list[object]:
        items = list(value) if isinstance(value, list) else ([] if value is None else [value])
        result: list[object] = []
        seen: set[str] = set()
        for item in [*items, *additions]:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def _merge_rule_value(value: object, lines: list[str]) -> object:
        if isinstance(value, list):
            result: list[str] = []
            seen: set[str] = set()
            for item in [*value, *lines]:
                text = str(item)
                if text in seen:
                    continue
                seen.add(text)
                result.append(text)
            return result
        if isinstance(value, dict):
            updated = dict(value)
            updated["customer_service_adjustment"] = lines
            return updated
        return CustomerServiceAgentService._append_text(value, " ".join(lines))

    @staticmethod
    def _section_evidence_ids(value: object) -> list[str]:
        found: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"evidence_ids", "evidence_id"}:
                    if isinstance(item, list):
                        found.extend(str(entry) for entry in item if entry)
                    elif item:
                        found.append(str(item))
                else:
                    found.extend(CustomerServiceAgentService._section_evidence_ids(item))
        elif isinstance(value, list):
            for item in value:
                found.extend(CustomerServiceAgentService._section_evidence_ids(item))
        return list(dict.fromkeys(found))

    @staticmethod
    def _rewrite_line(value: object, request_text: str) -> str:
        text = str(value)
        if "更通俗" in request_text or "简单易懂" in request_text:
            return f"{text}，表述更直接，方便快速执行。"
        if "更专业" in request_text or "专业" in request_text:
            return f"{text}，建议以更清晰的验证目标和执行优先级呈现。"
        if "更简洁" in request_text or "简洁" in request_text:
            return f"{text}，请只保留最关键的执行动作和判断标准。"
        if "更有创意" in request_text or "更创新" in request_text or "创新" in request_text:
            return f"{text}，可以再补充更有启发性的创意表达与尝试方向。"
        return f"{text}，请按本轮修改要求优化表达，但不要改变证据边界和分析结论。"

    @staticmethod
    def _new_snapshot(
        *,
        source: FinalReport,
        version: int,
        parent_report_id: str,
        changed_section_ids: list[str],
    ) -> FinalReport:
        report_id = str(uuid4())
        directory = Path(source.json_path).parent
        return source.model_copy(
            update={
                "report_id": report_id,
                "version": version,
                "parent_report_id": parent_report_id,
                "changed_section_ids": changed_section_ids,
                "json_path": str((directory / f"{report_id}.json").resolve()),
                "markdown_path": str((directory / f"{report_id}.md").resolve()),
                "created_at": utc_now(),
            }
        )

    @staticmethod
    def _write(report: FinalReport) -> None:
        Path(report.json_path).write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        Path(report.markdown_path).write_text(
            ReportExporter._markdown_with_anchors(report),
            encoding="utf-8",
        )
