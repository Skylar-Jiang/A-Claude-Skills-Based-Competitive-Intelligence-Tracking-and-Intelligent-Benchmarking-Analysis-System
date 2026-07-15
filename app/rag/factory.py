from collections.abc import Callable

from app.core.config import get_settings
from app.core.enums import KnowledgeType
from app.rag.chroma import ChromaKnowledgeStore
from app.rag.contracts import KnowledgeStore
from app.rag.embeddings import create_embedding_function
from app.rag.in_memory import InMemoryKnowledgeStore

KnowledgeStoreFactory = Callable[[], KnowledgeStore]


def create_knowledge_store() -> KnowledgeStore:
    """Create the configured knowledge store.

    Demo and tests keep the lightweight in-memory default. Production can set
    RAG_USE_CHROMA=true and provide embedding configuration.
    """

    settings = get_settings()
    if not settings.rag_use_chroma:
        return InMemoryKnowledgeStore()
    return ChromaKnowledgeStore(
        settings.chroma_persist_dir,
        create_embedding_function(settings),
        collection_names={
            KnowledgeType.PRODUCT_KNOWLEDGE: settings.chroma_product_collection,
            KnowledgeType.REVIEW_INSIGHT: settings.chroma_review_collection,
        },
        score_threshold=settings.rag_score_threshold,
    )
