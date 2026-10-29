"""Resumable orchestration for the configured end-to-end pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from researchpilot.domain import (
    PipelineStepRecord,
    PipelineStepStatus,
    RunRecord,
    RunStatus,
)
from researchpilot.domain.ports import PipelineRepository

StepMetric = str | int | float | bool | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PipelineContext:
    """The original run clock and latest persisted step state."""

    run: RunRecord
    steps: Mapping[str, PipelineStepRecord]


@dataclass(frozen=True)
class PipelineStepExecution:
    """Scalar metrics and optional skip decision returned by one step."""

    metrics: dict[str, StepMetric] = field(default_factory=dict)
    skipped: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.skipped and (self.reason is None or not self.reason.strip()):
            raise ValueError("a skipped pipeline step requires a reason")
        if not self.skipped and self.reason is not None:
            raise ValueError("a completed pipeline step cannot have a skip reason")

    @classmethod
    def skip(
        cls,
        reason: str,
        **metrics: StepMetric,
    ) -> PipelineStepExecution:
        """Create an intentional dynamic skip outcome."""

        return cls(metrics=dict(metrics), skipped=True, reason=reason)


@dataclass(frozen=True)
class PipelineStepDefinition:
    """One named, ordered, optionally enabled pipeline operation."""

    name: str
    enabled: bool
    execute: Callable[[PipelineContext], PipelineStepExecution]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("pipeline step name must not be empty")


@dataclass(frozen=True)
class PipelineRunResult:
    """Final persisted run and step state returned to an interface."""

    run: RunRecord
    steps: tuple[PipelineStepRecord, ...]
    resumed: bool
    failed_step: str | None = None

    @property
    def succeeded(self) -> bool:
        """Whether every enabled pipeline step completed successfully."""

        return self.run.status is RunStatus.SUCCEEDED


class RunPipeline:
    """Execute incomplete steps in order and resume hard-interrupted runs."""

    def __init__(
        self,
        repository: PipelineRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        run_key: str,
        steps: tuple[PipelineStepDefinition, ...],
        *,
        command: str = "run",
    ) -> PipelineRunResult:
        """Run pending work, retaining running state on process interruption."""

        if not steps:
            raise ValueError("pipeline requires at least one step")
        names = [step.name for step in steps]
        if len(names) != len(set(names)):
            raise ValueError("pipeline step names must be unique")
        session = self._repository.begin_or_resume(
            run_key,
            command,
            tuple((step.name, step.enabled) for step in steps),
            started_at=self._clock(),
        )
        records = {step.name: step for step in session.steps}

        for definition in steps:
            record = records[definition.name]
            if record.status in {
                PipelineStepStatus.SUCCEEDED,
                PipelineStepStatus.SKIPPED,
            }:
                continue
            records[definition.name] = self._repository.start_step(
                session.run.id,
                definition.name,
                started_at=self._clock(),
            )
            try:
                execution = definition.execute(
                    PipelineContext(run=session.run, steps=dict(records))
                )
                if not isinstance(execution, PipelineStepExecution):
                    raise TypeError(
                        "pipeline step must return PipelineStepExecution"
                    )
            except Exception as exc:
                error = str(exc).strip() or type(exc).__name__
                records[definition.name] = self._repository.fail_step(
                    session.run.id,
                    definition.name,
                    error,
                    finished_at=self._clock(),
                )
                run = self._repository.finish_run(
                    session.run.id,
                    RunStatus.FAILED,
                    finished_at=self._clock(),
                    error=f"{definition.name}: {error}",
                )
                return PipelineRunResult(
                    run=run,
                    steps=tuple(self._repository.list_steps(run.id)),
                    resumed=session.resumed,
                    failed_step=definition.name,
                )

            metrics = dict(execution.metrics)
            if execution.skipped:
                metrics["reason"] = execution.reason
                records[definition.name] = self._repository.skip_step(
                    session.run.id,
                    definition.name,
                    metrics,
                    finished_at=self._clock(),
                )
            else:
                records[definition.name] = self._repository.succeed_step(
                    session.run.id,
                    definition.name,
                    metrics,
                    finished_at=self._clock(),
                )

        run = self._repository.finish_run(
            session.run.id,
            RunStatus.SUCCEEDED,
            finished_at=self._clock(),
        )
        return PipelineRunResult(
            run=run,
            steps=tuple(self._repository.list_steps(run.id)),
            resumed=session.resumed,
        )
