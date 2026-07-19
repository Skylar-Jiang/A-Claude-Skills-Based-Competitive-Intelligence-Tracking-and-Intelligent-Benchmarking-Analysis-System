from pydantic import BaseModel, Field

from app.core.enums import (
    CustomerServiceAction,
    CustomerServiceIntent,
    CustomerServicePersonality,
)


class CustomerServiceMessageRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1)
    personality: CustomerServicePersonality = CustomerServicePersonality.PROFESSIONAL


class CustomerServiceMessageResponse(BaseModel):
    conversation_id: str
    intent: CustomerServiceIntent
    affected_modules: list[str] = Field(default_factory=list)
    action_taken: CustomerServiceAction
    reply: str
    report_id: str
    report_version: int = Field(ge=1)
    changed_section_ids: list[str] = Field(default_factory=list)
    change_summary: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)


class CustomerServiceConversationMessageRead(BaseModel):
    message_id: str
    role: str
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)


class CustomerServiceConversationRead(BaseModel):
    conversation_id: str
    report_id: str
    personality: CustomerServicePersonality
    confirmed_requirements: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)
    last_intent: CustomerServiceIntent | None = None
    last_affected_modules: list[str] = Field(default_factory=list)
    latest_report_id: str | None = None
    latest_report_version: int | None = None
    modification_history: list[dict[str, object]] = Field(default_factory=list)
    messages: list[CustomerServiceConversationMessageRead] = Field(default_factory=list)
