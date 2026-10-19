"""GitHub REST API adapter for repository discovery and README retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from researchpilot import __version__
from researchpilot.domain import RepositorySource, SoftwareRepository

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_PAGE_SIZE = 100
SEARCH_RESULT_LIMIT = 1_000
USER_AGENT = f"ResearchPilot/{__version__} (personal research assistant)"


class GitHubError(Exception):
    """A GitHub request or response problem safe to show to a user."""


class GitHubRateLimitError(GitHubError):
    """GitHub rejected a request because a rate limit was reached."""


class GitHubResponseError(GitHubError):
    """A GitHub response that cannot be converted to domain data."""


def _normalized_optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GitHubResponseError(f"GitHub repository has invalid {field}")
    normalized = " ".join(value.split())
    return normalized or None


def _required_text(item: dict[str, Any], field: str) -> str:
    value = _normalized_optional_text(item.get(field), field)
    if value is None:
        raise GitHubResponseError(f"GitHub repository is missing required {field}")
    return value


def _required_integer(item: dict[str, Any], field: str) -> int:
    value = item.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GitHubResponseError(f"GitHub repository has invalid {field}")
    return value


def _repository_identity(item: dict[str, Any]) -> tuple[str, str]:
    return str(_required_integer(item, "id")), _required_text(item, "full_name")


def repository_from_github_item(
    item: dict[str, Any],
    *,
    readme: str | None,
) -> SoftwareRepository:
    """Convert one adapter-local GitHub item into normalized domain data."""

    external_id, full_name = _repository_identity(item)
    owner_data = item.get("owner")
    if not isinstance(owner_data, dict):
        raise GitHubResponseError("GitHub repository is missing required owner")
    topics = item.get("topics", [])
    if not isinstance(topics, list) or any(
        not isinstance(topic, str) or not topic.strip() for topic in topics
    ):
        raise GitHubResponseError("GitHub repository has invalid topics")
    archived = item.get("archived", False)
    if not isinstance(archived, bool):
        raise GitHubResponseError("GitHub repository has invalid archived state")

    try:
        return SoftwareRepository(
            source=RepositorySource.GITHUB,
            external_id=external_id,
            full_name=full_name,
            owner=_required_text(owner_data, "login"),
            name=_required_text(item, "name"),
            description=_normalized_optional_text(
                item.get("description"),
                "description",
            ),
            readme=readme,
            url=_required_text(item, "html_url"),
            default_branch=_required_text(item, "default_branch"),
            primary_language=_normalized_optional_text(
                item.get("language"),
                "language",
            ),
            topics=list(dict.fromkeys(topic.strip() for topic in topics)),
            stars=_required_integer(item, "stargazers_count"),
            forks=_required_integer(item, "forks_count"),
            archived=archived,
            created_at=_required_text(item, "created_at"),
            updated_at=_required_text(item, "updated_at"),
            pushed_at=_normalized_optional_text(item.get("pushed_at"), "pushed_at"),
        )
    except ValidationError as exc:
        raise GitHubResponseError(
            f"GitHub repository contains invalid metadata: {exc}"
        ) from exc


class GitHubSource:
    """Discover repositories through GitHub's paginated REST API."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        token: str | None = None,
        base_url: str = GITHUB_API_URL,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._page_size = page_size
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": USER_AGENT,
        }
        if token is not None and token.strip():
            self._headers["Authorization"] = f"Bearer {token.strip()}"

    def search(
        self,
        *,
        queries: Sequence[str],
        pushed_after: datetime,
        max_results: int,
        max_readme_characters: int,
    ) -> list[SoftwareRepository]:
        """Search configured queries and retrieve available README content."""

        if not queries or any(not query.strip() for query in queries):
            raise ValueError("at least one non-empty GitHub query is required")
        if pushed_after.tzinfo is None:
            raise ValueError("GitHub pushed_after must include a timezone")
        if max_results < 1 or max_results > SEARCH_RESULT_LIMIT:
            raise ValueError("max_results must be between 1 and 1000")
        if max_readme_characters < 1:
            raise ValueError("max_readme_characters must be positive")

        repositories: list[SoftwareRepository] = []
        seen_ids: set[str] = set()
        pushed_date = pushed_after.astimezone(timezone.utc).date().isoformat()

        for configured_query in queries:
            page = 1
            per_page = min(self._page_size, max_results)
            while len(repositories) < max_results:
                payload = self._get_json(
                    "/search/repositories",
                    params={
                        "q": (
                            f"{configured_query.strip()} "
                            f"pushed:>={pushed_date} archived:false"
                        ),
                        "sort": "updated",
                        "order": "desc",
                        "per_page": per_page,
                        "page": page,
                    },
                )
                if not isinstance(payload, dict):
                    raise GitHubResponseError(
                        "GitHub repository search response must be a JSON object"
                    )
                total_count = payload.get("total_count")
                items = payload.get("items")
                if (
                    not isinstance(total_count, int)
                    or isinstance(total_count, bool)
                    or total_count < 0
                ):
                    raise GitHubResponseError(
                        "GitHub repository search has invalid total_count"
                    )
                if not isinstance(items, list) or any(
                    not isinstance(item, dict) for item in items
                ):
                    raise GitHubResponseError(
                        "GitHub repository search has invalid items"
                    )

                for item in items:
                    external_id, full_name = _repository_identity(item)
                    if external_id in seen_ids:
                        continue
                    readme = self._readme(full_name, max_readme_characters)
                    repositories.append(
                        repository_from_github_item(item, readme=readme)
                    )
                    seen_ids.add(external_id)
                    if len(repositories) >= max_results:
                        break

                result_cap = min(total_count, SEARCH_RESULT_LIMIT)
                if (
                    not items
                    or len(items) < per_page
                    or page * per_page >= result_cap
                    or len(repositories) >= max_results
                ):
                    break
                page += 1

            if len(repositories) >= max_results:
                break

        return repositories

    def _readme(self, full_name: str, max_characters: int) -> str | None:
        try:
            owner, name = full_name.split("/", 1)
        except ValueError as exc:
            raise GitHubResponseError(
                f"GitHub repository has invalid full_name: {full_name}"
            ) from exc
        path = f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}/readme"
        response = self._request(
            path,
            headers={"Accept": "application/vnd.github.raw+json"},
            allow_not_found=True,
        )
        if response is None:
            return None
        content = response.text.strip()
        return content[:max_characters] or None

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, object],
    ) -> Any:
        response = self._request(path, params=params)
        assert response is not None
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubResponseError("GitHub returned malformed JSON") from exc

    def _request(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        allow_not_found: bool = False,
    ) -> httpx.Response | None:
        request_headers = dict(self._headers)
        if headers:
            request_headers.update(headers)
        try:
            response = self._client.get(
                f"{self._base_url}{path}",
                params=params,
                headers=request_headers,
            )
            if allow_not_found and response.status_code == 404:
                return None
            if self._is_rate_limited(response):
                raise GitHubRateLimitError(self._rate_limit_message(response))
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise GitHubError("GitHub request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise GitHubError(
                f"GitHub returned HTTP {exc.response.status_code}: "
                f"{self._response_message(exc.response)}"
            ) from exc
        except httpx.RequestError as exc:
            raise GitHubError(f"GitHub request failed: {exc}") from exc

    @classmethod
    def _is_rate_limited(cls, response: httpx.Response) -> bool:
        if response.status_code == 429:
            return True
        if response.status_code != 403:
            return False
        if response.headers.get("X-RateLimit-Remaining") == "0":
            return True
        return "rate limit" in cls._response_message(response).casefold()

    @classmethod
    def _rate_limit_message(cls, response: httpx.Response) -> str:
        reset = response.headers.get("X-RateLimit-Reset")
        reset_text = ""
        if reset is not None:
            try:
                reset_at = datetime.fromtimestamp(int(reset), tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                reset_text = ""
            else:
                reset_text = f"; resets at {reset_at.isoformat()}"
        return f"GitHub rate limit reached{reset_text}: {cls._response_message(response)}"

    @staticmethod
    def _response_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.reason_phrase or "request failed"
        if isinstance(payload, dict) and isinstance(payload.get("message"), str):
            return payload["message"]
        return response.reason_phrase or "request failed"
