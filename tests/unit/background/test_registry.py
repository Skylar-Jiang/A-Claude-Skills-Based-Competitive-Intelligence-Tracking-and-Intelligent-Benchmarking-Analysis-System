from datetime import date

from app.background.contracts import BackgroundQuery, BackgroundResult
from app.background.registry import BackgroundProviderRegistry


class FakeProvider:
    name = "fake-background"

    def query(self, query: BackgroundQuery) -> BackgroundResult:
        return BackgroundResult(provider=self.name, query=query)


def test_registry_is_optional_and_resolves_named_provider() -> None:
    registry = BackgroundProviderRegistry()
    query = BackgroundQuery(
        product_name="New fountain",
        product_type="pet water fountain",
        market="United States",
        jurisdiction="US",
        platform="Amazon",
        context_types=["platform_policy", "compliance"],
        effective_date=date(2026, 7, 1),
        query_date=date(2026, 7, 15),
        user_constraints={"launch_window": "Q4"},
    )

    assert registry.query(query) is None
    registry.register(FakeProvider())
    result = registry.query(query, provider_name="fake-background")

    assert result is not None
    assert result.provider == "fake-background"
    assert result.query == query
