from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agents.contracts import ProductMarketAgentInput, UserInsightAgentInput
from app.agents.product_market import ProductMarketAgent
from app.agents.user_insight import UserInsightAgent
from app.core.enums import AgentStatus, DataOrigin, KnowledgeType
from app.rag.pipeline import RetrievalBundle
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductProfile
from tests.builders import build_scaffold_statistics


def _evidence(product: ProductProfile, evidence_id: str = "ev-1") -> EvidenceReference:
    return EvidenceReference(
        evidence_id=evidence_id,
        evidence_type="test",
        knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
        source_name="unit",
        excerpt="Durable harness with reflective material.",
        data_origin=product.data_origin,
        is_demo=product.data_origin is DataOrigin.DEMO,
        metadata={"retrieval_score": 0.9},
    )


def test_product_agent_rejects_model_invented_evidence_id(demo_product: ProductProfile) -> None:
    product = demo_product.model_copy(update={"data_origin": DataOrigin.REAL})
    model = RunnableLambda(
        lambda _: AIMessage(
            content='{"status":"succeeded","product_summary":"ok","evidence_ids":["fake"],'
            '"conclusions":[{"conclusion":"claim","conclusion_type":"risk","confidence":0.8,'
            '"evidence_ids":["fake"],"data_gaps":[]}],"data_gaps":[]}'
        )
    )
    output = ProductMarketAgent(model=model).run(
        ProductMarketAgentInput(
            product=product,
            evidence=[_evidence(product)],
            statistics=build_scaffold_statistics(product),
        )
    )

    assert output.evidence_ids == []
    assert output.conclusions[0].evidence_ids == []
    assert output.conclusions[0].data_gaps[0].code == "claim_without_valid_evidence"


def test_user_agent_returns_insufficient_evidence_without_reviews(demo_product: ProductProfile) -> None:
    output = UserInsightAgent().run(
        UserInsightAgentInput(product=demo_product, evidence=[], statistics=build_scaffold_statistics(demo_product))
    )

    assert output.status is AgentStatus.INSUFFICIENT_EVIDENCE
    assert output.data_gaps[0].field == "review_insight"


def test_product_agent_real_mode_uses_retrieval_pipeline(demo_product: ProductProfile) -> None:
    product = demo_product.model_copy(update={"data_origin": DataOrigin.REAL})
    evidence = _evidence(product, "RAG-PRODUCT-1")
    evidence.metadata.update({"product_id": product.product_id, "vector_score": 0.9})

    class FakePipeline:
        def retrieve_product_evidence(self, profile, constraints, *, deep=False):  # type: ignore[no-untyped-def]
            assert profile.product_id == product.product_id
            assert constraints["target_market"] == "amazon_us"
            return RetrievalBundle(
                original_query="product functions parameters",
                rewritten_queries=[],
                executed_queries=["product functions parameters"],
                collection="product_knowledge",
                filters={"product_id": product.product_id},
                evidence=[evidence],
                fetched_count=1,
                accepted_count=1,
                rejected_count=0,
                duplicate_count=0,
                sufficient=True,
            )

    model = RunnableLambda(
        lambda _: AIMessage(
            content='{"status":"succeeded","product_summary":"ok","evidence_ids":["RAG-PRODUCT-1"],'
            '"conclusions":[{"conclusion":"claim","conclusion_type":"scope","confidence":0.8,'
            '"evidence_ids":["RAG-PRODUCT-1"],"data_gaps":[]}],"data_gaps":[]}'
        )
    )
    output = ProductMarketAgent(model=model, retrieval_pipeline=FakePipeline()).run(  # type: ignore[arg-type]
        ProductMarketAgentInput(
            product=product,
            statistics=build_scaffold_statistics(product),
            user_constraints={"target_market": "amazon_us"},
        )
    )
    assert output.evidence_ids == ["RAG-PRODUCT-1"]
    assert output.evidence_references[1]["evidence_id"] == "RAG-PRODUCT-1"
