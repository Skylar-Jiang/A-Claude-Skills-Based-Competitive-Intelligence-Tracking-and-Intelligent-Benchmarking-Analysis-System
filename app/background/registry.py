from app.background.contracts import BackgroundProvider, BackgroundQuery, BackgroundResult


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
        if not self._providers:
            return None
        if provider_name is None:
            provider = next(iter(self._providers.values()))
        else:
            provider = self._providers.get(provider_name)
            if provider is None:
                return None
        return provider.query(query)
