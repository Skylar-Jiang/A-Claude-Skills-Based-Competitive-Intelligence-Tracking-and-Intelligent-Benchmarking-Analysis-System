from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from app.rag.embeddings import OpenAICompatibleEmbedding, create_embedding_function
from app.rag.factory import create_knowledge_store
from app.rag.in_memory import InMemoryKnowledgeStore


def test_default_knowledge_store_factory_is_lightweight_memory(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("RAG_USE_CHROMA", raising=False)
    monkeypatch.setenv("RAG_USE_CHROMA", "false")
    get_settings.cache_clear()
    try:
        assert isinstance(create_knowledge_store(), InMemoryKnowledgeStore)
    finally:
        get_settings.cache_clear()


def test_app_uses_injected_knowledge_store_factory(tmp_path: Path) -> None:
    store = InMemoryKnowledgeStore()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'factory.db'}",
        report_dir=tmp_path / "reports",
        upload_dir=tmp_path / "uploads",
        chroma_dir=tmp_path / "chroma",
    )

    with TestClient(create_app(settings, knowledge_store_factory=lambda: store)) as client:
        response = client.get("/api/v1/health")
        assert client.app.state.knowledge_store is store

    assert response.status_code == 200


def test_qwen_text_embedding_uses_qwen_credentials_and_supported_batch_size() -> None:
    settings = Settings(
        _env_file=None,
        embedding_model="text-embedding-v4",
        qwen_api_key="test-qwen-key",
        qwen_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        rag_embedding_batch_size=32,
    )

    embedding = create_embedding_function(settings)

    assert isinstance(embedding, OpenAICompatibleEmbedding)
    assert embedding.base_url == settings.qwen_base_url
    assert embedding.batch_size == 10


def test_openai_compatible_embedding_does_not_inherit_system_proxy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"index": 0, "embedding": [1.0, 0.0]}]}

    class Client:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            return None

        def post(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return Response()

    monkeypatch.setattr("app.rag.embeddings.httpx.Client", Client)
    embedding = OpenAICompatibleEmbedding(
        model_name="text-embedding-v4",
        base_url="https://example.invalid/v1",
        api_key="test-key",
        batch_size=10,
        concurrency=1,
        timeout=10,
        max_retries=1,
    )

    assert embedding.embed_documents(["peer product"]) == [[1.0, 0.0]]
    assert captured["trust_env"] is False
