import sys
import tomllib
from pathlib import Path

from app.core.config import Settings


def test_project_requires_python_312() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert sys.version_info[:2] == (3, 12)
    assert project["requires-python"] == ">=3.12,<3.13"
    assert Path(".python-version").read_text(encoding="utf-8").strip() == "3.12"


def test_settings_load_without_dotenv(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'tradepilot.db'}",
        chroma_dir=tmp_path / "chroma",
        upload_dir=tmp_path / "uploads",
        report_dir=tmp_path / "reports",
    )

    assert settings.app_name == "TradePilot"
    assert settings.app_env == "development"
    assert settings.openai_api_key is None
    assert settings.database_url.startswith("sqlite:///")
