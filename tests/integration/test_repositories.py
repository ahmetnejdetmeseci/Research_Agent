from datetime import datetime, timedelta, timezone

import pytest

from researchpilot.domain import (
    AbstractAnalysis,
    AnalysisStatus,
    Paper,
    PaperSource,
    RunStatus,
)
from researchpilot.persistence import (
    Database,
    PersistenceError,
    SQLiteAnalysisRepository,
    SQLitePaperRepository,
    SQLiteRunRepository,
)


def make_paper(
    external_id: str = "2601.00001",
    *,
    published_at: datetime | None = None,
) -> Paper:
    return Paper(
        source=PaperSource.ARXIV,
        external_id=external_id,
        title=f"Paper {external_id}",
        abstract="A useful abstract.",
        authors=["Ada Lovelace", "Alan Turing"],
        published_at=published_at
        or datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc),
        url=f"https://arxiv.org/abs/{external_id}",
        pdf_url=f"https://arxiv.org/pdf/{external_id}",
        categories=["cs.AI", "cs.CL"],
    )


@pytest.fixture
def database(tmp_path) -> Database:
    result = Database(tmp_path / "researchpilot.db")
    result.initialize()
    return result


def test_paper_round_trip_preserves_domain_data(database) -> None:
    repository = SQLitePaperRepository(database)
    paper = make_paper()

    inserted = repository.add(paper)
    restored = repository.get(paper.source, paper.external_id)

    assert inserted is True
    assert restored == paper
    assert repository.count() == 1


def test_duplicate_paper_identity_is_not_inserted_twice(database) -> None:
    repository = SQLitePaperRepository(database)
    paper = make_paper()

    assert repository.add(paper) is True
    assert repository.add(paper.model_copy(update={"title": "Changed title"})) is False
    assert repository.count() == 1
    assert repository.get(paper.source, paper.external_id).title == paper.title


def test_add_many_is_atomic_and_reports_new_rows(database) -> None:
    repository = SQLitePaperRepository(database)
    first = make_paper("2601.00001")
    second = make_paper("2601.00002")

    assert repository.add_many([first, second, first]) == 2
    assert repository.count() == 2


def test_papers_are_listed_newest_first(database) -> None:
    repository = SQLitePaperRepository(database)
    older = make_paper("2601.00001")
    newer = make_paper(
        "2601.00002",
        published_at=older.published_at + timedelta(days=1),
    )
    repository.add_many([older, newer])

    assert [paper.external_id for paper in repository.list_all()] == [
        "2601.00002",
        "2601.00001",
    ]


def test_run_history_can_be_started_and_finished(database) -> None:
    repository = SQLiteRunRepository(database)
    started_at = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    finished_at = started_at + timedelta(seconds=5)

    running = repository.start("discover arxiv", started_at)
    finished = repository.finish(
        running.id,
        RunStatus.SUCCEEDED,
        finished_at=finished_at,
    )

    assert running.status is RunStatus.RUNNING
    assert running.finished_at is None
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.finished_at == finished_at
    assert repository.get(running.id) == finished
    assert database.status().run_count == 1


def test_run_can_only_be_finished_once(database) -> None:
    repository = SQLiteRunRepository(database)
    running = repository.start("config check")
    repository.finish(running.id, RunStatus.FAILED, error="test failure")

    with pytest.raises(PersistenceError, match="already finished"):
        repository.finish(running.id, RunStatus.SUCCEEDED)


def test_analysis_attempt_history_preserves_failure_and_success(database) -> None:
    paper_repository = SQLitePaperRepository(database)
    analysis_repository = SQLiteAnalysisRepository(database)
    paper = make_paper()
    paper_repository.add(paper)
    started_at = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

    first = analysis_repository.begin_attempt(
        paper,
        "ollama",
        "llama3.2",
        started_at=started_at,
    )
    failed = analysis_repository.fail(
        first.id,
        "invalid structured output",
        raw_output="not json",
        completed_at=started_at + timedelta(seconds=1),
    )
    second = analysis_repository.begin_attempt(
        paper,
        "ollama",
        "llama3.2",
        started_at=started_at + timedelta(seconds=2),
    )
    result = AbstractAnalysis(
        summary="A useful paper.",
        key_contributions=["A useful contribution."],
        relevance_to_profile="Directly relevant.",
        limitations=["Only an abstract was analyzed."],
    )
    succeeded = analysis_repository.succeed(
        second.id,
        result,
        result.model_dump_json(),
        completed_at=started_at + timedelta(seconds=3),
    )

    attempts = analysis_repository.list_attempts(paper.source, paper.external_id)
    assert first.status is AnalysisStatus.RUNNING
    assert failed.status is AnalysisStatus.FAILED
    assert failed.raw_output == "not json"
    assert failed.attempt_number == 1
    assert succeeded.status is AnalysisStatus.SUCCEEDED
    assert succeeded.result == result
    assert succeeded.attempt_number == 2
    assert attempts == [failed, succeeded]
    assert analysis_repository.get_success(
        paper.source,
        paper.external_id,
        "ollama",
        "llama3.2",
    ) == succeeded
    assert database.status().analysis_attempt_count == 2


def test_successful_analysis_prevents_another_matching_attempt(database) -> None:
    paper_repository = SQLitePaperRepository(database)
    analysis_repository = SQLiteAnalysisRepository(database)
    paper = make_paper()
    paper_repository.add(paper)
    attempt = analysis_repository.begin_attempt(paper, "ollama", "llama3.2")
    result = AbstractAnalysis(
        summary="Summary",
        key_contributions=["Contribution"],
        relevance_to_profile="Relevant",
    )
    analysis_repository.succeed(attempt.id, result, result.model_dump_json())

    with pytest.raises(PersistenceError, match="already exists"):
        analysis_repository.begin_attempt(paper, "ollama", "llama3.2")
