from collections.abc import Callable

from app.core.config import Settings, get_settings
from app.core.enums import KnowledgeType
from app.rag.chroma import ChromaKnowledgeStore
from app.rag.contracts import KnowledgeStore
from app.rag.embeddings import create_embedding_function
from app.rag.in_memory import InMemoryKnowledgeStore

KnowledgeStoreFactory = Callable[[], KnowledgeStore]


def create_knowledge_store(settings: Settings | None = None) -> KnowledgeStore:
    """Create the configured knowledge store.

    Demo and tests keep the lightweight in-memory default. Production can set
    RAG_USE_CHROMA=true and provide embedding configuration.
    """

    resolved = settings or get_settings()
    if not resolved.rag_use_chroma:
        return InMemoryKnowledgeStore()
    return ChromaKnowledgeStore(
        resolved.chroma_persist_dir,
        create_embedding_function(resolved),
        collection_names={
            KnowledgeType.PRODUCT_KNOWLEDGE: resolved.chroma_product_collection,
            KnowledgeType.REVIEW_INSIGHT: resolved.chroma_review_collection,
        },
        score_threshold=resolved.rag_score_threshold,
    )
