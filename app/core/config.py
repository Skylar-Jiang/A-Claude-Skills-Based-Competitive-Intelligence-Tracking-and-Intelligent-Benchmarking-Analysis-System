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
    upload_dir: Path = Path("data/uploads")
    report_dir: Path = Path("data/reports")

    openai_api_key: str | None = None
    openai_base_url: str | None = None
    model_fast: str | None = None
    model_analysis: str | None = None
    model_report: str | None = None
    model_vision: str | None = None

    embedding_model: str | None = None
    embedding_device: str = "cpu"
    log_level: str = "INFO"
    default_data_mode: str = Field(default="demo")

    @property
    def real_model_configured(self) -> bool:
        return bool(self.openai_api_key and self.model_analysis)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
