from pathlib import Path

import pytest

from researchpilot.config import (
    CONFIG_PATH_ENV,
    OLLAMA_URL_ENV,
    ConfigurationError,
    load_config,
    resolve_config_path,
    resolve_ollama_base_url,
)


def test_example_profile_is_valid() -> None:
    config = load_config("config/profile.example.yaml")

    assert config.profile.name == "AI systems research"
    assert len(config.profile.interests) == 2
    assert config.sources.arxiv.categories == ["cs.AI", "cs.CL"]
    assert config.sources.arxiv.lookback_days == 7
    assert config.ranking.minimum_score == 1.0
    assert config.ranking.recency_weight == 0.5
    assert config.ranking.recency_window_days == 30
    assert str(config.ollama.base_url) == "http://localhost:11434/"
    assert config.ollama.model == "llama3.2"
    assert config.ollama.timeout_seconds == 120
    assert config.analysis.max_papers_per_run == 10


def test_explicit_path_overrides_environment() -> None:
    result = resolve_config_path(
        "explicit.yaml",
        {CONFIG_PATH_ENV: "environment.yaml"},
    )

    assert result == Path("explicit.yaml")


def test_environment_overrides_default_path() -> None:
    result = resolve_config_path(None, {CONFIG_PATH_ENV: "environment.yaml"})

    assert result == Path("environment.yaml")


def test_environment_overrides_ollama_base_url() -> None:
    result = resolve_ollama_base_url(
        "http://configured:11434/",
        {OLLAMA_URL_ENV: "http://environment:11434/"},
    )

    assert result == "http://environment:11434"


def test_invalid_profile_has_actionable_field_path(tmp_path) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(
        """
profile:
  name: Test profile
  interests: []
sources:
  arxiv:
    categories: [cs.AI]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as error:
        load_config(config_path)

    message = str(error.value)
    assert "invalid configuration" in message
    assert "profile.interests" in message


def test_duplicate_arxiv_categories_are_rejected(tmp_path) -> None:
    config_path = tmp_path / "duplicate-category.yaml"
    config_path.write_text(
        """
profile:
  name: Test profile
  interests:
    - name: Agents
      keywords: [planning]
sources:
  arxiv:
    categories: [cs.AI, cs.ai]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="categories must be unique"):
        load_config(config_path)


def test_invalid_arxiv_category_expression_is_rejected(tmp_path) -> None:
    config_path = tmp_path / "invalid-category.yaml"
    config_path.write_text(
        """
profile:
  name: Test profile
  interests:
    - name: Agents
      keywords: [planning]
sources:
  arxiv:
    categories: ["cs.AI OR all:agents"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="sources.arxiv.categories.0"):
        load_config(config_path)


def test_invalid_ranking_threshold_is_rejected(tmp_path) -> None:
    config_path = tmp_path / "invalid-ranking.yaml"
    config_path.write_text(
        """
profile:
  name: Test profile
  interests:
    - name: Agents
      keywords: [planning]
sources:
  arxiv:
    categories: [cs.AI]
ranking:
  minimum_score: -1
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="ranking.minimum_score"):
        load_config(config_path)


def test_invalid_analysis_run_limit_is_rejected(tmp_path) -> None:
    config_path = tmp_path / "invalid-analysis.yaml"
    config_path.write_text(
        """
profile:
  name: Test profile
  interests:
    - name: Agents
      keywords: [planning]
sources:
  arxiv:
    categories: [cs.AI]
analysis:
  max_papers_per_run: 0
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="analysis.max_papers_per_run"):
        load_config(config_path)


def test_invalid_yaml_is_reported(tmp_path) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("profile: [", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid YAML"):
        load_config(config_path)


def test_empty_file_is_reported(tmp_path) -> None:
    config_path = tmp_path / "empty.yaml"
    config_path.write_text("", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="configuration file is empty"):
        load_config(config_path)
