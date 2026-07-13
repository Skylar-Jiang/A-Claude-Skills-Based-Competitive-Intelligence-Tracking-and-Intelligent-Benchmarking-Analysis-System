from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.core import KnowledgeSource
from app.rag.contracts import KnowledgeDocument
from app.rag.in_memory import InMemoryKnowledgeStore


class KnowledgeService:
    def __init__(self, session: Session, store: InMemoryKnowledgeStore) -> None:
        self.session = session
        self.store = store

    def rebuild(self) -> int:
        records = self.session.scalars(select(KnowledgeSource)).all()
        documents = [
            KnowledgeDocument(
                document_id=item.source_id,
                product_id=item.product_id or "global",
                knowledge_type=item.knowledge_type,
                content=item.content,
                source_name=str(item.metadata_json.get("source_name", "database")),
                data_origin=item.data_origin,
                metadata=item.metadata_json,
            )
            for item in records
        ]
        self.store.clear()
        return self.store.ingest(documents)
