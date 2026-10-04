"""Load and validate ResearchPilot configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    ValidationError,
    field_validator,
)

from researchpilot.domain import InterestProfile

CONFIG_PATH_ENV = "RESEARCHPILOT_CONFIG"
OLLAMA_URL_ENV = "RESEARCHPILOT_OLLAMA_URL"
DEFAULT_CONFIG_PATH = Path("config/profile.yaml")
ArxivCategory = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[a-z][a-z0-9-]*(?:\.[A-Za-z0-9-]+)?$",
    ),
]


class ConfigurationError(Exception):
    """A configuration problem that can be shown directly to a user."""


class ConfigurationModel(BaseModel):
    """Base settings shared by strict configuration models."""

    model_config = ConfigDict(extra="forbid", validate_default=True)


class ArxivConfig(ConfigurationModel):
    """Settings used by the future ArXiv discovery adapter."""

    enabled: bool = True
    categories: list[ArxivCategory] = Field(min_length=1)
    max_results: int = Field(default=50, ge=1, le=1_000)
    lookback_days: int = Field(default=7, ge=1, le=365)

    @field_validator("categories")
    @classmethod
    def categories_must_be_unique(cls, value: list[str]) -> list[str]:
        """Reject duplicate ArXiv categories."""

        normalized = [category.casefold() for category in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("categories must be unique")
        return value


class SourcesConfig(ConfigurationModel):
    """Configuration for external discovery sources."""

    arxiv: ArxivConfig


class RankingConfig(ConfigurationModel):
    """Settings for transparent deterministic paper ranking."""

    minimum_score: float = Field(default=1.0, ge=0)
    recency_weight: float = Field(default=0.5, ge=0, le=10)
    recency_window_days: int = Field(default=30, ge=1, le=3_650)


class OllamaConfig(ConfigurationModel):
    """Connection and model settings for local Ollama inference."""

    base_url: HttpUrl = HttpUrl("http://localhost:11434")
    model: str = Field(default="llama3.2", min_length=1)
    timeout_seconds: float = Field(default=120.0, gt=0, le=3_600)


class AnalysisConfig(ConfigurationModel):
    """Limits for one abstract-analysis run."""

    max_papers_per_run: int = Field(default=10, ge=1, le=100)


class ResearchPilotConfig(ConfigurationModel):
    """Validated root configuration for ResearchPilot."""

    profile: InterestProfile
    sources: SourcesConfig
    ranking: RankingConfig = Field(default_factory=RankingConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)


def resolve_config_path(
    explicit_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve config path with CLI, environment, then default precedence."""

    if explicit_path is not None:
        return Path(explicit_path).expanduser()

    environment = os.environ if environ is None else environ
    if configured_path := environment.get(CONFIG_PATH_ENV):
        return Path(configured_path).expanduser()

    return DEFAULT_CONFIG_PATH


def resolve_ollama_base_url(
    configured_url: str | HttpUrl,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve the Ollama endpoint with environment-over-config precedence."""

    environment = os.environ if environ is None else environ
    return environment.get(OLLAMA_URL_ENV, str(configured_url)).rstrip("/")


def load_config(path: str | Path) -> ResearchPilotConfig:
    """Load a YAML file and return its validated configuration."""

    config_path = Path(path)
    try:
        document = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"configuration file not found: {config_path}. "
            "Copy config/profile.example.yaml, pass --config, or set "
            f"{CONFIG_PATH_ENV}."
        ) from exc
    except OSError as exc:
        raise ConfigurationError(
            f"could not read configuration file {config_path}: {exc}"
        ) from exc

    try:
        data: Any = yaml.safe_load(document)
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"invalid YAML in configuration file {config_path}: {exc}"
        ) from exc

    if data is None:
        raise ConfigurationError(f"configuration file is empty: {config_path}")

    try:
        return ResearchPilotConfig.model_validate(data)
    except ValidationError as exc:
        details = "\n".join(
            f"- {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigurationError(
            f"invalid configuration in {config_path}:\n{details}"
        ) from exc
