import pytest

from researchpilot.application import (
    PipelineStepDefinition,
    PipelineStepExecution,
    RunPipeline,
)
from researchpilot.domain import PipelineStepStatus, RunStatus
from researchpilot.persistence import Database, SQLitePipelineRepository


def test_pipeline_resumes_after_hard_interruption_without_repeating_success(
    tmp_path,
) -> None:
    database = Database(tmp_path / "researchpilot.db")
    database.initialize()
    repository = SQLitePipelineRepository(database)
    calls = {"first": 0, "interrupted": 0}

    def first(_context):
        calls["first"] += 1
        return PipelineStepExecution({"inserted": 1})

    def interrupted(_context):
        calls["interrupted"] += 1
        if calls["interrupted"] == 1:
            raise KeyboardInterrupt
        return PipelineStepExecution({"retried": True})

    steps = (
        PipelineStepDefinition("first", True, first),
        PipelineStepDefinition("interrupted", True, interrupted),
    )

    with pytest.raises(KeyboardInterrupt):
        RunPipeline(repository).execute("key", steps)

    active_steps = repository.list_steps(1)
    assert active_steps[0].status is PipelineStepStatus.SUCCEEDED
    assert active_steps[1].status is PipelineStepStatus.RUNNING

    result = RunPipeline(repository).execute("key", steps)

    assert result.resumed is True
    assert result.succeeded is True
    assert result.run.status is RunStatus.SUCCEEDED
    assert calls == {"first": 1, "interrupted": 2}
    assert result.steps[1].attempt_count == 2


def test_pipeline_records_normal_failure_and_stops_later_steps(tmp_path) -> None:
    database = Database(tmp_path / "researchpilot.db")
    database.initialize()
    repository = SQLitePipelineRepository(database)
    later_calls = 0

    def fail(_context):
        raise RuntimeError("service unavailable")

    def later(_context):
        nonlocal later_calls
        later_calls += 1
        return PipelineStepExecution()

    result = RunPipeline(repository).execute(
        "key",
        (
            PipelineStepDefinition("failure", True, fail),
            PipelineStepDefinition("later", True, later),
        ),
    )

    assert result.succeeded is False
    assert result.failed_step == "failure"
    assert result.run.status is RunStatus.FAILED
    assert result.steps[0].status is PipelineStepStatus.FAILED
    assert result.steps[0].error == "service unavailable"
    assert result.steps[1].status is PipelineStepStatus.PENDING
    assert later_calls == 0


def test_pipeline_persists_disabled_and_dynamic_skips(tmp_path) -> None:
    database = Database(tmp_path / "researchpilot.db")
    database.initialize()

    result = RunPipeline(SQLitePipelineRepository(database)).execute(
        "key",
        (
            PipelineStepDefinition("disabled", False, lambda _context: None),
            PipelineStepDefinition(
                "no_content",
                True,
                lambda _context: PipelineStepExecution.skip(
                    "nothing selected",
                    built=False,
                ),
            ),
        ),
    )

    assert result.succeeded is True
    assert [step.status for step in result.steps] == [
        PipelineStepStatus.SKIPPED,
        PipelineStepStatus.SKIPPED,
    ]
    assert result.steps[0].result == {"reason": "disabled"}
    assert result.steps[1].result == {
        "built": False,
        "reason": "nothing selected",
    }
