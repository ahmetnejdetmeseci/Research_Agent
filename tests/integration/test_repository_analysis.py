from datetime import datetime, timezone

from researchpilot.application import (
    AnalyzeRepositories,
    RankingPolicy,
    RepositoryContentPolicy,
)
from researchpilot.domain import (
    AnalysisContentKind,
    AnalysisStatus,
    ContentReference,
    Interest,
    InterestProfile,
    RepositorySource,
    RetrievedContent,
    SoftwareRepository,
)
from researchpilot.domain.ports import ContentRetrievalError, LLMProviderError
from researchpilot.persistence import (
    Database,
    SQLiteRepositoryAnalysisStore,
    SQLiteRepositoryStore,
)

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
VALID_OUTPUT = """{
  "summary": "A concise summary.",
  "key_capabilities": ["Agent planning."],
  "relevance_to_profile": "Directly relevant to planning.",
  "notable_technologies": ["Python"],
  "limitations": ["Only the README was analyzed."]
}"""


class FakeProvider:
    provider_name = "ollama"
    model_name = "llama3.2"

    def __init__(self, outputs) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    def generate(self, **arguments) -> str:
        self.calls.append(arguments)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


def repository(
    external_id: str = "123",
    *,
    readme: str | None = "# Planning\nAgent planning tools.",
) -> SoftwareRepository:
    return SoftwareRepository(
        source=RepositorySource.GITHUB,
        external_id=external_id,
        full_name=f"example/repository-{external_id}",
        owner="example",
        name=f"repository-{external_id}",
        description="Planning tools.",
        readme=readme,
        url=f"https://github.com/example/repository-{external_id}",
        default_branch="main",
        primary_language="Python",
        created_at="2026-01-01T00:00:00Z",
        updated_at=NOW,
        pushed_at=NOW,
    )


def profile() -> InterestProfile:
    return InterestProfile(
        name="Planning research",
        interests=[Interest(name="Planning", keywords=["planning"])],
    )


def setup(tmp_path, repositories):
    database = Database(tmp_path / "researchpilot.db")
    database.initialize()
    store = SQLiteRepositoryStore(database)
    store.add_many(repositories)
    return store, SQLiteRepositoryAnalysisStore(database)


def analyzer(store, analyses, provider) -> AnalyzeRepositories:
    return AnalyzeRepositories(
        store,
        analyses,
        provider,
        clock=lambda: NOW,
    )


def test_successful_analysis_is_persisted_and_skipped(tmp_path) -> None:
    item = repository()
    store, analyses = setup(tmp_path, [item])
    provider = FakeProvider([VALID_OUTPUT])
    service = analyzer(store, analyses, provider)

    first = service.execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=10,
        now=NOW,
    )
    second = service.execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=10,
        now=NOW,
    )

    assert (first.selected, first.attempted, first.succeeded, first.failed) == (
        1,
        1,
        1,
        0,
    )
    assert second.already_complete == 1
    assert len(provider.calls) == 1
    assert item.full_name in provider.calls[0]["prompt"]
    stored = analyses.get_success(
        item.source,
        item.external_id,
        "ollama",
        "llama3.2",
    )
    assert stored.status is AnalysisStatus.SUCCEEDED
    assert stored.result.key_capabilities == ["Agent planning."]


def test_malformed_output_is_preserved_and_retried(tmp_path) -> None:
    item = repository()
    store, analyses = setup(tmp_path, [item])
    provider = FakeProvider(["not json", VALID_OUTPUT])
    service = analyzer(store, analyses, provider)

    first = service.execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=1,
        now=NOW,
    )
    second = service.execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=1,
        now=NOW,
    )

    attempts = analyses.list_attempts(item.source, item.external_id)
    assert first.failed == 1
    assert second.succeeded == 1
    assert [attempt.status for attempt in attempts] == [
        AnalysisStatus.FAILED,
        AnalysisStatus.SUCCEEDED,
    ]
    assert attempts[0].raw_output == "not json"


def test_missing_readme_is_skipped_without_an_attempt(tmp_path) -> None:
    item = repository(readme=None)
    store, analyses = setup(tmp_path, [item])

    result = analyzer(store, analyses, FakeProvider([])).execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=1,
        now=NOW,
    )

    assert result.selected == 1
    assert result.missing_readme == 1
    assert result.attempted == 0
    assert analyses.list_attempts(item.source, item.external_id) == []


def test_provider_outage_stops_after_one_attempt(tmp_path) -> None:
    items = [repository("1"), repository("2")]
    store, analyses = setup(tmp_path, items)
    provider = FakeProvider([LLMProviderError("Ollama unavailable")])

    result = analyzer(store, analyses, provider).execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=10,
        now=NOW,
    )

    assert result.selected == 2
    assert result.attempted == result.failed == 1
    assert len(provider.calls) == 1


class FakeRepositoryContentProvider:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[dict] = []

    def retrieve(self, repository, **limits) -> RetrievedContent:
        self.calls.append({"repository": repository, **limits})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def source_policy() -> RepositoryContentPolicy:
    return RepositoryContentPolicy(
        enabled=True,
        include_patterns=("*.py",),
        exclude_patterns=("tests/**",),
        max_files=3,
        max_file_bytes=10_000,
        max_total_characters=30_000,
    )


def source_content() -> RetrievedContent:
    return RetrievedContent(
        text="FILE: src/planner.py\ndef plan(): pass",
        references=[
            ContentReference(
                label="src/planner.py",
                locator="https://github.com/example/project/blob/main/src/planner.py",
                characters=16,
            )
        ],
    )


def test_source_analysis_is_distinct_from_existing_readme_analysis(tmp_path) -> None:
    item = repository()
    store, analyses = setup(tmp_path, [item])
    analyzer(store, analyses, FakeProvider([VALID_OUTPUT])).execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=1,
        now=NOW,
    )
    content_provider = FakeRepositoryContentProvider(source_content())
    llm = FakeProvider([VALID_OUTPUT])

    result = AnalyzeRepositories(
        store,
        analyses,
        llm,
        content_provider=content_provider,
        clock=lambda: NOW,
    ).execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=1,
        now=NOW,
        content_policy=source_policy(),
    )

    attempts = analyses.list_attempts(item.source, item.external_id)
    assert result.source_content_used == 1
    assert len(attempts) == 2
    assert attempts[-1].content_trace.kind is (
        AnalysisContentKind.README_AND_SOURCE_FILES
    )
    assert "SELECTED SOURCE FILES" in llm.calls[0]["prompt"]


def test_source_failure_falls_back_to_traceable_readme(tmp_path) -> None:
    item = repository()
    store, analyses = setup(tmp_path, [item])
    content_provider = FakeRepositoryContentProvider(
        ContentRetrievalError("no matching source files")
    )

    result = AnalyzeRepositories(
        store,
        analyses,
        FakeProvider([VALID_OUTPUT]),
        content_provider=content_provider,
        clock=lambda: NOW,
    ).execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=1,
        now=NOW,
        content_policy=source_policy(),
    )

    attempt = analyses.list_attempts(item.source, item.external_id)[0]
    assert result.succeeded == 1
    assert result.fallbacks[0].reason == "no matching source files"
    assert attempt.content_trace.kind is AnalysisContentKind.README
    assert "fallback to README" in attempt.content_trace.warnings[0]


def test_source_files_can_analyze_repository_without_readme(tmp_path) -> None:
    item = repository(readme=None)
    store, analyses = setup(tmp_path, [item])

    result = AnalyzeRepositories(
        store,
        analyses,
        FakeProvider([VALID_OUTPUT]),
        content_provider=FakeRepositoryContentProvider(source_content()),
        clock=lambda: NOW,
    ).execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=1,
        now=NOW,
        content_policy=source_policy(),
    )

    attempt = analyses.list_attempts(item.source, item.external_id)[0]
    assert result.succeeded == 1
    assert result.missing_readme == 0
    assert attempt.content_trace.kind is AnalysisContentKind.SOURCE_FILES


def test_no_readme_and_source_failure_is_partial_not_failed(tmp_path) -> None:
    item = repository(readme=None)
    store, analyses = setup(tmp_path, [item])

    result = AnalyzeRepositories(
        store,
        analyses,
        FakeProvider([]),
        content_provider=FakeRepositoryContentProvider(
            ContentRetrievalError("source files unavailable")
        ),
        clock=lambda: NOW,
    ).execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_repositories=1,
        now=NOW,
        content_policy=source_policy(),
    )

    assert result.attempted == result.failed == 0
    assert result.content_unavailable == 1
    assert result.missing_readme == 1
    assert result.fallbacks[0].reason == "source files unavailable"
