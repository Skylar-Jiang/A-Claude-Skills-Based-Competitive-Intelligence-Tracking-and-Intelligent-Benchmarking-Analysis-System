from sqlalchemy.orm import Session

from app.core.enums import DataMode, DataOrigin, KnowledgeType
from app.db.models.core import CompetitorOffer, KnowledgeSource, Review
from app.db.repositories.protocols import ProductRepository
from app.rag.contracts import KnowledgeDocument, KnowledgeStore
from app.schemas.product import ProductCreate, ProductProfile


class DemoDomainAdapter:
    domain_name = "generic_cross_border_demo"
    product_name = "DEMO Portable Organizer"

    def seed(
        self,
        session: Session,
        products: ProductRepository,
        knowledge_store: KnowledgeStore,
    ) -> ProductProfile:
        product = next((item for item in products.list() if item.name == self.product_name), None)
        if product is None:
            product = products.create(
                ProductCreate(
                    name=self.product_name,
                    category="demo-generic-accessory",
                    description="DEMO fixture for backend scaffold verification only.",
                    attributes={"fixture": True, "domain_profile": self.domain_name},
                    features=["DEMO feature placeholder"],
                    target_market="DEMO market",
                    data_mode=DataMode.DEMO,
                ),
                data_origin=DataOrigin.DEMO,
            )

        for index in range(1, 4):
            key = f"demo-offer-{product.product_id}-{index}"
            if session.get(CompetitorOffer, key) is None:
                session.add(
                    CompetitorOffer(
                        offer_id=key,
                        product_id=product.product_id,
                        data_origin=DataOrigin.DEMO.value,
                        attributes_json={"fixture": True, "position": index},
                    )
                )
        for index in range(1, 11):
            key = f"demo-review-{product.product_id}-{index}"
            if session.get(Review, key) is None:
                session.add(
                    Review(
                        review_id=key,
                        product_id=product.product_id,
                        content=f"DEMO review fixture {index}; no real sentiment conclusion.",
                        data_origin=DataOrigin.DEMO.value,
                        metadata_json={"fixture": True},
                    )
                )

        documents = [
            KnowledgeDocument(
                document_id=f"demo-product-knowledge-{product.product_id}",
                product_id=product.product_id,
                knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
                content="DEMO product knowledge fixture; real domain evidence is not included.",
                source_name="TradePilot demo fixture",
                data_origin=DataOrigin.DEMO,
            ),
            KnowledgeDocument(
                document_id=f"demo-review-insight-{product.product_id}",
                product_id=product.product_id,
                knowledge_type=KnowledgeType.REVIEW_INSIGHT,
                content="DEMO review insight fixture; real review analysis is not included.",
                source_name="TradePilot demo fixture",
                data_origin=DataOrigin.DEMO,
            ),
        ]
        for document in documents:
            if session.get(KnowledgeSource, document.document_id) is None:
                session.add(
                    KnowledgeSource(
                        source_id=document.document_id,
                        product_id=product.product_id,
                        knowledge_type=document.knowledge_type.value,
                        content=document.content,
                        data_origin=document.data_origin.value,
                        metadata_json={"source_name": document.source_name, "fixture": True},
                    )
                )
        session.commit()
        knowledge_store.ingest(documents)
        return product
