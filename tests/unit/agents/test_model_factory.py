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

    def fake_chat_openai(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(model_factory, "ChatOpenAI", fake_chat_openai)
    settings = Settings(
        _env_file=None,
        qwen_api_key="test-key",
        model_report="qwen3.7-plus",
    )

    model_factory.create_operations_model(settings)

    assert captured["extra_body"] == {"enable_thinking": False}


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
