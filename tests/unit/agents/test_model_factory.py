from app.agents import model_factory
from app.core.config import Settings


def test_deepseek_analysis_model_disables_reasoning_for_bounded_json(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_chat_openai(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(model_factory, "ChatOpenAI", fake_chat_openai)
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-key",
        model_analysis="deepseek-v4-flash",
    )

    model_factory.create_analysis_model(settings)

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured["model_kwargs"] == {"response_format": {"type": "json_object"}}


def test_qwen_models_disable_thinking_for_structured_output(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}
    client_options: dict[str, object] = {}
    direct_client = object()

    def fake_chat_openai(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return object()

    def fake_http_client(**kwargs):  # type: ignore[no-untyped-def]
        client_options.update(kwargs)
        return direct_client

    monkeypatch.setattr(model_factory, "ChatOpenAI", fake_chat_openai)
    monkeypatch.setattr(model_factory.httpx, "Client", fake_http_client)
    settings = Settings(
        _env_file=None,
        qwen_api_key="test-key",
        model_report="qwen3.7-plus",
    )

    model_factory.create_operations_model(settings)

    assert captured["extra_body"] == {"enable_thinking": False}
    assert captured["http_client"] is direct_client
    assert client_options["trust_env"] is False


def test_mixed_provider_routes_each_model_role_by_configured_provider(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    created: list[dict[str, object]] = []

    def fake_chat_openai(**kwargs):  # type: ignore[no-untyped-def]
        created.append(kwargs)
        return object()

    monkeypatch.setattr(model_factory, "ChatOpenAI", fake_chat_openai)
    monkeypatch.setattr(model_factory.httpx, "Client", lambda **_kwargs: object())
    settings = Settings(
        _env_file=None,
        deepseek_api_key="fake-deepseek-credential",
        deepseek_base_url="https://deepseek.example/v1",
        qwen_api_key="fake-qwen-credential",
        qwen_base_url="https://qwen.example/v1",
        model_analysis="deepseek-analysis-model",
        model_report="qwen-report-model",
        model_fast="qwen-fast-model",
    )

    model_factory.create_analysis_model(settings)
    model_factory.create_operations_model(settings)
    model_factory.create_audit_model(settings)

    assert [(item["base_url"], item["model"]) for item in created] == [
        ("https://deepseek.example/v1", "deepseek-analysis-model"),
        ("https://qwen.example/v1", "qwen-report-model"),
        ("https://qwen.example/v1", "qwen-fast-model"),
    ]


def test_minimax_m3_disables_thinking_for_bounded_json(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_chat_openai(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(model_factory, "ChatOpenAI", fake_chat_openai)
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        openai_base_url="https://api.minimaxi.com/v1",
        model_analysis="MiniMax-M3",
    )

    model_factory.create_analysis_model(settings)

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured["model_kwargs"] == {"response_format": {"type": "json_object"}}


def test_generic_openai_compatible_model_does_not_receive_provider_parameters(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_chat_openai(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(model_factory, "ChatOpenAI", fake_chat_openai)
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        openai_base_url="https://example.invalid/v1",
        model_analysis="generic-model",
    )

    model_factory.create_analysis_model(settings)

    assert captured["extra_body"] is None


def test_operations_model_supports_deepseek_without_qwen(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_chat_openai(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(model_factory, "ChatOpenAI", fake_chat_openai)
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-deepseek-key",
        model_report="deepseek-v4-flash",
    )

    model_factory.create_operations_model(settings)

    assert captured["api_key"] == "test-deepseek-key"
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


def test_audit_model_supports_deepseek_without_qwen(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_chat_openai(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(model_factory, "ChatOpenAI", fake_chat_openai)
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-deepseek-key",
        model_fast="deepseek-v4-flash",
    )

    model_factory.create_audit_model(settings)

    assert captured["api_key"] == "test-deepseek-key"
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
