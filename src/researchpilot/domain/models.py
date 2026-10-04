"""Provider-independent models used by ResearchPilot workflows."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class DomainModel(BaseModel):
    """Base settings shared by strict domain models."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Interest(DomainModel):
    """A weighted topic and the terms that identify it."""

    name: NonEmptyString
    keywords: list[NonEmptyString] = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0, le=10)

    @field_validator("keywords")
    @classmethod
    def keywords_must_be_unique(cls, value: list[str]) -> list[str]:
        """Reject duplicate keywords using case-insensitive comparison."""

        normalized = [keyword.casefold() for keyword in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("keywords must be unique within an interest")
        return value


class InterestProfile(DomainModel):
    """The user's weighted interests and explicit exclusions."""

    name: NonEmptyString
    interests: list[Interest] = Field(min_length=1)
    exclusions: list[NonEmptyString] = Field(default_factory=list)

    @field_validator("exclusions")
    @classmethod
    def exclusions_must_be_unique(cls, value: list[str]) -> list[str]:
        """Reject duplicate exclusion terms."""

        normalized = [exclusion.casefold() for exclusion in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("exclusions must be unique")
        return value

    @model_validator(mode="after")
    def interest_names_must_be_unique(self) -> Self:
        """Reject duplicate interest names."""

        names = [interest.name.casefold() for interest in self.interests]
        if len(names) != len(set(names)):
            raise ValueError("interest names must be unique")
        return self


class PaperSource(StrEnum):
    """A supported source of paper metadata."""

    ARXIV = "arxiv"


class Paper(DomainModel):
    """Normalized paper metadata independent of an external API response."""

    source: PaperSource
    external_id: NonEmptyString
    title: NonEmptyString
    abstract: NonEmptyString
    authors: list[NonEmptyString] = Field(min_length=1)
    published_at: datetime
    updated_at: datetime | None = None
    url: HttpUrl
    pdf_url: HttpUrl | None = None
    categories: list[NonEmptyString] = Field(default_factory=list)

    @field_validator("published_at", "updated_at")
    @classmethod
    def timestamps_must_include_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """Require unambiguous timestamps at the domain boundary."""

        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value


class KeywordMatch(DomainModel):
    """One explainable keyword contribution to a paper's rank."""

    interest_name: NonEmptyString
    keyword: NonEmptyString
    contribution: float = Field(gt=0)


class RankedPaper(DomainModel):
    """A paper plus its deterministic ranking decision and explanation."""

    paper: Paper
    score: float = Field(ge=0)
    keyword_score: float = Field(ge=0)
    recency_bonus: float = Field(ge=0)
    matches: list[KeywordMatch] = Field(default_factory=list)
    exclusions: list[NonEmptyString] = Field(default_factory=list)
    selected: bool


class AbstractAnalysis(DomainModel):
    """Validated structured analysis generated from a paper abstract."""

    summary: NonEmptyString
    key_contributions: list[NonEmptyString] = Field(min_length=1, max_length=5)
    relevance_to_profile: NonEmptyString
    limitations: list[NonEmptyString] = Field(default_factory=list, max_length=5)


class AnalysisStatus(StrEnum):
    """Lifecycle state for one LLM analysis attempt."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PaperAnalysisRecord(DomainModel):
    """One persisted, auditable attempt to analyze a paper abstract."""

    id: int = Field(gt=0)
    paper_source: PaperSource
    paper_external_id: NonEmptyString
    provider: NonEmptyString
    model: NonEmptyString
    attempt_number: int = Field(gt=0)
    status: AnalysisStatus
    result: AbstractAnalysis | None = None
    raw_output: str | None = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime | None = None

    @field_validator("started_at", "completed_at")
    @classmethod
    def analysis_timestamps_must_include_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """Require unambiguous timestamps for analysis attempts."""

        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def state_must_be_consistent(self) -> Self:
        """Keep running, succeeded, and failed records internally consistent."""

        if self.status is AnalysisStatus.RUNNING:
            if self.result is not None or self.error is not None or self.completed_at:
                raise ValueError("a running analysis cannot contain a result or error")
        elif self.status is AnalysisStatus.SUCCEEDED:
            if self.result is None or not self.raw_output or self.completed_at is None:
                raise ValueError(
                    "a succeeded analysis requires result, raw output, and completion time"
                )
            if self.error is not None:
                raise ValueError("a succeeded analysis cannot contain an error")
        elif self.status is AnalysisStatus.FAILED:
            if not self.error or self.completed_at is None:
                raise ValueError("a failed analysis requires error and completion time")
            if self.result is not None:
                raise ValueError("a failed analysis cannot contain a result")
        return self


class RunStatus(StrEnum):
    """Lifecycle state for one ResearchPilot command run."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunRecord(DomainModel):
    """A persisted record of a ResearchPilot command execution."""

    id: int = Field(gt=0)
    command: NonEmptyString
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def run_timestamps_must_include_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """Require unambiguous timestamps in run history."""

        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value
