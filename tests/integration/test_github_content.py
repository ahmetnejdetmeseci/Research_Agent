from datetime import datetime, timezone

import httpx
import pytest

from researchpilot.domain import RepositorySource, SoftwareRepository
from researchpilot.integrations.github_content import (
    GitHubContentError,
    GitHubContentSource,
)


def repository(*, readme: str | None = "# Example") -> SoftwareRepository:
    return SoftwareRepository(
        source=RepositorySource.GITHUB,
        external_id="123",
        full_name="example/project",
        owner="example",
        name="project",
        description="Planning tools",
        readme=readme,
        url="https://github.com/example/project",
        default_branch="main",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )


def test_selected_source_files_are_bounded_and_traced() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if "/git/trees/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "truncated": True,
                    "tree": [
                        {"path": "src/main.py", "type": "blob", "size": 30},
                        {"path": "tests/test_main.py", "type": "blob", "size": 20},
                        {"path": "src/huge.py", "type": "blob", "size": 5_000},
                        {"path": "README.md", "type": "blob", "size": 20},
                    ],
                },
                request=request,
            )
        assert request.url.path.endswith("/contents/src/main.py")
        assert request.url.params["ref"] == "main"
        return httpx.Response(
            200,
            content=b"def plan():\n    return 'planning'\n",
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GitHubContentSource(client).retrieve(
            repository(),
            include_patterns=("*.py", "**/*.py"),
            exclude_patterns=("tests/**",),
            max_files=5,
            max_file_bytes=1_000,
            max_total_characters=10_000,
        )

    assert "FILE: src/main.py" in result.text
    assert "def plan" in result.text
    assert [reference.label for reference in result.references] == ["src/main.py"]
    assert result.truncated is True
    assert any("truncated recursive source tree" in item for item in result.warnings)
    assert any("src/huge.py" in item for item in result.warnings)
    assert len(paths) == 2


def test_aggregate_character_limit_truncates_a_file() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/git/trees/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [{"path": "main.py", "type": "blob", "size": 100}],
                },
                request=request,
            )
        return httpx.Response(200, content=b"x" * 100, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GitHubContentSource(client).retrieve(
            repository(),
            include_patterns=("*.py",),
            exclude_patterns=(),
            max_files=1,
            max_file_bytes=1_000,
            max_total_characters=30,
        )

    assert len(result.text) == 30
    assert result.references[0].truncated is True
    assert result.truncated is True


def test_no_matching_source_files_is_fallback_safe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [{"path": "README.md", "type": "blob", "size": 20}],
            },
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GitHubContentError, match="no matching source files"):
            GitHubContentSource(client).retrieve(
                repository(),
                include_patterns=("*.py",),
                exclude_patterns=(),
                max_files=1,
                max_file_bytes=1_000,
                max_total_characters=1_000,
            )


def test_rate_limit_is_translated_to_content_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0"},
            json={"message": "API rate limit exceeded"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GitHubContentError, match="rate limit"):
            GitHubContentSource(client).retrieve(
                repository(),
                include_patterns=("*.py",),
                exclude_patterns=(),
                max_files=1,
                max_file_bytes=1_000,
                max_total_characters=1_000,
            )
