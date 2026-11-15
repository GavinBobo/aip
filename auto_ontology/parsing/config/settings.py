import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


def _parse_env_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"true", "1", "yes", "on"}


def _validate_http_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("must be an absolute http:// or https:// URL")
    return value


class ServerConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    host: str = "0.0.0.0"
    port: int = Field(default=8000, gt=0, le=65535)
    workers: int = Field(default=1, gt=0)


class LayoutAnalyzeModelConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    url: Optional[str] = None
    batch_size: int = Field(default=8, gt=0)
    max_concurrency: int = Field(default=2, gt=0)
    timeout: int = Field(default=60, gt=0)
    retry_times: int = Field(default=2, gt=0)
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    nms_iou_threshold: Optional[float] = Field(default=0.6, ge=0.0, le=1.0)
    provides_reading_order: bool = False

    _validate_url = field_validator("url")(_validate_http_url)


class OXRModelConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    url: Optional[str] = None
    model_name: str = "oxr"
    api_key: Optional[str] = None
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    max_tokens: int = Field(default=8192, gt=0)
    max_concurrency: int = Field(default=16, gt=0)
    connect_timeout: int = Field(default=10, gt=0)
    timeout: int = Field(default=120, gt=0)
    retry_times: int = Field(default=2, gt=0)

    _validate_url = field_validator("url")(_validate_http_url)


class PipelineConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    # Where extracted pictures are written. Relative paths resolve against the
    # process CWD, which for this service is the repository root; the default
    # lives under ``logs/`` because the directory is runtime output and is
    # already ignored by git. OXR wrote to ``outputs/`` for its demo server.
    image_output_dir: str = "logs/parsing-assets"
    # Prefix the markdown image link is built from. It has to be something the
    # browser can resolve: this service serves the files itself at
    # ``/api/parsing/assets`` (see ``parsing/router.py``), so a root-relative
    # path works in the app preview and behind any reverse proxy.
    image_url_prefix: str = "/api/parsing/assets"
    # Where the uploaded source files are kept. OXR never stored them — the bytes
    # lived in memory for the length of the request — which makes "what exactly
    # was parsed?" unanswerable after the fact. Relative paths resolve against
    # the process CWD (the repository root).
    upload_dir: str = "logs/parsing-uploads"
    full_overlap_dedupe: bool = False
    table_image_placeholders: bool = False
    table_image_min_score: float = Field(default=0.5, ge=0.0, le=1.0)


class Settings(BaseSettings):
    debug: bool = Field(
        default_factory=lambda: _parse_env_bool(os.getenv("DEBUG"), False)
    )
    server: ServerConfig = Field(default_factory=ServerConfig)
    layout_analyze_model: LayoutAnalyzeModelConfig = Field(
        default_factory=LayoutAnalyzeModelConfig
    )
    oxr_model: OXRModelConfig = Field(default_factory=OXRModelConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    model_settings_path: str = "data/model-settings.json"

    model_config = SettingsConfigDict(
        env_prefix="OXR__",
        env_nested_delimiter="__",
        extra="forbid",
    )

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_model_configuration(cls, data: Any) -> Any:
        if isinstance(data, dict) and "model" in data:
            raise ValueError(
                "The legacy 'model' configuration is no longer supported; "
                "migrate it to 'layout_analyze_model' and 'oxr_model'."
            )

        legacy_environment = sorted(
            name
            for name in os.environ
            if name.upper().startswith("OXR_MODEL__")
            or name.upper().startswith("OXR__MODEL__")
        )
        if legacy_environment:
            raise ValueError(
                "legacy model configuration environment variables are not supported "
                f"({', '.join(legacy_environment)}); migrate to "
                "OXR__LAYOUT_ANALYZE_MODEL__* and OXR__OXR_MODEL__*."
            )
        return data

    def validate_for_server(self) -> None:
        """Validate the server can start before a model backend is chosen.

        Model URLs are intentionally optional here: the server must start
        without loading a model and let the Settings page choose between a
        local backend and a vLLM endpoint. Parse requests validate readiness
        through ``model_backend.ensure_ready()`` instead.
        """

    def validate_model_urls(self) -> None:
        """Raise when both model URLs are missing, for callers that need them."""
        missing = []
        if not self.layout_analyze_model.url:
            missing.append("layout_analyze_model.url")
        if not self.oxr_model.url:
            missing.append("oxr_model.url")
        if missing:
            raise ValueError("Both model URLs are required: " + ", ".join(missing))

    @classmethod
    def load_from_yaml(cls, yaml_path: str) -> "Settings":
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)


settings = Settings()
