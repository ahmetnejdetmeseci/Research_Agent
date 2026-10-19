from datetime import datetime, timezone

import pytest

from researchpilot.application import (
    DiscoverPapers,
    DiscoverRepositories,
    DiscoveryRequest,
    RepositoryDiscoveryRequest,
)
from researchpilot.domain import (
    Paper,
    PaperSource,
    RepositorySource,
    SoftwareRepository,
)


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


def software_repository() -> SoftwareRepository:
    return SoftwareRepository(
        source=RepositorySource.GITHUB,
        external_id="123",
        full_name="example/repository",
        owner="example",
        name="repository",
        url="https://github.com/example/repository",
        default_branch="main",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-10-01T00:00:00Z",
    )


def test_repository_discovery_orchestrates_source_and_store() -> None:
    expected = software_repository()
    request = RepositoryDiscoveryRequest(
        queries=("agent planning",),
        pushed_after=datetime(2026, 9, 1, tzinfo=timezone.utc),
        max_results=10,
        max_readme_characters=30_000,
    )

    class Source:
        def search(self, **parameters) -> list[SoftwareRepository]:
            assert parameters == {
                "queries": ("agent planning",),
                "pushed_after": datetime(2026, 9, 1, tzinfo=timezone.utc),
                "max_results": 10,
                "max_readme_characters": 30_000,
            }
            return [expected]

    class Store:
        def add_many(self, repositories) -> int:
            assert list(repositories) == [expected]
            return 1

    result = DiscoverRepositories(Source(), Store()).execute(request)

    assert (result.fetched, result.inserted, result.duplicates) == (1, 1, 0)
