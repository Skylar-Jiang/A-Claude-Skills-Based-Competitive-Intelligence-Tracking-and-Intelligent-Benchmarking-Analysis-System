import os

import pytest

from app.agents.contracts import ProductMarketAgentInput
from app.agents.product_market import ProductMarketAgent
from app.core.enums import DataMode, DataOrigin, KnowledgeType
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
