from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundError
from app.db.models.core import Conversation, Message


class ConversationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_feedback(self, run_id: str, session_id: str, message: str) -> dict[str, object]:
        conversation = self.session.get(Conversation, session_id)
        if conversation is None:
            conversation = Conversation(
                conversation_id=session_id,
                metadata_json={"analysis_run_id": run_id, "kind": "feedback"},
            )
            self.session.add(conversation)
        record = Message(conversation_id=session_id, role="user", content=message)
        self.session.add(record)
        self.session.commit()
        return {"session_id": session_id, "message_id": record.message_id, "accepted": True}

    def get(self, session_id: str) -> dict[str, object]:
        conversation = self.session.get(Conversation, session_id)
        if conversation is None:
            raise ResourceNotFoundError("conversation", session_id)
        records = self.session.scalars(
            select(Message).where(Message.conversation_id == session_id).order_by(Message.message_id)
        ).all()
        return {
            "session_id": session_id,
            "metadata": conversation.metadata_json,
            "messages": [
                {"message_id": item.message_id, "role": item.role, "content": item.content}
                for item in records
            ],
        }
