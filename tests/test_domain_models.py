from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from researchpilot.domain import (
    AnalysisContentKind,
    AnalysisContentTrace,
    ContentReference,
    Interest,
    InterestProfile,
    Paper,
    PaperSource,
    RepositorySource,
    SoftwareRepository,
)


def test_interest_profile_normalizes_surrounding_whitespace() -> None:
    profile = InterestProfile(
        name="  Machine learning  ",
        interests=[
            Interest(
                name="  Agents  ",
                keywords=["  tool use  ", "planning"],
                weight=1.5,
            )
        ],
        exclusions=["  medical imaging  "],
    )

    assert profile.name == "Machine learning"
    assert profile.interests[0].keywords[0] == "tool use"
    assert profile.exclusions == ["medical imaging"]


def test_interest_profile_rejects_duplicate_topics() -> None:
    with pytest.raises(ValidationError, match="interest names must be unique"):
        InterestProfile(
            name="Test",
            interests=[
                Interest(name="Agents", keywords=["planning"]),
                Interest(name="agents", keywords=["tools"]),
            ],
        )


def test_paper_contains_only_normalized_domain_data() -> None:
    paper = Paper(
        source=PaperSource.ARXIV,
        external_id="2401.12345",
        title="A useful paper",
        abstract="A concise abstract.",
        authors=["Ada Lovelace"],
        published_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        url="https://arxiv.org/abs/2401.12345",
        pdf_url="https://arxiv.org/pdf/2401.12345",
        categories=["cs.AI"],
    )

    assert paper.external_id == "2401.12345"
    assert paper.source is PaperSource.ARXIV


def test_paper_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timestamp must include a timezone"):
        Paper(
            source="arxiv",
            external_id="2401.12345",
            title="A useful paper",
            abstract="A concise abstract.",
            authors=["Ada Lovelace"],
            published_at=datetime(2026, 1, 2),
            url="https://arxiv.org/abs/2401.12345",
        )


def test_software_repository_contains_only_normalized_domain_data() -> None:
    repository = SoftwareRepository(
        source=RepositorySource.GITHUB,
        external_id="123",
        full_name="openai/example",
        owner="openai",
        name="example",
        description="An example repository.",
        readme="# Example",
        url="https://github.com/openai/example",
        default_branch="main",
        primary_language="Python",
        topics=["agents"],
        stars=42,
        forks=3,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        pushed_at="2026-01-02T00:00:00Z",
    )

    assert repository.source is RepositorySource.GITHUB
    assert repository.external_id == "123"
    assert repository.readme == "# Example"


def test_software_repository_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timestamp must include a timezone"):
        SoftwareRepository(
            source="github",
            external_id="123",
            full_name="openai/example",
            owner="openai",
            name="example",
            url="https://github.com/openai/example",
            default_branch="main",
            created_at=datetime(2026, 1, 1),
            updated_at="2026-01-02T00:00:00Z",
        )


def test_analysis_content_trace_retains_provenance_without_content() -> None:
    trace = AnalysisContentTrace(
        kind=AnalysisContentKind.FULL_PAPER,
        references=[
            ContentReference(
                label="ArXiv PDF",
                locator="https://arxiv.org/pdf/2401.12345",
                characters=50_000,
                pages=20,
                truncated=True,
            )
        ],
        truncated=True,
        warnings=["page 4 could not be extracted"],
    )

    assert trace.kind is AnalysisContentKind.FULL_PAPER
    assert trace.references[0].pages == 20
    assert "text" not in trace.model_dump()
