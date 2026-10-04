from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from researchpilot.domain import Interest, InterestProfile, Paper, PaperSource


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
