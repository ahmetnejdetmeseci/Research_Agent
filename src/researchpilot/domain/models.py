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


class RepositorySource(StrEnum):
    """A supported source of software-repository metadata."""

    GITHUB = "github"


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


class SoftwareRepository(DomainModel):
    """Normalized repository metadata independent of an external API response."""

    source: RepositorySource
    external_id: NonEmptyString
    full_name: NonEmptyString
    owner: NonEmptyString
    name: NonEmptyString
    description: NonEmptyString | None = None
    readme: NonEmptyString | None = None
    url: HttpUrl
    default_branch: NonEmptyString
    primary_language: NonEmptyString | None = None
    topics: list[NonEmptyString] = Field(default_factory=list)
    stars: int = Field(default=0, ge=0)
    forks: int = Field(default=0, ge=0)
    archived: bool = False
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime | None = None

    @field_validator("created_at", "updated_at", "pushed_at")
    @classmethod
    def repository_timestamps_must_include_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """Require unambiguous timestamps at the domain boundary."""

        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value


class RankedRepository(DomainModel):
    """A repository plus its deterministic ranking explanation."""

    repository: SoftwareRepository
    score: float = Field(ge=0)
    keyword_score: float = Field(ge=0)
    recency_bonus: float = Field(ge=0)
    matches: list[KeywordMatch] = Field(default_factory=list)
    exclusions: list[NonEmptyString] = Field(default_factory=list)
    selected: bool


class AbstractAnalysis(DomainModel):
    """Validated paper analysis, retained under its original public name."""

    summary: NonEmptyString
    key_contributions: list[NonEmptyString] = Field(min_length=1, max_length=5)
    relevance_to_profile: NonEmptyString
    limitations: list[NonEmptyString] = Field(default_factory=list, max_length=5)


class RepositoryAnalysis(DomainModel):
    """Validated analysis generated from bounded repository content."""

    summary: NonEmptyString
    key_capabilities: list[NonEmptyString] = Field(min_length=1, max_length=5)
    relevance_to_profile: NonEmptyString
    notable_technologies: list[NonEmptyString] = Field(
        default_factory=list,
        max_length=10,
    )
    limitations: list[NonEmptyString] = Field(default_factory=list, max_length=5)


class AnalysisContentKind(StrEnum):
    """The bounded content supplied to one LLM analysis attempt."""

    ABSTRACT = "abstract"
    FULL_PAPER = "full_paper"
    README = "readme"
    SOURCE_FILES = "source_files"
    README_AND_SOURCE_FILES = "readme_and_source_files"


class ContentReference(DomainModel):
    """Traceable provenance for one piece of retrieved analysis content."""

    label: NonEmptyString
    locator: NonEmptyString
    characters: int = Field(ge=0)
    truncated: bool = False
    pages: int | None = Field(default=None, ge=1)


class RetrievedContent(DomainModel):
    """Bounded text returned by a provider-independent content adapter."""

    text: NonEmptyString
    references: list[ContentReference] = Field(min_length=1)
    truncated: bool = False
    warnings: list[NonEmptyString] = Field(default_factory=list)


class AnalysisContentTrace(DomainModel):
    """Persisted provenance for content used without storing the content itself."""

    kind: AnalysisContentKind
    references: list[ContentReference] = Field(default_factory=list)
    truncated: bool = False
    warnings: list[NonEmptyString] = Field(default_factory=list)


class AnalysisStatus(StrEnum):
    """Lifecycle state for one LLM analysis attempt."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PaperAnalysisRecord(DomainModel):
    """One persisted, auditable attempt to analyze bounded paper content."""

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
    content_trace: AnalysisContentTrace = Field(
        default_factory=lambda: AnalysisContentTrace(
            kind=AnalysisContentKind.ABSTRACT
        )
    )
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


class RepositoryAnalysisRecord(DomainModel):
    """One persisted, auditable attempt to analyze repository content."""

    id: int = Field(gt=0)
    repository_source: RepositorySource
    repository_external_id: NonEmptyString
    provider: NonEmptyString
    model: NonEmptyString
    attempt_number: int = Field(gt=0)
    status: AnalysisStatus
    result: RepositoryAnalysis | None = None
    raw_output: str | None = None
    error: str | None = None
    content_trace: AnalysisContentTrace = Field(
        default_factory=lambda: AnalysisContentTrace(
            kind=AnalysisContentKind.README
        )
    )
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


class DigestItemKind(StrEnum):
    """The normalized research-item types included in a digest."""

    PAPER = "paper"
    REPOSITORY = "repository"


class DigestEntry(DomainModel):
    """One ranked, analyzed research item ready for digest rendering."""

    kind: DigestItemKind
    source: NonEmptyString
    external_id: NonEmptyString
    title: NonEmptyString
    url: HttpUrl
    score: float = Field(ge=0)
    matches: list[KeywordMatch] = Field(default_factory=list)
    summary: NonEmptyString
    highlights: list[NonEmptyString] = Field(min_length=1, max_length=5)
    relevance_to_profile: NonEmptyString
    notable_technologies: list[NonEmptyString] = Field(
        default_factory=list,
        max_length=10,
    )
    limitations: list[NonEmptyString] = Field(default_factory=list, max_length=5)
    analysis_provider: NonEmptyString
    analysis_model: NonEmptyString
    content_trace: AnalysisContentTrace
    analyzed_at: datetime

    @field_validator("analyzed_at")
    @classmethod
    def analyzed_at_must_include_timezone(cls, value: datetime) -> datetime:
        """Require an unambiguous analysis completion timestamp."""

        if value.tzinfo is None:
            raise ValueError("analyzed_at must include a timezone")
        return value


class ResearchDigest(DomainModel):
    """A deterministic snapshot of ranked, successfully analyzed items."""

    profile_name: NonEmptyString
    as_of: datetime
    entries: list[DigestEntry] = Field(min_length=1)

    @field_validator("as_of")
    @classmethod
    def as_of_must_include_timezone(cls, value: datetime) -> datetime:
        """Require an unambiguous ranking snapshot timestamp."""

        if value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return value


class ExportDisposition(StrEnum):
    """How an exporter changed a destination artifact."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


class DigestExportReceipt(DomainModel):
    """Provider-independent result returned by a digest exporter."""

    path: NonEmptyString
    disposition: ExportDisposition


class RunStatus(StrEnum):
    """Lifecycle state for one ResearchPilot command run."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunRecord(DomainModel):
    """A persisted record of a ResearchPilot command execution."""

    id: int = Field(gt=0)
    command: NonEmptyString
    run_key: NonEmptyString | None = None
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


class PipelineStepStatus(StrEnum):
    """Lifecycle state for one persisted pipeline step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStepRecord(DomainModel):
    """Persisted state and scalar metrics for one pipeline step."""

    id: int = Field(gt=0)
    run_id: int = Field(gt=0)
    name: NonEmptyString
    position: int = Field(ge=0)
    status: PipelineStepStatus
    attempt_count: int = Field(ge=0)
    result: dict[str, str | int | float | bool | None] | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def step_timestamps_must_include_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """Require unambiguous timestamps in pipeline history."""

        if value is not None and value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def state_must_be_consistent(self) -> Self:
        """Reject impossible pending, running, and completed step states."""

        if self.status is PipelineStepStatus.PENDING:
            if self.attempt_count or any(
                value is not None
                for value in (
                    self.result,
                    self.error,
                    self.started_at,
                    self.finished_at,
                )
            ):
                raise ValueError("a pending step cannot contain outcome data")
        elif self.status is PipelineStepStatus.RUNNING:
            if self.attempt_count < 1 or self.started_at is None:
                raise ValueError("a running step requires an attempt and start time")
            if any(
                value is not None
                for value in (self.result, self.error, self.finished_at)
            ):
                raise ValueError("a running step cannot contain an outcome")
        elif self.status is PipelineStepStatus.SUCCEEDED:
            if (
                self.attempt_count < 1
                or self.started_at is None
                or self.finished_at is None
                or self.result is None
                or self.error is not None
            ):
                raise ValueError("a succeeded step requires result and timestamps")
        elif self.status is PipelineStepStatus.FAILED:
            if (
                self.attempt_count < 1
                or self.started_at is None
                or self.finished_at is None
                or not self.error
                or self.result is not None
            ):
                raise ValueError("a failed step requires error and timestamps")
        elif self.status is PipelineStepStatus.SKIPPED:
            if self.finished_at is None or self.result is None or self.error is not None:
                raise ValueError("a skipped step requires a result and finish time")
        return self


class PipelineSession(DomainModel):
    """A newly started or resumable pipeline run and its ordered steps."""

    run: RunRecord
    steps: list[PipelineStepRecord] = Field(min_length=1)
    resumed: bool
