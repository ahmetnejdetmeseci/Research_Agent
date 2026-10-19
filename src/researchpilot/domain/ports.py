"""Interfaces implemented by ResearchPilot persistence adapters."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, Protocol

from researchpilot.domain.models import (
    AbstractAnalysis,
    AnalysisContentKind,
    AnalysisContentTrace,
    Paper,
    PaperAnalysisRecord,
    PaperSource,
    RepositoryAnalysis,
    RepositoryAnalysisRecord,
    RepositorySource,
    RetrievedContent,
    RunRecord,
    RunStatus,
    SoftwareRepository,
)


class LLMProviderError(Exception):
    """A provider-independent text-generation failure."""


class ContentRetrievalError(Exception):
    """A provider-independent content acquisition or extraction failure."""


class DigestWriter(Protocol):
    """Persist one generated digest without coupling construction to storage."""

    def write(self, filename: str, content: str) -> str:
        """Write content idempotently and return its display path."""


class LLMProvider(Protocol):
    """Generate structured text without exposing provider transport details."""

    @property
    def provider_name(self) -> str:
        """Return the stable provider identifier."""

    @property
    def model_name(self) -> str:
        """Return the configured model identifier."""

    def generate(
        self,
        *,
        system_prompt: str,
        prompt: str,
        response_schema: dict[str, Any],
    ) -> str:
        """Return the provider's raw structured-output text."""


class PaperDiscoverySource(Protocol):
    """Discover normalized papers without exposing provider transport types."""

    def search(
        self,
        *,
        categories: Sequence[str],
        submitted_after: datetime,
        submitted_before: datetime,
        max_results: int,
    ) -> list[Paper]:
        """Return papers matching source categories and submission dates."""


class RepositoryDiscoverySource(Protocol):
    """Discover normalized repositories without exposing provider transport types."""

    def search(
        self,
        *,
        queries: Sequence[str],
        pushed_after: datetime,
        max_results: int,
        max_readme_characters: int,
    ) -> list[SoftwareRepository]:
        """Return repositories matching configured queries and activity date."""


class PaperContentProvider(Protocol):
    """Retrieve bounded full-paper text without exposing transport details."""

    def retrieve(
        self,
        paper: Paper,
        *,
        max_download_bytes: int,
        max_pages: int,
        max_characters: int,
    ) -> RetrievedContent:
        """Return extracted full text and provenance for a paper."""


class RepositoryContentProvider(Protocol):
    """Retrieve bounded selected source files from a repository."""

    def retrieve(
        self,
        repository: SoftwareRepository,
        *,
        include_patterns: Sequence[str],
        exclude_patterns: Sequence[str],
        max_files: int,
        max_file_bytes: int,
        max_total_characters: int,
    ) -> RetrievedContent:
        """Return selected source text and provenance for a repository."""


class PaperRepository(Protocol):
    """Persistence operations needed by paper workflows."""

    def add(self, paper: Paper) -> bool:
        """Store a paper, returning whether a new row was inserted."""

    def add_many(self, papers: Iterable[Paper]) -> int:
        """Atomically store papers and return the number inserted."""

    def get(self, source: PaperSource, external_id: str) -> Paper | None:
        """Find one paper by its stable source identity."""

    def list_all(self) -> list[Paper]:
        """Return all papers in deterministic order."""

    def count(self) -> int:
        """Return the number of stored papers."""


class RepositoryStore(Protocol):
    """Persistence operations needed by repository workflows."""

    def add(self, repository: SoftwareRepository) -> bool:
        """Store a repository, returning whether a new row was inserted."""

    def add_many(self, repositories: Iterable[SoftwareRepository]) -> int:
        """Atomically store repositories and return the number inserted."""

    def get(
        self,
        source: RepositorySource,
        external_id: str,
    ) -> SoftwareRepository | None:
        """Find one repository by its stable source identity."""

    def list_all(self) -> list[SoftwareRepository]:
        """Return all repositories in deterministic order."""

    def count(self) -> int:
        """Return the number of stored repositories."""


class RunRepository(Protocol):
    """Persistence operations for command-run history."""

    def start(self, command: str, started_at: datetime | None = None) -> RunRecord:
        """Create a running history record."""

    def finish(
        self,
        run_id: int,
        status: RunStatus,
        *,
        finished_at: datetime | None = None,
        error: str | None = None,
    ) -> RunRecord:
        """Finish a running history record exactly once."""

    def get(self, run_id: int) -> RunRecord | None:
        """Find a history record by ID."""


class AnalysisRepository(Protocol):
    """Persist auditable paper-analysis attempts."""

    def get_success(
        self,
        source: PaperSource,
        external_id: str,
        provider: str,
        model: str,
        content_kind: AnalysisContentKind = AnalysisContentKind.ABSTRACT,
    ) -> PaperAnalysisRecord | None:
        """Return a successful matching analysis, if one exists."""

    def begin_attempt(
        self,
        paper: Paper,
        provider: str,
        model: str,
        *,
        content_trace: AnalysisContentTrace | None = None,
        started_at: datetime | None = None,
    ) -> PaperAnalysisRecord:
        """Create a new running attempt, preserving earlier attempts."""

    def succeed(
        self,
        attempt_id: int,
        result: AbstractAnalysis,
        raw_output: str,
        *,
        completed_at: datetime | None = None,
    ) -> PaperAnalysisRecord:
        """Complete a running attempt successfully."""

    def fail(
        self,
        attempt_id: int,
        error: str,
        *,
        raw_output: str | None = None,
        completed_at: datetime | None = None,
    ) -> PaperAnalysisRecord:
        """Mark a running attempt failed while retaining diagnostics."""

    def list_attempts(
        self,
        source: PaperSource,
        external_id: str,
    ) -> list[PaperAnalysisRecord]:
        """Return a paper's analysis history in attempt order."""


class RepositoryAnalysisStore(Protocol):
    """Persist auditable repository-analysis attempts."""

    def get_success(
        self,
        source: RepositorySource,
        external_id: str,
        provider: str,
        model: str,
        content_kind: AnalysisContentKind = AnalysisContentKind.README,
    ) -> RepositoryAnalysisRecord | None:
        """Return a successful matching analysis, if one exists."""

    def begin_attempt(
        self,
        repository: SoftwareRepository,
        provider: str,
        model: str,
        *,
        content_trace: AnalysisContentTrace | None = None,
        started_at: datetime | None = None,
    ) -> RepositoryAnalysisRecord:
        """Create a new running attempt, preserving earlier attempts."""

    def succeed(
        self,
        attempt_id: int,
        result: RepositoryAnalysis,
        raw_output: str,
        *,
        completed_at: datetime | None = None,
    ) -> RepositoryAnalysisRecord:
        """Complete a running attempt successfully."""

    def fail(
        self,
        attempt_id: int,
        error: str,
        *,
        raw_output: str | None = None,
        completed_at: datetime | None = None,
    ) -> RepositoryAnalysisRecord:
        """Mark a running attempt failed while retaining diagnostics."""

    def list_attempts(
        self,
        source: RepositorySource,
        external_id: str,
    ) -> list[RepositoryAnalysisRecord]:
        """Return a repository's analysis history in attempt order."""
