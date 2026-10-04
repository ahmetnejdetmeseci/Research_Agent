from datetime import datetime, timezone

import pytest

from researchpilot.application import DiscoverPapers, DiscoveryRequest
from researchpilot.domain import Paper, PaperSource


def paper() -> Paper:
    return Paper(
        source=PaperSource.ARXIV,
        external_id="2601.00001",
        title="A useful paper",
        abstract="A useful abstract.",
        authors=["Ada Lovelace"],
        published_at="2026-01-02T12:00:00Z",
        url="https://arxiv.org/abs/2601.00001",
    )


def request() -> DiscoveryRequest:
    return DiscoveryRequest(
        categories=("cs.AI",),
        submitted_after=datetime(2026, 1, 1, tzinfo=timezone.utc),
        submitted_before=datetime(2026, 1, 8, tzinfo=timezone.utc),
        max_results=10,
    )


def test_discovery_service_orchestrates_source_and_repository() -> None:
    expected_paper = paper()

    class Source:
        def search(self, **parameters) -> list[Paper]:
            assert parameters == {
                "categories": ("cs.AI",),
                "submitted_after": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "submitted_before": datetime(2026, 1, 8, tzinfo=timezone.utc),
                "max_results": 10,
            }
            return [expected_paper]

    class Repository:
        def add_many(self, papers) -> int:
            assert list(papers) == [expected_paper]
            return 0

    result = DiscoverPapers(Source(), Repository()).execute(request())

    assert result.fetched == 1
    assert result.inserted == 0
    assert result.duplicates == 1


@pytest.mark.parametrize(
    "invalid_request",
    [
        lambda: DiscoveryRequest(
            categories=(),
            submitted_after=datetime(2026, 1, 1, tzinfo=timezone.utc),
            submitted_before=datetime(2026, 1, 8, tzinfo=timezone.utc),
            max_results=10,
        ),
        lambda: DiscoveryRequest(
            categories=("cs.AI",),
            submitted_after=datetime(2026, 1, 8, tzinfo=timezone.utc),
            submitted_before=datetime(2026, 1, 1, tzinfo=timezone.utc),
            max_results=10,
        ),
        lambda: DiscoveryRequest(
            categories=("cs.AI",),
            submitted_after=datetime(2026, 1, 1),
            submitted_before=datetime(2026, 1, 8),
            max_results=10,
        ),
        lambda: DiscoveryRequest(
            categories=("cs.AI",),
            submitted_after=datetime(2026, 1, 1, tzinfo=timezone.utc),
            submitted_before=datetime(2026, 1, 8, tzinfo=timezone.utc),
            max_results=0,
        ),
    ],
)
def test_discovery_request_rejects_invalid_boundaries(invalid_request) -> None:
    with pytest.raises(ValueError):
        invalid_request()
