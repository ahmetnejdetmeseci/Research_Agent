from datetime import datetime, timedelta, timezone

import pytest

from researchpilot.domain import (
    AbstractAnalysis,
    AnalysisContentKind,
    AnalysisContentTrace,
    AnalysisStatus,
    ContentReference,
    Paper,
    PaperSource,
    PipelineStepStatus,
    RepositoryAnalysis,
    RepositorySource,
    RunStatus,
    SoftwareRepository,
)
from researchpilot.persistence import (
    Database,
    PersistenceError,
    SQLiteAnalysisRepository,
    SQLitePaperRepository,
    SQLitePipelineRepository,
    SQLiteRepositoryAnalysisStore,
    SQLiteRepositoryStore,
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


def make_repository(
    external_id: str = "123",
    *,
    pushed_at: datetime | None = None,
) -> SoftwareRepository:
    return SoftwareRepository(
        source=RepositorySource.GITHUB,
        external_id=external_id,
        full_name=f"example/repository-{external_id}",
        owner="example",
        name=f"repository-{external_id}",
        description="Agent planning tools.",
        readme="# Repository\nPlanning tools.",
        url=f"https://github.com/example/repository-{external_id}",
        default_branch="main",
        primary_language="Python",
        topics=["agents", "planning"],
        stars=42,
        forks=3,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        pushed_at=pushed_at or datetime(2026, 10, 2, tzinfo=timezone.utc),
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


def test_repository_round_trip_and_deduplication(database) -> None:
    store = SQLiteRepositoryStore(database)
    repository = make_repository()

    assert store.add(repository) is True
    assert store.add(repository.model_copy(update={"stars": 100})) is False
    assert store.get(repository.source, repository.external_id) == repository
    assert store.count() == 1
    assert database.status().repository_count == 1


def test_repositories_are_listed_by_recent_activity(database) -> None:
    store = SQLiteRepositoryStore(database)
    older = make_repository(
        "1",
        pushed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    newer = make_repository(
        "2",
        pushed_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    store.add_many([older, newer])

    assert [item.external_id for item in store.list_all()] == ["2", "1"]


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


def test_pipeline_repository_records_ordered_step_outcomes(database) -> None:
    repository = SQLitePipelineRepository(database)
    started_at = datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc)
    session = repository.begin_or_resume(
        "pipeline-key",
        "run",
        (("discover", True), ("export", False)),
        started_at=started_at,
    )

    running = repository.start_step(
        session.run.id,
        "discover",
        started_at=started_at + timedelta(seconds=1),
    )
    succeeded = repository.succeed_step(
        session.run.id,
        "discover",
        {"inserted": 2, "duplicates": 1},
        finished_at=started_at + timedelta(seconds=2),
    )
    finished = repository.finish_run(
        session.run.id,
        RunStatus.SUCCEEDED,
        finished_at=started_at + timedelta(seconds=3),
    )
    steps = repository.list_steps(session.run.id)

    assert session.resumed is False
    assert session.run.run_key == "pipeline-key"
    assert running.status is PipelineStepStatus.RUNNING
    assert running.attempt_count == 1
    assert succeeded.status is PipelineStepStatus.SUCCEEDED
    assert succeeded.result == {"inserted": 2, "duplicates": 1}
    assert steps[1].status is PipelineStepStatus.SKIPPED
    assert steps[1].result == {"reason": "disabled"}
    assert finished.status is RunStatus.SUCCEEDED
    assert database.status().run_step_count == 2


def test_pipeline_repository_resumes_running_step(database) -> None:
    repository = SQLitePipelineRepository(database)
    session = repository.begin_or_resume(
        "pipeline-key",
        "run",
        (("first", True), ("interrupted", True)),
    )
    repository.start_step(session.run.id, "first")
    repository.succeed_step(session.run.id, "first", {"done": True})
    first_attempt = repository.start_step(session.run.id, "interrupted")

    resumed = repository.begin_or_resume(
        "pipeline-key",
        "run",
        (("first", True), ("interrupted", True)),
    )
    second_attempt = repository.start_step(session.run.id, "interrupted")

    assert resumed.resumed is True
    assert resumed.run.id == session.run.id
    assert first_attempt.attempt_count == 1
    assert second_attempt.attempt_count == 2
    assert resumed.steps[0].status is PipelineStepStatus.SUCCEEDED
    assert resumed.steps[1].status is PipelineStepStatus.RUNNING


def test_pipeline_resume_rejects_changed_step_definition(database) -> None:
    repository = SQLitePipelineRepository(database)
    repository.begin_or_resume(
        "pipeline-key",
        "run",
        (("first", True),),
    )

    with pytest.raises(PersistenceError, match="different step definition"):
        repository.begin_or_resume(
            "pipeline-key",
            "run",
            (("changed", True),),
        )


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
    assert succeeded.content_trace.kind is AnalysisContentKind.ABSTRACT
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


def test_paper_successes_are_distinct_by_content_kind(database) -> None:
    papers = SQLitePaperRepository(database)
    analyses = SQLiteAnalysisRepository(database)
    paper = make_paper()
    papers.add(paper)
    result = AbstractAnalysis(
        summary="Summary",
        key_contributions=["Contribution"],
        relevance_to_profile="Relevant",
    )

    abstract_attempt = analyses.begin_attempt(paper, "ollama", "llama3.2")
    analyses.succeed(abstract_attempt.id, result, result.model_dump_json())
    full_trace = AnalysisContentTrace(
        kind=AnalysisContentKind.FULL_PAPER,
        references=[
            ContentReference(
                label="ArXiv PDF",
                locator=str(paper.pdf_url),
                characters=10_000,
                pages=8,
            )
        ],
    )
    full_attempt = analyses.begin_attempt(
        paper,
        "ollama",
        "llama3.2",
        content_trace=full_trace,
    )
    full_success = analyses.succeed(
        full_attempt.id,
        result,
        result.model_dump_json(),
    )

    assert full_success.content_trace == full_trace
    assert analyses.get_success(
        paper.source,
        paper.external_id,
        "ollama",
        "llama3.2",
        AnalysisContentKind.FULL_PAPER,
    ) == full_success


def test_repository_analysis_preserves_failure_and_success(database) -> None:
    repository_store = SQLiteRepositoryStore(database)
    analysis_store = SQLiteRepositoryAnalysisStore(database)
    repository = make_repository()
    repository_store.add(repository)
    started_at = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

    first = analysis_store.begin_attempt(
        repository,
        "ollama",
        "llama3.2",
        started_at=started_at,
    )
    failed = analysis_store.fail(
        first.id,
        "invalid structured output",
        raw_output="not json",
        completed_at=started_at + timedelta(seconds=1),
    )
    second = analysis_store.begin_attempt(
        repository,
        "ollama",
        "llama3.2",
        started_at=started_at + timedelta(seconds=2),
    )
    result = RepositoryAnalysis(
        summary="A useful repository.",
        key_capabilities=["Agent planning."],
        relevance_to_profile="Directly relevant.",
        notable_technologies=["Python"],
    )
    succeeded = analysis_store.succeed(
        second.id,
        result,
        result.model_dump_json(),
        completed_at=started_at + timedelta(seconds=3),
    )

    attempts = analysis_store.list_attempts(
        repository.source,
        repository.external_id,
    )
    assert failed.status is AnalysisStatus.FAILED
    assert succeeded.status is AnalysisStatus.SUCCEEDED
    assert succeeded.result == result
    assert succeeded.content_trace.kind is AnalysisContentKind.README
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert analysis_store.get_success(
        repository.source,
        repository.external_id,
        "ollama",
        "llama3.2",
    ) == succeeded
    assert database.status().repository_analysis_attempt_count == 2


def test_repository_successes_are_distinct_by_content_kind(database) -> None:
    repositories = SQLiteRepositoryStore(database)
    analyses = SQLiteRepositoryAnalysisStore(database)
    repository = make_repository()
    repositories.add(repository)
    result = RepositoryAnalysis(
        summary="Summary",
        key_capabilities=["Planning"],
        relevance_to_profile="Relevant",
    )

    readme_attempt = analyses.begin_attempt(
        repository,
        "ollama",
        "llama3.2",
    )
    analyses.succeed(readme_attempt.id, result, result.model_dump_json())
    source_trace = AnalysisContentTrace(
        kind=AnalysisContentKind.README_AND_SOURCE_FILES,
        references=[
            ContentReference(
                label="src/main.py",
                locator="https://github.com/example/repository-123/blob/main/src/main.py",
                characters=500,
            )
        ],
    )
    source_attempt = analyses.begin_attempt(
        repository,
        "ollama",
        "llama3.2",
        content_trace=source_trace,
    )
    source_success = analyses.succeed(
        source_attempt.id,
        result,
        result.model_dump_json(),
    )

    assert source_success.content_trace == source_trace
