"""Use-case orchestration independent of CLI, HTTP, and SQLite details."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from researchpilot.domain.ports import (
    PaperDiscoverySource,
    PaperRepository,
    RepositoryDiscoverySource,
    RepositoryStore,
)


@dataclass(frozen=True)
class DiscoveryRequest:
    """Provider-independent parameters for one paper-discovery run."""

    categories: tuple[str, ...]
    submitted_after: datetime
    submitted_before: datetime
    max_results: int

    def __post_init__(self) -> None:
        if not self.categories or any(
            not category.strip() for category in self.categories
        ):
            raise ValueError("at least one non-empty category is required")
        if self.submitted_after.tzinfo is None or self.submitted_before.tzinfo is None:
            raise ValueError("discovery timestamps must include a timezone")
        if self.submitted_after >= self.submitted_before:
            raise ValueError("submitted_after must be earlier than submitted_before")
        if self.max_results < 1:
            raise ValueError("max_results must be positive")


@dataclass(frozen=True)
class DiscoveryResult:
    """Counts produced by one completed paper-discovery run."""

    fetched: int
    inserted: int

    @property
    def duplicates(self) -> int:
        """Return fetched papers that were already stored or repeated."""

        return self.fetched - self.inserted


class DiscoverPapers:
    """Fetch normalized papers from a source and persist unseen identities."""

    def __init__(
        self,
        source: PaperDiscoverySource,
        repository: PaperRepository,
    ) -> None:
        self._source = source
        self._repository = repository

    def execute(self, request: DiscoveryRequest) -> DiscoveryResult:
        """Run discovery once and atomically persist returned papers."""

        papers = self._source.search(
            categories=request.categories,
            submitted_after=request.submitted_after,
            submitted_before=request.submitted_before,
            max_results=request.max_results,
        )
        inserted = self._repository.add_many(papers)
        return DiscoveryResult(fetched=len(papers), inserted=inserted)


@dataclass(frozen=True)
class RepositoryDiscoveryRequest:
    """Provider-independent parameters for repository discovery."""

    queries: tuple[str, ...]
    pushed_after: datetime
    max_results: int
    max_readme_characters: int

    def __post_init__(self) -> None:
        if not self.queries or any(not query.strip() for query in self.queries):
            raise ValueError("at least one non-empty query is required")
        if self.pushed_after.tzinfo is None:
            raise ValueError("pushed_after must include a timezone")
        if self.max_results < 1:
            raise ValueError("max_results must be positive")
        if self.max_readme_characters < 1:
            raise ValueError("max_readme_characters must be positive")


class DiscoverRepositories:
    """Fetch normalized repositories and persist unseen identities."""

    def __init__(
        self,
        source: RepositoryDiscoverySource,
        repository: RepositoryStore,
    ) -> None:
        self._source = source
        self._repository = repository

    def execute(self, request: RepositoryDiscoveryRequest) -> DiscoveryResult:
        """Run discovery once and atomically persist returned repositories."""

        repositories = self._source.search(
            queries=request.queries,
            pushed_after=request.pushed_after,
            max_results=request.max_results,
            max_readme_characters=request.max_readme_characters,
        )
        inserted = self._repository.add_many(repositories)
        return DiscoveryResult(fetched=len(repositories), inserted=inserted)
