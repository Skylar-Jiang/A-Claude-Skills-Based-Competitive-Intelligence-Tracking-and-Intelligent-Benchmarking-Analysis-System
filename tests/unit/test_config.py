import pytest

from app.core.config import Settings


def test_real_model_configured_accepts_deepseek_only_text_stack() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-deepseek-key",
        model_analysis="deepseek-v4-flash",
        model_fast="deepseek-v4-flash",
        model_report="deepseek-v4-flash",
    )

    assert settings.real_model_configured is True


def test_real_model_configured_accepts_deepseek_qwen_mixed_stack() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key="fake-deepseek-credential",
        qwen_api_key="fake-qwen-credential",
        model_analysis="deepseek-analysis-model",
        model_fast="qwen-fast-model",
        model_report="qwen-report-model",
        model_vision="qwen-vision-model",
        embedding_model="text-embedding-v4",
        rag_use_chroma=True,
    )

    assert settings.real_model_configured is True


def test_railway_mixed_provider_environment_names_are_resolved(monkeypatch) -> None:
    fake_environment = {
        "DEEPSEEK_API_KEY": "fake-deepseek-credential",
        "QWEN_API_KEY": "fake-qwen-credential",
        "DEEPSEEK_BASE_URL": "https://deepseek.example/v1",
        "QWEN_BASE_URL": "https://qwen.example/v1",
        "MODEL_ANALYSIS": "deepseek-analysis-model",
        "MODEL_FAST": "qwen-fast-model",
        "MODEL_REPORT": "qwen-report-model",
        "MODEL_VISION": "qwen-vision-model",
    }
    for name, value in fake_environment.items():
        monkeypatch.setenv(name, value)

    settings = Settings(_env_file=None)

    assert settings.deepseek_api_key
    assert settings.qwen_api_key
    assert settings.deepseek_base_url == "https://deepseek.example/v1"
    assert settings.qwen_base_url == "https://qwen.example/v1"
    assert (
        settings.model_analysis,
        settings.model_fast,
        settings.model_report,
        settings.model_vision,
    ) == (
        "deepseek-analysis-model",
        "qwen-fast-model",
        "qwen-report-model",
        "qwen-vision-model",
    )


def test_deployment_allowlists_are_normalized() -> None:
    settings = Settings(
        _env_file=None,
        cors_allowed_origins=" https://tradepilot-preview.vercel.app/, http://127.0.0.1:5173 ",
        trusted_hosts=" tradepilot-staging.up.railway.app, healthcheck.railway.app ",
    )

    assert settings.cors_origins == [
        "https://tradepilot-preview.vercel.app",
        "http://127.0.0.1:5173",
    ]
    assert settings.allowed_hosts == [
        "tradepilot-staging.up.railway.app",
        "healthcheck.railway.app",
    ]


def test_deployment_allowlists_reject_unrestricted_wildcards() -> None:
    with pytest.raises(ValueError, match="CORS_ALLOWED_ORIGINS"):
        Settings(_env_file=None, cors_allowed_origins="*")

    with pytest.raises(ValueError, match="TRUSTED_HOSTS"):
        Settings(_env_file=None, trusted_hosts="*")
