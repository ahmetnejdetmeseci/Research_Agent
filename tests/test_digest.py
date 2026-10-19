from datetime import datetime, timedelta, timezone

import pytest

from researchpilot.application import RankingPolicy
from researchpilot.digests import (
    BuildDigest,
    DigestBuildError,
    LocalMarkdownDigestWriter,
)
from researchpilot.domain import (
    AbstractAnalysis,
    AnalysisContentKind,
    AnalysisContentTrace,
    AnalysisStatus,
    ContentReference,
    Interest,
    InterestProfile,
    Paper,
    PaperAnalysisRecord,
    PaperSource,
    RepositoryAnalysis,
    RepositoryAnalysisRecord,
    RepositorySource,
    SoftwareRepository,
)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def make_paper(external_id: str = "2610.00001") -> Paper:
    return Paper(
        source=PaperSource.ARXIV,
        external_id=external_id,
        title="Agent planning with local models",
        abstract="Planning for an agent with a local model.",
        authors=["Ada Lovelace"],
        published_at=NOW - timedelta(days=2),
        url=f"https://arxiv.org/abs/{external_id}",
        pdf_url=f"https://arxiv.org/pdf/{external_id}",
    )


def make_repository(external_id: str = "42") -> SoftwareRepository:
    return SoftwareRepository(
        source=RepositorySource.GITHUB,
        external_id=external_id,
        full_name="example/agent-planner",
        owner="example",
        name="agent-planner",
        description="Planning tools for local model agents",
        readme="Agent planning with a local model.",
        url="https://github.com/example/agent-planner",
        default_branch="main",
        primary_language="Python",
        topics=["agents"],
        stars=10,
        forks=2,
        created_at=NOW - timedelta(days=100),
        updated_at=NOW - timedelta(days=1),
        pushed_at=NOW - timedelta(days=1),
    )


def make_profile() -> InterestProfile:
    return InterestProfile(
        name="Agent Research",
        interests=[
            Interest(
                name="Agents",
                keywords=["agent", "planning", "local model"],
                weight=1,
            )
        ],
    )


def paper_analysis(kind: AnalysisContentKind) -> PaperAnalysisRecord:
    summary = (
        "Full paper summary."
        if kind is AnalysisContentKind.FULL_PAPER
        else "Abstract summary."
    )
    return PaperAnalysisRecord(
        id=1 if kind is AnalysisContentKind.FULL_PAPER else 2,
        paper_source=PaperSource.ARXIV,
        paper_external_id="2610.00001",
        provider="ollama",
        model="llama3.2",
        attempt_number=1,
        status=AnalysisStatus.SUCCEEDED,
        result=AbstractAnalysis(
            summary=summary,
            key_contributions=["A deterministic planning method."],
            relevance_to_profile="Directly relevant to agent research.",
            limitations=["Evaluated on one benchmark."],
        ),
        raw_output="{}",
        content_trace=AnalysisContentTrace(
            kind=kind,
            references=[
                ContentReference(
                    label="PDF" if kind is AnalysisContentKind.FULL_PAPER else "Abstract",
                    locator="https://arxiv.org/pdf/2610.00001",
                    characters=12_000,
                    pages=8 if kind is AnalysisContentKind.FULL_PAPER else None,
                )
            ],
        ),
        started_at=NOW,
        completed_at=NOW + timedelta(minutes=1),
    )


def repository_analysis(kind: AnalysisContentKind) -> RepositoryAnalysisRecord:
    return RepositoryAnalysisRecord(
        id=3,
        repository_source=RepositorySource.GITHUB,
        repository_external_id="42",
        provider="ollama",
        model="llama3.2",
        attempt_number=1,
        status=AnalysisStatus.SUCCEEDED,
        result=RepositoryAnalysis(
            summary="A practical planning toolkit.",
            key_capabilities=["Runs bounded agent plans."],
            relevance_to_profile="Useful for local agent experiments.",
            notable_technologies=["Python"],
            limitations=[],
        ),
        raw_output="{}",
        content_trace=AnalysisContentTrace(
            kind=kind,
            references=[
                ContentReference(
                    label="README",
                    locator="https://github.com/example/agent-planner#readme",
                    characters=500,
                ),
                ContentReference(
                    label="planner.py",
                    locator="https://github.com/example/agent-planner/blob/main/planner.py",
                    characters=1_000,
                ),
            ],
        ),
        started_at=NOW,
        completed_at=NOW + timedelta(minutes=2),
    )


class ItemStore:
    def __init__(self, values):
        self.values = values

    def list_all(self):
        return list(self.values)


class AnalysisStore:
    def __init__(self, values):
        self.values = values

    def get_success(self, source, external_id, provider, model, content_kind):
        return self.values.get((external_id, content_kind))


class MemoryWriter:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    def write(self, filename: str, content: str) -> str:
        self.files[filename] = content
        return filename


def test_digest_is_deterministic_prefers_enriched_analysis_and_has_provenance() -> None:
    writer = MemoryWriter()
    service = BuildDigest(
        ItemStore([make_paper(), make_paper()]),
        AnalysisStore(
            {
                ("2610.00001", AnalysisContentKind.ABSTRACT): paper_analysis(
                    AnalysisContentKind.ABSTRACT
                ),
                ("2610.00001", AnalysisContentKind.FULL_PAPER): paper_analysis(
                    AnalysisContentKind.FULL_PAPER
                ),
            }
        ),
        ItemStore([make_repository()]),
        AnalysisStore(
            {
                (
                    "42",
                    AnalysisContentKind.README_AND_SOURCE_FILES,
                ): repository_analysis(
                    AnalysisContentKind.README_AND_SOURCE_FILES
                )
            }
        ),
        writer,
    )

    first = service.execute(
        make_profile(),
        RankingPolicy(),
        provider="ollama",
        model="llama3.2",
        max_papers=10,
        max_repositories=10,
    )
    first_markdown = writer.files[first.path]
    second = service.execute(
        make_profile(),
        RankingPolicy(),
        provider="ollama",
        model="llama3.2",
        max_papers=10,
        max_repositories=10,
    )

    assert first.digest_id == second.digest_id
    assert writer.files[first.path] == first_markdown
    assert len(writer.files) == 1
    assert first.paper_count == first.repository_count == 1
    assert first.as_of == NOW - timedelta(days=1)
    assert first_markdown.count("Agent planning with local models") == 1
    assert "Full paper summary." in first_markdown
    assert "Abstract summary." not in first_markdown
    assert "[PDF](<https://arxiv.org/pdf/2610.00001>)" in first_markdown
    assert "`full_paper`" in first_markdown
    assert "`readme_and_source_files`" in first_markdown
    assert "https://github.com/example/agent-planner" in first_markdown


def test_digest_reports_selected_items_without_matching_analysis() -> None:
    service = BuildDigest(
        ItemStore([make_paper(), make_paper("2610.00002")]),
        AnalysisStore(
            {
                ("2610.00001", AnalysisContentKind.ABSTRACT): paper_analysis(
                    AnalysisContentKind.ABSTRACT
                )
            }
        ),
        ItemStore([]),
        AnalysisStore({}),
        MemoryWriter(),
    )

    result = service.execute(
        make_profile(),
        RankingPolicy(),
        provider="ollama",
        model="llama3.2",
        max_papers=10,
        max_repositories=10,
    )

    assert result.paper_count == 1
    assert result.missing_analysis == 1


def test_digest_requires_at_least_one_selected_successful_analysis() -> None:
    service = BuildDigest(
        ItemStore([make_paper()]),
        AnalysisStore({}),
        ItemStore([]),
        AnalysisStore({}),
        MemoryWriter(),
    )

    with pytest.raises(DigestBuildError, match="run the analysis commands first"):
        service.execute(
            make_profile(),
            RankingPolicy(),
            provider="ollama",
            model="llama3.2",
            max_papers=10,
            max_repositories=10,
        )


def test_local_writer_replaces_instead_of_appending(tmp_path) -> None:
    writer = LocalMarkdownDigestWriter(tmp_path / "digests")

    first_path = writer.write("researchpilot-test.md", "# Digest\n\nOne entry\n")
    second_path = writer.write("researchpilot-test.md", "# Digest\n\nOne entry\n")

    assert first_path == second_path
    assert (tmp_path / "digests" / "researchpilot-test.md").read_text(
        encoding="utf-8"
    ) == "# Digest\n\nOne entry\n"


def test_local_writer_rejects_path_traversal(tmp_path) -> None:
    writer = LocalMarkdownDigestWriter(tmp_path)

    with pytest.raises(ValueError, match="plain Markdown filename"):
        writer.write("../outside.md", "content")
