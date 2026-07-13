from typing import Protocol

from sqlalchemy.orm import Session

from app.db.repositories.protocols import ProductRepository
from app.rag.contracts import KnowledgeStore
from app.schemas.product import ProductProfile


class DomainAdapter(Protocol):
    domain_name: str

    def seed(
        self,
        session: Session,
        products: ProductRepository,
        knowledge_store: KnowledgeStore,
    ) -> ProductProfile: ...
