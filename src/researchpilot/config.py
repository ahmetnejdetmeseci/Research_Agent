"""Load and validate ResearchPilot configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from researchpilot.domain import InterestProfile

CONFIG_PATH_ENV = "RESEARCHPILOT_CONFIG"
OLLAMA_URL_ENV = "RESEARCHPILOT_OLLAMA_URL"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
DEFAULT_CONFIG_PATH = Path("config/profile.yaml")
ArxivCategory = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[a-z][a-z0-9-]*(?:\.[A-Za-z0-9-]+)?$",
    ),
]
NonEmptyQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
SourcePattern = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
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


class GitHubConfig(ConfigurationModel):
    """Settings used by GitHub repository discovery."""

    enabled: bool = False
    queries: list[NonEmptyQuery] = Field(default_factory=list)
    max_results: int = Field(default=25, ge=1, le=1_000)
    lookback_days: int = Field(default=30, ge=1, le=3_650)
    max_readme_characters: int = Field(default=30_000, ge=1_000, le=1_000_000)

    @field_validator("queries")
    @classmethod
    def queries_must_be_unique(cls, value: list[str]) -> list[str]:
        """Reject duplicate search queries using case-insensitive comparison."""

        normalized = [query.casefold() for query in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("queries must be unique")
        return value

    @model_validator(mode="after")
    def enabled_source_requires_queries(self) -> Self:
        """Ensure an enabled GitHub source has something to search for."""

        if self.enabled and not self.queries:
            raise ValueError("at least one query is required when GitHub is enabled")
        return self


class SourcesConfig(ConfigurationModel):
    """Configuration for external discovery sources."""

    arxiv: ArxivConfig
    github: GitHubConfig = Field(default_factory=GitHubConfig)


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
    max_repositories_per_run: int = Field(default=10, ge=1, le=100)


class DigestConfig(ConfigurationModel):
    """Settings for bounded local Markdown digest generation."""

    output_directory: Path = Path("digests")
    max_papers: int = Field(default=10, ge=1, le=100)
    max_repositories: int = Field(default=10, ge=1, le=100)


class ObsidianExportConfig(ConfigurationModel):
    """Filesystem destination settings for Obsidian digest notes."""

    vault_path: Path | None = None
    folder: str = Field(default="ResearchPilot", min_length=1, max_length=256)

    @field_validator("vault_path", mode="before")
    @classmethod
    def vault_path_must_not_be_empty(cls, value: object) -> object:
        """Distinguish an omitted vault from an accidental empty path."""

        if isinstance(value, str) and not value.strip():
            raise ValueError("vault path cannot be empty")
        return value

    @field_validator("folder")
    @classmethod
    def folder_must_be_safe_relative_posix_path(cls, value: str) -> str:
        """Reject absolute, ambiguous, and parent-traversing vault folders."""

        value = value.strip()
        path = PurePosixPath(value)
        if (
            not value
            or value.startswith("/")
            or "\\" in value
            or ":" in value
            or "//" in value
            or value.endswith("/")
            or path.is_absolute()
            or not path.parts
            or ".." in path.parts
            or str(path) != value
        ):
            raise ValueError("folder must be a normalized relative POSIX path")
        return value


class ExportsConfig(ConfigurationModel):
    """Configuration for digest export destinations."""

    obsidian: ObsidianExportConfig = Field(default_factory=ObsidianExportConfig)


class PaperContentConfig(ConfigurationModel):
    """Opt-in bounds for full-paper download and extraction."""

    enabled: bool = False
    max_download_bytes: int = Field(default=20_000_000, ge=100_000, le=100_000_000)
    max_pages: int = Field(default=40, ge=1, le=500)
    max_characters: int = Field(default=60_000, ge=1_000, le=1_000_000)


class RepositoryContentConfig(ConfigurationModel):
    """Opt-in selection and bounds for GitHub source-file retrieval."""

    enabled: bool = False
    include_patterns: list[SourcePattern] = Field(
        default_factory=lambda: [
            "*.py",
            "**/*.py",
            "*.rs",
            "**/*.rs",
            "*.ts",
            "**/*.ts",
        ]
    )
    exclude_patterns: list[SourcePattern] = Field(
        default_factory=lambda: [
            "tests/**",
            "vendor/**",
            "node_modules/**",
            "dist/**",
            "build/**",
        ]
    )
    max_files: int = Field(default=6, ge=1, le=50)
    max_file_bytes: int = Field(default=200_000, ge=1_000, le=5_000_000)
    max_total_characters: int = Field(default=60_000, ge=1_000, le=1_000_000)

    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def patterns_must_be_safe_and_unique(cls, value: list[str]) -> list[str]:
        """Reject absolute, parent-traversing, duplicate source patterns."""

        normalized: list[str] = []
        for pattern in value:
            if pattern.startswith("/") or "\\" in pattern:
                raise ValueError("source patterns must be relative POSIX patterns")
            if ".." in PurePosixPath(pattern).parts:
                raise ValueError("source patterns cannot contain '..'")
            normalized.append(pattern.casefold())
        if len(normalized) != len(set(normalized)):
            raise ValueError("source patterns must be unique")
        return value

    @model_validator(mode="after")
    def enabled_source_content_requires_patterns(self) -> Self:
        """Ensure enabled source retrieval has an explicit selection."""

        if self.enabled and not self.include_patterns:
            raise ValueError(
                "at least one include pattern is required when source content is enabled"
            )
        return self


class ContentConfig(ConfigurationModel):
    """Optional full-content acquisition settings."""

    papers: PaperContentConfig = Field(default_factory=PaperContentConfig)
    repositories: RepositoryContentConfig = Field(
        default_factory=RepositoryContentConfig
    )


class ResearchPilotConfig(ConfigurationModel):
    """Validated root configuration for ResearchPilot."""

    profile: InterestProfile
    sources: SourcesConfig
    ranking: RankingConfig = Field(default_factory=RankingConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    content: ContentConfig = Field(default_factory=ContentConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    exports: ExportsConfig = Field(default_factory=ExportsConfig)


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


def resolve_github_token(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Return an optional GitHub token without placing it in configuration."""

    environment = os.environ if environ is None else environ
    token = environment.get(GITHUB_TOKEN_ENV)
    if token is None or not token.strip():
        return None
    return token.strip()


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
