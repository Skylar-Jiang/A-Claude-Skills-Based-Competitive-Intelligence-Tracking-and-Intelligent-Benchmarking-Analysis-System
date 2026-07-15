from app.core.enums import ErrorCode


class TradePilotError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, status_code: int = 400, details: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []


class ResourceNotFoundError(TradePilotError):
    def __init__(self, resource: str, resource_id: str | None = None):
        message = resource if resource_id is None else f"{resource} not found: {resource_id}"
        super().__init__(ErrorCode.RESOURCE_NOT_FOUND, message, 404)


class LLMNotConfiguredError(TradePilotError):
    def __init__(self, message: str = "Real mode requires an API key and analysis model configuration"):
        super().__init__(ErrorCode.LLM_NOT_CONFIGURED, message, 503)


class ScaffoldOnlyError(TradePilotError):
    def __init__(self, mode: str = "real"):
        super().__init__(
            ErrorCode.WORKFLOW_FAILED,
            f"{mode.capitalize()} analysis is not implemented in this scaffold; no mode fallback was used",
            503,
        )


class DataPreparationRequiredError(TradePilotError):
    def __init__(self, component: str, *, stale: bool = False):
        state = "stale" if stale else "missing"
        super().__init__(
            ErrorCode.DATA_PREPARATION_REQUIRED,
            f"Prepared {component} cache is {state}; run the explicit prepare_peer_data command first",
            503,
        )
