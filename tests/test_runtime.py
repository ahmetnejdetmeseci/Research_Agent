from datetime import datetime, timezone

import pytest

from researchpilot.domain import Paper, PaperSource, RepositorySource, SoftwareRepository
from researchpilot.persistence import (
    Database,
    PersistenceError,
    SQLitePaperRepository,
    SQLiteRepositoryStore,
)
from researchpilot.runtime import ResearchPilotRuntime


def write_config(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(
        """
profile:
  name: Runtime test
  interests:
    - name: Agents
      keywords: [planning]
      weight: 2
sources:
  arxiv:
    enabled: false
    categories: [cs.AI]
  github:
    enabled: false
ranking:
  minimum_score: 1
  recency_weight: 0
""".strip(),
        encoding="utf-8",
    )
    return path


def test_runtime_requires_current_database(tmp_path) -> None:
    database_path = tmp_path / "missing.db"

    with pytest.raises(PersistenceError, match="not initialized or needs migration"):
        ResearchPilotRuntime.load(write_config(tmp_path), database_path)

    assert database_path.exists() is False


def test_runtime_ranking_reuses_application_services(tmp_path) -> None:
    database_path = tmp_path / "researchpilot.db"
    database = Database(database_path)
    database.initialize()
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    SQLitePaperRepository(database).add(
        Paper(
            source=PaperSource.ARXIV,
            external_id="2610.00001",
            title="Planning for agents",
            abstract="A planning paper.",
            authors=["Ada Lovelace"],
            published_at=now,
            url="https://arxiv.org/abs/2610.00001",
        )
    )
    SQLiteRepositoryStore(database).add(
        SoftwareRepository(
            source=RepositorySource.GITHUB,
            external_id="42",
            full_name="example/planning",
            owner="example",
            name="planning",
            description="Planning tools",
            url="https://github.com/example/planning",
            default_branch="main",
            created_at=now,
            updated_at=now,
        )
    )
    runtime = ResearchPilotRuntime.load(write_config(tmp_path), database_path)

    papers = runtime.rank_papers(now)
    repositories = runtime.rank_repositories(now)

    assert papers.as_of == repositories.as_of == now
    assert papers.selected_count == repositories.selected_count == 1
    assert papers.items[0].paper.external_id == "2610.00001"
    assert repositories.items[0].repository.external_id == "42"
