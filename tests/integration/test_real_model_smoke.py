import os

import pytest

from app.agents.contracts import ProductMarketAgentInput, UserInsightAgentInput
from app.agents.product_market import ProductMarketAgent
from app.agents.user_insight import UserInsightAgent
from app.core.config import get_settings
from app.core.enums import DataMode, DataOrigin, KnowledgeType
from app.rag.reranker import Reranker
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductCreate, ProductProfile
from app.statistics.contracts import StatisticsResult

pytestmark = [pytest.mark.real_model, pytest.mark.real_data]


@pytest.mark.skipif(os.getenv("RUN_REAL_MODEL_TESTS") != "1", reason="real model smoke is opt-in")
def test_real_product_market_agent_smoke() -> None:
    product = ProductProfile(
        product_id="real-smoke-product",
        data_origin=DataOrigin.REAL,
        **ProductCreate(
            name="Pet harness",
            category="Pet Supplies",
            description="Harness for dogs",
            data_mode=DataMode.REAL,
        ).model_dump(),
    )
    evidence = EvidenceReference(
        evidence_id="real-smoke-evidence",
        evidence_type="test_review",
        knowledge_type=KnowledgeType.PRODUCT_KNOWLEDGE,
        source_name="real smoke fixture",
        excerpt="The harness uses durable neoprene and reflective strips.",
        data_origin=DataOrigin.REAL,
        is_demo=False,
    )
    stats = StatisticsResult(product_id=product.product_id, status="succeeded", data_origin=DataOrigin.REAL)

    output = ProductMarketAgent().run(
        ProductMarketAgentInput(product=product, evidence=[evidence], statistics=stats)
    )

    assert output.data_origin is DataOrigin.REAL
    assert all(item in {"real-smoke-evidence"} for item in output.evidence_ids)


@pytest.mark.skipif(os.getenv("RUN_REAL_MODEL_TESTS") != "1", reason="real model smoke is opt-in")
def test_real_user_insight_agent_smoke() -> None:
    product = ProductProfile(
        product_id="real-smoke-product",
        data_origin=DataOrigin.REAL,
        **ProductCreate(
            name="Pet harness",
            category="Pet Supplies",
            description="Harness for dogs",
            data_mode=DataMode.REAL,
        ).model_dump(),
    )
    evidence = EvidenceReference(
        evidence_id="real-smoke-review",
        evidence_type="test_review",
        knowledge_type=KnowledgeType.REVIEW_INSIGHT,
        source_name="real smoke fixture",
        excerpt="Rating: 5. The harness fits well and the reflective strips help on evening walks.",
        data_origin=DataOrigin.REAL,
        is_demo=False,
        metadata={"rating": 5, "review_id": "real-smoke-review"},
    )
    stats = StatisticsResult(product_id=product.product_id, status="succeeded", data_origin=DataOrigin.REAL)

    output = UserInsightAgent().run(UserInsightAgentInput(product=product, evidence=[evidence], statistics=stats))

    assert output.data_origin is DataOrigin.REAL
    assert all(item in {"real-smoke-review"} for item in output.evidence_ids)


@pytest.mark.real_rerank
@pytest.mark.skipif(os.getenv("RUN_REAL_RERANK_TESTS") != "1", reason="real reranker smoke is opt-in")
def test_real_reranker_smoke_preserves_candidate_mapping(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RERANK_MODEL", "Qwen/Qwen3-Reranker-0.6B")
    get_settings.cache_clear()
    try:
        reranker = Reranker(get_settings())
        items = [
            {"id": "a", "document": "durable dog harness", "metadata": {}, "score": 0.2, "vector_score": 0.2},
            {"id": "b", "document": "fragile cat toy", "metadata": {}, "score": 0.1, "vector_score": 0.1},
        ]
        reranked, summary = reranker.rerank("durable dog harness", items, top_n=2)
    finally:
        get_settings.cache_clear()

    assert summary.used
    assert {item["id"] for item in reranked[:2]} == {"a", "b"}
    assert all(item.get("vector_score") is not None for item in reranked[:2])
    assert all(item.get("rerank_score") is not None for item in reranked[:2])
