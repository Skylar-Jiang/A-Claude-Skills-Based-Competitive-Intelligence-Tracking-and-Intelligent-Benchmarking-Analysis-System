from app.core.enums import AgentStatus, KnowledgeType, RetrievalScope
from app.rag.contracts import KnowledgeDocument
from app.schemas.common import DataGap
from app.schemas.evidence import EvidenceReference, RetrievalResult


class InMemoryKnowledgeStore:
    """Deterministic test/demo store; it intentionally performs no semantic ranking."""

    def __init__(self) -> None:
        self._documents: dict[str, KnowledgeDocument] = {}

    @property
    def documents(self) -> list[KnowledgeDocument]:
        return list(self._documents.values())

    def ingest(self, documents: list[KnowledgeDocument]) -> int:
        for document in documents:
            self._documents[document.document_id] = document
        return len(documents)

    def clear(self) -> None:
        self._documents.clear()

    def retrieve(
        self,
        *,
        query: str,
        product_id: str,
        knowledge_type: KnowledgeType,
        top_k: int = 5,
        scope: RetrievalScope = RetrievalScope.EXACT_PRODUCT,
        peer_group_id: str | None = None,
        filters: dict[str, object] | None = None,
        fetch_k: int | None = None,
    ) -> RetrievalResult:
        del query, fetch_k
        if scope is RetrievalScope.PEER_GROUP and not peer_group_id:
            raise ValueError("peer_group_id is required for peer_group retrieval")
        matches = [
            document
            for document in self._documents.values()
            if document.knowledge_type is knowledge_type
            and (
                document.product_id == product_id
                if scope is RetrievalScope.EXACT_PRODUCT
                else document.metadata.get("peer_group_id") == peer_group_id
            )
            and all(document.metadata.get(key) == value for key, value in (filters or {}).items())
        ][:top_k]
        if not matches:
            return RetrievalResult(
                status=AgentStatus.INSUFFICIENT_EVIDENCE,
                data_gaps=[
                    DataGap(
                        code="no_rag_evidence",
                        field=knowledge_type.value,
                        reason="No matching evidence exists in the scaffold knowledge store.",
                        required_for="agent analysis",
                    )
                ],
            )
        return RetrievalResult(
            status=AgentStatus.SUCCEEDED,
            evidence=[
                EvidenceReference(
                    evidence_id=document.document_id,
                    evidence_type="demo_document",
                    knowledge_type=document.knowledge_type,
                    source_name=document.source_name,
                    source_uri=document.source_uri,
                    excerpt=document.content,
                    data_origin=document.data_origin,
                    is_demo=document.data_origin.value == "demo",
                    metadata={
                        **document.metadata,
                        "product_id": document.product_id,
                        "retrieval_scope": scope.value,
                        **(
                            {"candidate_product_id": product_id, "peer_group_id": peer_group_id}
                            if scope is RetrievalScope.PEER_GROUP
                            else {}
                        ),
                    },
                )
                for document in matches
            ],
        )
