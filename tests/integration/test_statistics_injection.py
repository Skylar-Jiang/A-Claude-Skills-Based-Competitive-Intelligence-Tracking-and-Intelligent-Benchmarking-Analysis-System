import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.enums import AgentStatus, DataOrigin
from app.main import create_app
from app.schemas.product import ProductProfile
from app.statistics.contracts import StatisticsResult
from app.statistics.factory import create_statistics_provider
from app.statistics.providers.pet_supplies import PetSuppliesStatisticsProvider
from app.statistics.stub import ScaffoldStatisticsProvider


class RecordingStatisticsProvider:
    def __init__(self) -> None:
        self.product_ids: list[str] = []

    def get_statistics(self, *, product: ProductProfile) -> StatisticsResult:
        self.product_ids.append(product.product_id)
        return StatisticsResult(
            product_id=product.product_id,
            status=AgentStatus.INSUFFICIENT_EVIDENCE,
            data_origin=product.data_origin,
        )


def test_api_analysis_uses_injected_session_scoped_statistics_provider(tmp_path: Path) -> None:
    provider = RecordingStatisticsProvider()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'statistics.db'}",
        report_dir=tmp_path / "reports",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
    )
    app = create_app(
        settings,
        statistics_provider_factory=lambda session: provider,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/products",
            json={"name": "DEMO Product", "category": "demo", "data_mode": "demo"},
        )
        product_id = created.json()["data"]["product_id"]
        run = client.post(
            "/api/v1/analysis-runs",
            json={"product_id": product_id, "data_mode": "demo"},
        )
        run_id = run.json()["data"]["run_id"]
        for _ in range(200):
            persisted = client.get(f"/api/v1/analysis-runs/{run_id}").json()["data"]
            if persisted["state"].get("statistics_result"):
                break
            time.sleep(0.01)

    assert run.status_code == 202
    assert provider.product_ids == [product_id]
    assert persisted["state"]["statistics_result"]["product_id"] == product_id


def test_default_statistics_factory_returns_pet_supplies_provider() -> None:
    class DummySession:
        pass

    provider = create_statistics_provider(DummySession())  # type: ignore[arg-type]

    assert isinstance(provider, PetSuppliesStatisticsProvider)


def test_pet_supplies_provider_falls_back_for_demo_product(tmp_path: Path) -> None:
    class DummySession:
        def get(self, *_args, **_kwargs):
            return None

    provider = create_statistics_provider(DummySession())  # type: ignore[arg-type]
    result = provider.get_statistics(
        product=ProductProfile(
            product_id="demo-product",
            data_origin=DataOrigin.DEMO,
            name="Demo Product",
            category="demo",
            data_mode="demo",
        )
    )

    assert isinstance(provider.fallback, ScaffoldStatisticsProvider)
    assert result.status is AgentStatus.INSUFFICIENT_EVIDENCE
