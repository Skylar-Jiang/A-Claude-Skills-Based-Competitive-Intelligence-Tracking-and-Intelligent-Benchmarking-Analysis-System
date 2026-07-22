from app.background.contracts import BackgroundProvider, BackgroundQuery, BackgroundResult
from app.schemas.common import DataGap


class BackgroundProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, BackgroundProvider] = {}

    def register(self, provider: BackgroundProvider) -> None:
        self._providers[provider.name] = provider

    def query(
        self,
        query: BackgroundQuery,
        *,
        provider_name: str | None = None,
    ) -> BackgroundResult | None:
        if provider_name is not None:
            provider = self._providers.get(provider_name)
            if provider is None:
                return BackgroundResult(
                    provider=provider_name,
                    query=query,
                    data_gaps=[
                        DataGap(
                            code="background_provider_unavailable",
                            field="background_provider",
                            reason=f"Requested background provider is not prepared: {provider_name}",
                            required_for="requested product background evidence",
                        )
                    ],
                )
        elif not self._providers:
            return None
        else:
            provider = next(iter(self._providers.values()))
        return provider.query(query)
