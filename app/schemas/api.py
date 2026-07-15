from pydantic import BaseModel, Field

from app.core.enums import ImplementationStatus


class HealthRead(BaseModel):
    service: str
    status: str
    implementation_status: ImplementationStatus


class FeedbackAccepted(BaseModel):
    session_id: str
    message_id: str
    accepted: bool


class KnowledgeRebuildRead(BaseModel):
    documents_ingested: int
    implementation_status: ImplementationStatus


class ConversationMessageRead(BaseModel):
    message_id: str
    role: str
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)


class ConversationRead(BaseModel):
    session_id: str
    metadata: dict[str, object] = Field(default_factory=dict)
    messages: list[ConversationMessageRead] = Field(default_factory=list)
