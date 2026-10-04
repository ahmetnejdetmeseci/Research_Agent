"""Interfaces implemented by ResearchPilot persistence adapters."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, Protocol

from researchpilot.domain.models import (
    AbstractAnalysis,
    Paper,
    PaperAnalysisRecord,
    PaperSource,
    RunRecord,
    RunStatus,
)


class LLMProviderError(Exception):
    """A provider-independent text-generation failure."""


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
    ) -> PaperAnalysisRecord | None:
        """Return a successful matching analysis, if one exists."""

    def begin_attempt(
        self,
        paper: Paper,
        provider: str,
        model: str,
        *,
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
