from datetime import datetime, timezone

from researchpilot.application import AnalyzePapers, RankingPolicy
from researchpilot.domain import (
    AnalysisStatus,
    Interest,
    InterestProfile,
    Paper,
    PaperSource,
)
from researchpilot.domain.ports import LLMProviderError
from researchpilot.persistence import (
    Database,
    SQLiteAnalysisRepository,
    SQLitePaperRepository,
)

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
VALID_OUTPUT = """{
  "summary": "A concise summary.",
  "key_contributions": ["A useful contribution."],
  "relevance_to_profile": "Directly relevant to planning.",
  "limitations": ["Only the abstract was available."]
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


def make_paper(external_id: str = "2601.00001") -> Paper:
    return Paper(
        source=PaperSource.ARXIV,
        external_id=external_id,
        title=f"Planning paper {external_id}",
        abstract="This paper studies planning for technical systems.",
        authors=["Ada Lovelace"],
        published_at=NOW,
        url=f"https://arxiv.org/abs/{external_id}",
    )


def profile() -> InterestProfile:
    return InterestProfile(
        name="Planning research",
        interests=[Interest(name="Planning", keywords=["planning"], weight=1)],
    )


def setup_repositories(tmp_path, papers: list[Paper]):
    database = Database(tmp_path / "researchpilot.db")
    database.initialize()
    paper_repository = SQLitePaperRepository(database)
    paper_repository.add_many(papers)
    return database, paper_repository, SQLiteAnalysisRepository(database)


def service(papers, analyses, provider) -> AnalyzePapers:
    return AnalyzePapers(
        papers,
        analyses,
        provider,
        clock=lambda: NOW,
    )


def test_successful_analysis_is_persisted_and_skipped_on_next_run(tmp_path) -> None:
    paper = make_paper()
    _, papers, analyses = setup_repositories(tmp_path, [paper])
    provider = FakeProvider([VALID_OUTPUT])
    analyzer = service(papers, analyses, provider)

    first = analyzer.execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_papers=10,
        now=NOW,
    )
    second = analyzer.execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_papers=10,
        now=NOW,
    )

    assert (first.selected, first.attempted, first.succeeded, first.failed) == (
        1,
        1,
        1,
        0,
    )
    assert second.attempted == 0
    assert second.already_complete == 1
    assert len(provider.calls) == 1
    assert paper.title in provider.calls[0]["prompt"]
    assert provider.calls[0]["response_schema"]["type"] == "object"
    stored = analyses.get_success(
        paper.source,
        paper.external_id,
        provider.provider_name,
        provider.model_name,
    )
    assert stored.status is AnalysisStatus.SUCCEEDED
    assert stored.raw_output == VALID_OUTPUT
    assert stored.result.summary == "A concise summary."


def test_malformed_output_is_preserved_and_retried_safely(tmp_path) -> None:
    paper = make_paper()
    _, papers, analyses = setup_repositories(tmp_path, [paper])
    provider = FakeProvider(["not json", VALID_OUTPUT])
    analyzer = service(papers, analyses, provider)

    first = analyzer.execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_papers=1,
        now=NOW,
    )
    second = analyzer.execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_papers=1,
        now=NOW,
    )

    attempts = analyses.list_attempts(paper.source, paper.external_id)
    assert first.failed == 1
    assert second.succeeded == 1
    assert [attempt.status for attempt in attempts] == [
        AnalysisStatus.FAILED,
        AnalysisStatus.SUCCEEDED,
    ]
    assert attempts[0].raw_output == "not json"
    assert "invalid structured analysis" in attempts[0].error
    assert attempts[1].attempt_number == 2


def test_provider_outage_fails_one_attempt_and_stops_the_run(tmp_path) -> None:
    first_paper = make_paper("2601.00001")
    second_paper = make_paper("2601.00002")
    _, papers, analyses = setup_repositories(
        tmp_path,
        [first_paper, second_paper],
    )
    provider = FakeProvider([LLMProviderError("Ollama unavailable")])

    result = service(papers, analyses, provider).execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_papers=10,
        now=NOW,
    )

    assert result.selected == 2
    assert result.attempted == 1
    assert result.failed == 1
    assert len(provider.calls) == 1
    attempts = sum(
        (
            analyses.list_attempts(paper.source, paper.external_id)
            for paper in [first_paper, second_paper]
        ),
        [],
    )
    assert len(attempts) == 1
    assert attempts[0].status is AnalysisStatus.FAILED
    assert attempts[0].error == "Ollama unavailable"


def test_run_limit_bounds_the_number_of_attempts(tmp_path) -> None:
    paper_list = [make_paper("2601.00001"), make_paper("2601.00002")]
    _, papers, analyses = setup_repositories(tmp_path, paper_list)
    provider = FakeProvider([VALID_OUTPUT])

    result = service(papers, analyses, provider).execute(
        profile(),
        RankingPolicy(recency_weight=0),
        max_papers=1,
        now=NOW,
    )

    assert result.selected == 2
    assert result.attempted == 1
    assert result.succeeded == 1
    assert len(provider.calls) == 1
