from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_debug: bool = False
    app_name: str = "TradePilot"
    app_version: str = "0.1.0"
    app_api_key: str | None = None

    database_url: str = "sqlite:///data/tradepilot.db"
    chroma_dir: Path = Path("data/chroma")
    chroma_persist_dir: Path = Path("data/chroma")
    chroma_product_collection: str = "product_knowledge"
    chroma_review_collection: str = "review_insight"
    upload_dir: Path = Path("data/uploads")
    report_dir: Path = Path("data/reports")

    openai_api_key: str | None = None
    openai_base_url: str | None = None
    model_fast: str | None = None
    model_analysis: str | None = None
    model_report: str | None = None
    model_vision: str | None = None
    model_temperature: float = 0.1
    model_timeout_seconds: int = 120
    model_max_retries: int = 3

    embedding_model: str | None = None
    embedding_device: str = "cpu"
    rerank_model: str | None = None
    rag_fetch_k: int = 30
    rag_top_k: int = 8
    rag_score_threshold: float = 0.0
    rag_batch_size: int = 128
    rag_embedding_batch_size: int = 32
    rag_embedding_concurrency: int = 4
    rag_index_batch_size: int = 32
    rag_chunk_size: int = 2800
    rag_chunk_overlap: int = 300
    rag_use_chroma: bool = False
    rag_manifest_path: Path = Path("data/index_manifest.sqlite")
    log_level: str = "INFO"
    default_data_mode: str = Field(default="demo")

    @property
    def real_model_configured(self) -> bool:
        return bool(self.openai_api_key and self.model_analysis)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
