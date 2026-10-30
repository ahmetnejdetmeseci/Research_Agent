"""HTTP response models for the ResearchPilot API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from researchpilot.application import PipelineRunResult
from researchpilot.domain import (
    PipelineRunHistory,
    PipelineStepRecord,
    RankedPaper,
    RankedRepository,
    RunRecord,
)
from researchpilot.runtime import (
    PaperRankingSnapshot,
    RepositoryRankingSnapshot,
    ResearchPilotRuntime,
)


class APIModel(BaseModel):
    """Strict base model shared by API responses."""

    model_config = ConfigDict(extra="forbid")


class HealthResponse(APIModel):
    """Lightweight process health response."""

    status: str
    version: str


class DatabaseStatusResponse(APIModel):
    """Safe local database status exposed to the dashboard."""

    path: str
    current_version: int
    latest_version: int
    pending_migrations: int
    papers: int
    repositories: int
    runs: int
    analysis_attempts: int
    repository_analysis_attempts: int
    pipeline_steps: int


class SourceStatusResponse(APIModel):
    """Configured discovery source availability."""

    arxiv: bool
    github: bool


class StatusResponse(APIModel):
    """Dashboard overview without credentials or secret values."""

    version: str
    profile: str
    ollama_model: str
    sources: SourceStatusResponse
    obsidian_export: bool
    database: DatabaseStatusResponse

    @classmethod
    def from_runtime(
        cls,
        runtime: ResearchPilotRuntime,
        *,
        version: str,
    ) -> StatusResponse:
        """Build a presentation response from shared runtime state."""

        config = runtime.config
        status = runtime.database_status()
        return cls(
            version=version,
            profile=config.profile.name,
            ollama_model=config.ollama.model,
            sources=SourceStatusResponse(
                arxiv=config.sources.arxiv.enabled,
                github=config.sources.github.enabled,
            ),
            obsidian_export=config.exports.obsidian.vault_path is not None,
            database=DatabaseStatusResponse(
                path=str(status.path),
                current_version=status.current_version,
                latest_version=status.latest_version,
                pending_migrations=status.pending_migrations,
                papers=status.paper_count,
                repositories=status.repository_count,
                runs=status.run_count,
                analysis_attempts=status.analysis_attempt_count,
                repository_analysis_attempts=(
                    status.repository_analysis_attempt_count
                ),
                pipeline_steps=status.run_step_count,
            ),
        )


class PaperRankingResponse(APIModel):
    """One timestamped paper-ranking snapshot."""

    as_of: datetime
    count: int
    selected_count: int
    items: list[RankedPaper]

    @classmethod
    def from_snapshot(cls, snapshot: PaperRankingSnapshot) -> PaperRankingResponse:
        return cls(
            as_of=snapshot.as_of,
            count=len(snapshot.items),
            selected_count=snapshot.selected_count,
            items=list(snapshot.items),
        )


class RepositoryRankingResponse(APIModel):
    """One timestamped repository-ranking snapshot."""

    as_of: datetime
    count: int
    selected_count: int
    items: list[RankedRepository]

    @classmethod
    def from_snapshot(
        cls,
        snapshot: RepositoryRankingSnapshot,
    ) -> RepositoryRankingResponse:
        return cls(
            as_of=snapshot.as_of,
            count=len(snapshot.items),
            selected_count=snapshot.selected_count,
            items=list(snapshot.items),
        )


class PipelineRunResponse(APIModel):
    """Persisted pipeline run with ordered step outcomes."""

    run: RunRecord
    steps: list[PipelineStepRecord]

    @classmethod
    def from_history(cls, history: PipelineRunHistory) -> PipelineRunResponse:
        return cls(run=history.run, steps=history.steps)


class PipelineRunListResponse(APIModel):
    """Recent persisted pipeline runs."""

    count: int
    items: list[PipelineRunResponse]

    @classmethod
    def from_history(
        cls,
        history: tuple[PipelineRunHistory, ...],
    ) -> PipelineRunListResponse:
        items = [PipelineRunResponse.from_history(item) for item in history]
        return cls(count=len(items), items=items)


class PipelineExecutionResponse(PipelineRunResponse):
    """Immediate outcome from starting or resuming the pipeline."""

    resumed: bool
    failed_step: str | None

    @classmethod
    def from_result(
        cls,
        result: PipelineRunResult,
    ) -> PipelineExecutionResponse:
        return cls(
            run=result.run,
            steps=list(result.steps),
            resumed=result.resumed,
            failed_step=result.failed_step,
        )
