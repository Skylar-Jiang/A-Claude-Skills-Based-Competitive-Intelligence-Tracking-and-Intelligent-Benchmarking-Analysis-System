from datetime import UTC, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundError
from app.db.models.core import Conversation, Message
from app.schemas.common import utc_now


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
        record = Message(conversation_id=session_id, role="user", content=message, metadata_json={})
        self.session.add(record)
        self.session.commit()
        return {"session_id": session_id, "message_id": record.message_id, "accepted": True}

    def add_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, object],
        conversation_metadata: dict[str, object] | None = None,
    ) -> Message:
        conversation = self.session.get(Conversation, session_id)
        if conversation is None:
            conversation = Conversation(
                conversation_id=session_id,
                metadata_json=conversation_metadata or {},
            )
            self.session.add(conversation)
        latest_created_at = self.session.scalar(
            select(Message.created_at)
            .where(Message.conversation_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        created_at = utc_now()
        if latest_created_at is not None:
            if latest_created_at.tzinfo is None:
                latest_created_at = latest_created_at.replace(tzinfo=UTC)
            if created_at <= latest_created_at:
                created_at = latest_created_at + timedelta(microseconds=1)
        record = Message(
            conversation_id=session_id,
            role=role,
            content=content,
            metadata_json=metadata,
            created_at=created_at,
        )
        self.session.add(record)
        self.session.commit()
        return record

    def update_metadata(self, session_id: str, updates: dict[str, object]) -> dict[str, object]:
        conversation = self.session.get(Conversation, session_id)
        if conversation is None:
            raise ResourceNotFoundError("conversation", session_id)
        metadata = dict(conversation.metadata_json or {})
        metadata.update(updates)
        conversation.metadata_json = metadata
        self.session.commit()
        return metadata

    def get(self, session_id: str) -> dict[str, object]:
        conversation = self.session.get(Conversation, session_id)
        if conversation is None:
            raise ResourceNotFoundError("conversation", session_id)
        records = self.session.scalars(
            select(Message)
            .where(Message.conversation_id == session_id)
            .order_by(Message.created_at, Message.message_id)
        ).all()
        return {
            "session_id": session_id,
            "metadata": conversation.metadata_json,
            "messages": [
                {
                    "message_id": item.message_id,
                    "role": item.role,
                    "content": item.content,
                    "metadata": item.metadata_json,
                }
                for item in records
            ],
        }
