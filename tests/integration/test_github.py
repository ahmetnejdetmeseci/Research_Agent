from datetime import datetime, timezone

import httpx
import pytest

from researchpilot.application import (
    DiscoverRepositories,
    RepositoryDiscoveryRequest,
)
from researchpilot.domain import RepositorySource
from researchpilot.integrations.github import (
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubSource,
)
from researchpilot.persistence import Database, SQLiteRepositoryStore

PUSHED_AFTER = datetime(2026, 9, 1, tzinfo=timezone.utc)


def github_item(identifier: int, full_name: str = "openai/example") -> dict:
    owner, name = full_name.split("/", 1)
    return {
        "id": identifier,
        "full_name": full_name,
        "owner": {"login": owner},
        "name": name,
        "description": "Agent planning tools",
        "html_url": f"https://github.com/{full_name}",
        "default_branch": "main",
        "language": "Python",
        "topics": ["agents", "planning"],
        "stargazers_count": 42,
        "forks_count": 3,
        "archived": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-10-01T00:00:00Z",
        "pushed_at": "2026-10-01T00:00:00Z",
    }


def test_search_sends_auth_query_and_retrieves_readme() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search/repositories":
            return httpx.Response(
                200,
                json={"total_count": 1, "items": [github_item(123)]},
                request=request,
            )
        assert request.url.path == "/repos/openai/example/readme"
        return httpx.Response(200, text="# Example\nAgent planning.", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        repositories = GitHubSource(client, token="secret").search(
            queries=["agent planning"],
            pushed_after=PUSHED_AFTER,
            max_results=10,
            max_readme_characters=1_000,
        )

    assert len(repositories) == 1
    repository = repositories[0]
    assert repository.source is RepositorySource.GITHUB
    assert repository.external_id == "123"
    assert repository.full_name == "openai/example"
    assert repository.readme == "# Example\nAgent planning."
    search_request, readme_request = requests
    assert search_request.headers["authorization"] == "Bearer secret"
    assert search_request.url.params["q"] == (
        "agent planning pushed:>=2026-09-01 archived:false"
    )
    assert search_request.url.params["sort"] == "updated"
    assert readme_request.headers["accept"] == "application/vnd.github.raw+json"


def test_search_paginates_deduplicates_and_allows_missing_readme() -> None:
    search_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            page = request.url.params["page"]
            search_pages.append(page)
            item = github_item(
                1 if page == "1" else 2,
                "example/one" if page == "1" else "example/two",
            )
            return httpx.Response(
                200,
                json={"total_count": 2, "items": [item]},
                request=request,
            )
        return httpx.Response(404, json={"message": "Not Found"}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        repositories = GitHubSource(client, page_size=1).search(
            queries=["agents", "planning"],
            pushed_after=PUSHED_AFTER,
            max_results=2,
            max_readme_characters=1_000,
        )

    assert search_pages == ["1", "2"]
    assert [repository.external_id for repository in repositories] == ["1", "2"]
    assert all(repository.readme is None for repository in repositories)


def test_rate_limit_is_reported_with_reset_time() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "1790812800",
            },
            json={"message": "API rate limit exceeded"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GitHubRateLimitError, match="rate limit reached.*resets at"):
            GitHubSource(client).search(
                queries=["agents"],
                pushed_after=PUSHED_AFTER,
                max_results=1,
                max_readme_characters=1_000,
            )


def test_malformed_search_response_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GitHubResponseError, match="total_count"):
            GitHubSource(client).search(
                queries=["agents"],
                pushed_after=PUSHED_AFTER,
                max_results=1,
                max_readme_characters=1_000,
            )


def test_repeated_discovery_run_skips_existing_repository(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return httpx.Response(
                200,
                json={"total_count": 1, "items": [github_item(123)]},
                request=request,
            )
        return httpx.Response(200, text="# Example", request=request)

    database = Database(tmp_path / "researchpilot.db")
    database.initialize()
    repository = SQLiteRepositoryStore(database)
    request = RepositoryDiscoveryRequest(
        queries=("agents",),
        pushed_after=PUSHED_AFTER,
        max_results=5,
        max_readme_characters=1_000,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = DiscoverRepositories(GitHubSource(client), repository)
        first = service.execute(request)
        second = service.execute(request)

    assert (first.fetched, first.inserted, first.duplicates) == (1, 1, 0)
    assert (second.fetched, second.inserted, second.duplicates) == (1, 0, 1)
    assert repository.count() == 1
