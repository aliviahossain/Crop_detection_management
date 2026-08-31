"""Central configuration. Everything is env-overridable so the same image runs
on a laptop (synthetic weather, no model) and in a demo deployment."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"), extra="ignore", case_sensitive=False
    )

    app_env: str = "dev"
    database_url: str = f"sqlite:///{(REPO_ROOT / 'cropguard.db').as_posix()}"
    upload_dir: Path = REPO_ROOT / "backend" / "app" / "data" / "uploads"

    # Detection
    yolo_onnx_path: Path = REPO_ROOT / "ml" / "weights" / "best.onnx"
    yolo_pt_path: Path = REPO_ROOT / "ml" / "weights" / "best.pt"
    detection_conf_threshold: float = 0.25
    # Written by ml/tune_thresholds.py; absent until the model is tuned.
    detection_thresholds_path: Path = REPO_ROOT / "ml" / "weights" / "thresholds.json"
    detection_iou_threshold: float = 0.45
    low_confidence_threshold: float = 0.55

    # Weather
    openweather_api_key: str = ""
    weather_provider: str = "openweathermap"
    weather_cache_ttl_seconds: int = 1800

    # Advisory
    chroma_dir: Path = REPO_ROOT / "backend" / "app" / "data" / "chroma"
    kb_dir: Path = REPO_ROOT / "backend" / "app" / "data" / "kb"
    anthropic_api_key: str = ""
    advisory_llm_model: str = "claude-sonnet-5"

    # i18n
    default_language: str = "en"
    supported_languages: str = "en,mr,hi,bn"

    @property
    def languages(self) -> list[str]:
        return [c.strip() for c in self.supported_languages.split(",") if c.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
