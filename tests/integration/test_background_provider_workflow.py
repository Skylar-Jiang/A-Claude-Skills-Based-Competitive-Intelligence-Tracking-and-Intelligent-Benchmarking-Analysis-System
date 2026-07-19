import json
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.background.contracts import (
    BackgroundEvidence,
    BackgroundQuery,
    BackgroundResult,
)
from app.background.providers.us_tariff_provider import USTariffProvider
from app.background.registry import BackgroundProviderRegistry
from app.background.tariff_data import TariffRuleRecord, build_tariff_database
from app.core.config import Settings
from app.core.enums import DataMode, DataOrigin
from app.db.base import Base
from app.db.repositories.sqlalchemy import SqlAlchemyProductRepository
from app.rag.in_memory import InMemoryKnowledgeStore
from app.schemas.analysis import AnalysisRunCreate
from app.schemas.product import ProductCreate
from app.services.analysis_service import AnalysisService


class RecordingProvider:
    name = "recording-provider"

    def __init__(self) -> None:
        self.queries: list[BackgroundQuery] = []

    def query(self, query: BackgroundQuery) -> BackgroundResult:
        self.queries.append(query)
        return BackgroundResult(
            provider=self.name,
            query=query,
            evidence=[
                BackgroundEvidence(
                    evidence_id="background-1",
                    context_type="platform_policy",
                    content="Fixture-only platform context.",
                    source_name="Fake source",
                    source_uri="fixture://background-1",
                    effective_date=date(2026, 7, 1),
                    jurisdiction="US",
                    confidence=0.9,
                )
            ],
        )


def test_fake_background_provider_is_queried_once_and_persisted_with_provenance(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    provider = RecordingProvider()
    registry = BackgroundProviderRegistry()
    registry.register(provider)
    with Session(engine) as session:
        product = SqlAlchemyProductRepository(session).create(
            ProductCreate(
                name="Unlisted fountain",
                category="pet water fountain",
                target_market="United States",
                data_mode=DataMode.DEMO,
            ),
            data_origin=DataOrigin.DEMO,
        )
        service = AnalysisService(
            session=session,
            knowledge_store=InMemoryKnowledgeStore(),
            report_dir=tmp_path,
            settings=Settings(_env_file=None, database_url="sqlite://"),
            background_registry=registry,
        )
        run = service.start(
            AnalysisRunCreate(
                product_id=product.product_id,
                data_mode=DataMode.DEMO,
                target_market="United States",
                jurisdiction="US",
                platform="Amazon",
                background_context_types=["platform_policy"],
                effective_date=date(2026, 7, 1),
                query_date=date(2026, 7, 15),
                user_constraints={"launch_window": "Q4"},
            )
        )

    assert len(provider.queries) == 1
    query = provider.queries[0]
    assert query.product_name == "Unlisted fountain"
    assert query.product_type == "pet water fountain"
    assert query.platform == "Amazon"
    assert query.user_constraints == {"launch_window": "Q4"}
    assert run.state["background_context"]["provider"] == "recording-provider"
    assert any(item["evidence_id"] == "background-1" for item in run.state["rag_evidence"])


def test_no_background_provider_keeps_context_empty(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        product = SqlAlchemyProductRepository(session).create(
            ProductCreate(name="No provider", category="fountain", data_mode=DataMode.DEMO),
            data_origin=DataOrigin.DEMO,
        )
        service = AnalysisService(
            session=session,
            knowledge_store=InMemoryKnowledgeStore(),
            report_dir=tmp_path,
            settings=Settings(_env_file=None, database_url="sqlite://"),
        )
        run = service.start(AnalysisRunCreate(product_id=product.product_id, data_mode=DataMode.DEMO))

    assert run.state["background_context"] is None


def test_us_tariff_provider_persists_real_tariff_evidence_with_provenance(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    mapping_path, database_path = _write_tariff_artifacts(tmp_path)
    registry = BackgroundProviderRegistry()
    registry.register(USTariffProvider(database_path=database_path, mapping_path=mapping_path))
    with Session(engine) as session:
        product = SqlAlchemyProductRepository(session).create(
            ProductCreate(
                name="Cordless pet fountain",
                category="Fountains",
                target_market="United States",
                data_mode=DataMode.DEMO,
            ),
            data_origin=DataOrigin.DEMO,
        )
        service = AnalysisService(
            session=session,
            knowledge_store=InMemoryKnowledgeStore(),
            report_dir=tmp_path,
            settings=Settings(
                _env_file=None,
                database_url="sqlite://",
                trade_hs_mapping_path=mapping_path,
                trade_tariff_db_path=database_path,
            ),
            background_registry=registry,
        )
        run = service.start(
            AnalysisRunCreate(
                product_id=product.product_id,
                data_mode=DataMode.DEMO,
                target_market="United States",
                jurisdiction="US",
                background_context_types=["tariff_rate"],
                effective_date=date(2026, 7, 1),
                query_date=date(2026, 7, 15),
            )
        )
        report = service.get_report(run.report_id)

    assert run.state["background_context"]["provider"] == "us-tariff-provider"
    tariff_evidence = next(item for item in run.state["rag_evidence"] if item["evidence_id"].startswith("us-hts-"))
    assert tariff_evidence["source_name"] == "USITC Harmonized Tariff Schedule"
    assert tariff_evidence["metadata"]["provider"] == "us-tariff-provider"
    assert tariff_evidence["metadata"]["context_type"] == "tariff_rate"
    assert tariff_evidence["metadata"]["jurisdiction"] == "US"
    payload = json.loads(Path(report.json_path).read_text(encoding="utf-8"))
    markdown = Path(report.markdown_path).read_text(encoding="utf-8")
    snapshot = payload["sections"]["tax_and_tariff_snapshot"]
    assert snapshot["provider"] == "us-tariff-provider"
    assert snapshot["jurisdiction"] == "US"
    assert len(snapshot["tariff_evidence"]) == 1
    assert snapshot["tariff_evidence"][0]["source_name"] == "USITC Harmonized Tariff Schedule"
    assert snapshot["decision_inputs"]["primary_tariff_profile"]["hs_code"] == "8421210000"
    assert "additional_duty_present" in snapshot["decision_inputs"]["tariff_risk_flags"]
    assert snapshot["decision_inputs"]["tariff_cost_burden"] == "high"
    assert snapshot["decision_inputs"]["tariff_recommended_actions"]
    tariff_impact = payload["sections"]["tariff_selection_impact"]
    assert tariff_impact["manual_review_required"] is True
    executive_summary = payload["sections"]["executive_summary"]
    assert executive_summary["manual_review_required"] is True
    assert executive_summary["evidence_audit_manual_review_required"] is False
    assert executive_summary["customs_broker_review_required"] is True
    assert tariff_impact["selection_impact"]
    assert "landed cost" in " ".join(tariff_impact["selection_impact"])
    assert any(
        item == "us-hts-8421210000-2026-01-01"
        for item in run.state["operation_plan"]["evidence_ids"]
    )
    assert "## Tax and tariff snapshot" in markdown
    assert "## Tariff impact on selection" in markdown
    assert "landed cost" in markdown


def _write_tariff_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    mapping_path = tmp_path / "config" / "trade" / "hs_mapping.yaml"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(
        yaml.safe_dump(
            {
                "mappings": [
                    {
                        "segment_id": "fountains",
                        "product_types": ["Fountains"],
                        "keywords": ["pet fountain"],
                        "hs_codes": [
                            {
                                "hs_code": "8421210000",
                                "confidence": 0.74,
                                "rationale": "Phase 1 candidate mapping for pet fountains.",
                            }
                        ],
                        "notes": "Use only as a candidate mapping for the existing Fountains category.",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "data" / "external" / "serving" / "tariff_rules.sqlite"
    build_tariff_database(
        [
            TariffRuleRecord(
                market="United States",
                jurisdiction="US",
                hs_code="8421210000",
                hs_version="2026 Rev. 11",
                product_scope="Filtering or purifying machinery for liquids",
                general_rate="Free",
                special_rate_text="",
                additional_duty_text="25%",
                effective_date=date(2026, 1, 1),
                end_date=None,
                source_name="USITC Harmonized Tariff Schedule",
                source_url="https://hts.usitc.gov/export",
            )
        ],
        database_path,
    )
    return mapping_path, database_path
