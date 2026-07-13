import pytest
from pydantic import ValidationError

from app.core.enums import AgentStatus, AuditStatus, DataMode, DataOrigin, ImplementationStatus
from app.schemas.analysis import (
    AuditResult,
    OperationPlan,
    ProductMarketAnalysis,
    UserInsight,
)
from app.schemas.evidence import EvidenceReference
from app.schemas.product import ProductCreate, ProductProfile
from app.workflows.state import TradePilotState


def test_product_profile_keeps_domain_fields_in_attributes() -> None:
    created = ProductCreate(
        name="Demo Portable Organizer",
        category="generic",
        attributes={"custom_field": "custom value"},
        target_market="US",
        data_mode=DataMode.DEMO,
    )
    profile = ProductProfile(
        product_id="prod_demo",
        **created.model_dump(),
        data_origin=DataOrigin.DEMO,
    )

    assert profile.attributes == {"custom_field": "custom value"}
    assert profile.data_origin is DataOrigin.DEMO


def test_scaffold_outputs_require_explicit_markers() -> None:
    market = ProductMarketAnalysis(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        implementation_status=ImplementationStatus.SCAFFOLD,
    )
    insight = UserInsight(
        status=AgentStatus.INSUFFICIENT_EVIDENCE,
        data_origin=DataOrigin.DEMO,
        implementation_status=ImplementationStatus.SCAFFOLD,
    )
    plan = OperationPlan(
        status=AgentStatus.SUCCEEDED,
        data_origin=DataOrigin.DEMO,
        implementation_status=ImplementationStatus.SCAFFOLD,
    )
    audit = AuditResult(
        status=AuditStatus.PASS,
        data_origin=DataOrigin.DEMO,
        implementation_status=ImplementationStatus.SCAFFOLD,
    )

    assert market.implementation_status is ImplementationStatus.SCAFFOLD
    assert insight.conclusions == []
    assert plan.evidence_ids == []
    assert audit.manual_review_required is False


def test_evidence_rejects_mismatched_demo_origin() -> None:
    with pytest.raises(ValidationError):
        EvidenceReference(
            evidence_id="ev_1",
            evidence_type="document",
            knowledge_type="product_knowledge",
            source_name="Demo source",
            excerpt="Demo excerpt",
            data_origin=DataOrigin.REAL,
            is_demo=True,
        )


def test_tradepilot_state_validates_agent_models() -> None:
    profile = ProductProfile(
        product_id="prod_demo",
        name="Demo Portable Organizer",
        category="generic",
        data_mode=DataMode.DEMO,
        data_origin=DataOrigin.DEMO,
    )
    state = TradePilotState(
        task_id="task_demo",
        run_id="run_demo",
        session_id="session_demo",
        thread_id="thread_demo",
        data_mode=DataMode.DEMO,
        product_profile=profile,
        target_market="US",
    )

    assert state.retry_count == 0
    assert state.node_status == {}
