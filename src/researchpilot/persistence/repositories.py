"""SQLite implementations of ResearchPilot repository ports."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

from pydantic import ValidationError

from researchpilot.domain import (
    AbstractAnalysis,
    AnalysisContentKind,
    AnalysisContentTrace,
    AnalysisStatus,
    Paper,
    PaperAnalysisRecord,
    PaperSource,
    PipelineSession,
    PipelineStepRecord,
    PipelineStepStatus,
    RepositoryAnalysis,
    RepositoryAnalysisRecord,
    RepositorySource,
    RunRecord,
    RunStatus,
    SoftwareRepository,
)
from researchpilot.persistence.database import Database, PersistenceError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat()


def _optional_timestamp(value: datetime | None) -> str | None:
    return None if value is None else _timestamp(value)


def _paper_from_row(row: sqlite3.Row) -> Paper:
    try:
        return Paper.model_validate(
            {
                "source": row["source"],
                "external_id": row["external_id"],
                "title": row["title"],
                "abstract": row["abstract"],
                "authors": json.loads(row["authors_json"]),
                "published_at": row["published_at"],
                "updated_at": row["updated_at"],
                "url": row["url"],
                "pdf_url": row["pdf_url"],
                "categories": json.loads(row["categories_json"]),
            }
        )
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise PersistenceError(
            f"stored paper {row['source']}:{row['external_id']} is invalid: {exc}"
        ) from exc


def _repository_from_row(row: sqlite3.Row) -> SoftwareRepository:
    try:
        return SoftwareRepository.model_validate(
            {
                "source": row["source"],
                "external_id": row["external_id"],
                "full_name": row["full_name"],
                "owner": row["owner"],
                "name": row["name"],
                "description": row["description"],
                "readme": row["readme"],
                "url": row["url"],
                "default_branch": row["default_branch"],
                "primary_language": row["primary_language"],
                "topics": json.loads(row["topics_json"]),
                "stars": row["stars"],
                "forks": row["forks"],
                "archived": bool(row["archived"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "pushed_at": row["pushed_at"],
            }
        )
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise PersistenceError(
            "stored repository "
            f"{row['source']}:{row['external_id']} is invalid: {exc}"
        ) from exc


def _run_from_row(row: sqlite3.Row) -> RunRecord:
    try:
        return RunRecord.model_validate(dict(row))
    except ValidationError as exc:
        raise PersistenceError(f"stored run {row['id']} is invalid: {exc}") from exc


def _pipeline_step_from_row(row: sqlite3.Row) -> PipelineStepRecord:
    try:
        result = (
            None if row["result_json"] is None else json.loads(row["result_json"])
        )
        return PipelineStepRecord(
            id=row["id"],
            run_id=row["run_id"],
            name=row["name"],
            position=row["position"],
            status=row["status"],
            attempt_count=row["attempt_count"],
            result=result,
            error=row["error"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise PersistenceError(
            f"stored pipeline step {row['id']} is invalid: {exc}"
        ) from exc


PIPELINE_STEP_SELECT = """
    SELECT id, run_id, name, position, status, attempt_count,
           result_json, error, started_at, finished_at
    FROM run_steps
"""


def _analysis_from_row(row: sqlite3.Row) -> PaperAnalysisRecord:
    try:
        result = (
            None
            if row["result_json"] is None
            else AbstractAnalysis.model_validate_json(row["result_json"])
        )
        content_trace = AnalysisContentTrace.model_validate_json(
            row["content_trace_json"]
        )
        return PaperAnalysisRecord(
            id=row["id"],
            paper_source=row["paper_source"],
            paper_external_id=row["paper_external_id"],
            provider=row["provider"],
            model=row["model"],
            attempt_number=row["attempt_number"],
            status=row["status"],
            result=result,
            raw_output=row["raw_output"],
            error=row["error"],
            content_trace=content_trace,
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise PersistenceError(
            f"stored analysis attempt {row['id']} is invalid: {exc}"
        ) from exc


ANALYSIS_SELECT = """
    SELECT a.id,
           p.source AS paper_source,
           p.external_id AS paper_external_id,
           a.provider,
           a.model,
           a.attempt_number,
           a.status,
           a.result_json,
           a.raw_output,
           a.error,
           a.content_trace_json,
           a.started_at,
           a.completed_at
    FROM paper_analysis_attempts AS a
    JOIN papers AS p ON p.id = a.paper_id
"""


def _repository_analysis_from_row(row: sqlite3.Row) -> RepositoryAnalysisRecord:
    try:
        result = (
            None
            if row["result_json"] is None
            else RepositoryAnalysis.model_validate_json(row["result_json"])
        )
        content_trace = AnalysisContentTrace.model_validate_json(
            row["content_trace_json"]
        )
        return RepositoryAnalysisRecord(
            id=row["id"],
            repository_source=row["repository_source"],
            repository_external_id=row["repository_external_id"],
            provider=row["provider"],
            model=row["model"],
            attempt_number=row["attempt_number"],
            status=row["status"],
            result=result,
            raw_output=row["raw_output"],
            error=row["error"],
            content_trace=content_trace,
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise PersistenceError(
            f"stored repository analysis attempt {row['id']} is invalid: {exc}"
        ) from exc


REPOSITORY_ANALYSIS_SELECT = """
    SELECT a.id,
           r.source AS repository_source,
           r.external_id AS repository_external_id,
           a.provider,
           a.model,
           a.attempt_number,
           a.status,
           a.result_json,
           a.raw_output,
           a.error,
           a.content_trace_json,
           a.started_at,
           a.completed_at
    FROM repository_analysis_attempts AS a
    JOIN repositories AS r ON r.id = a.repository_id
"""


class SQLitePaperRepository:
    """Store normalized papers in SQLite with source-level deduplication."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, paper: Paper) -> bool:
        """Store a paper, returning whether it was newly inserted."""

        return self.add_many([paper]) == 1

    def add_many(self, papers: Iterable[Paper]) -> int:
        """Atomically store papers and return the number newly inserted."""

        inserted = 0
        discovered_at = _timestamp(_utc_now())
        try:
            with self._database.transaction() as connection:
                for paper in papers:
                    cursor = connection.execute(
                        """
                        INSERT INTO papers (
                            source,
                            external_id,
                            title,
                            abstract,
                            authors_json,
                            published_at,
                            updated_at,
                            url,
                            pdf_url,
                            categories_json,
                            discovered_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source, external_id) DO NOTHING
                        """,
                        (
                            paper.source.value,
                            paper.external_id,
                            paper.title,
                            paper.abstract,
                            json.dumps(paper.authors, ensure_ascii=False),
                            _timestamp(paper.published_at),
                            _optional_timestamp(paper.updated_at),
                            str(paper.url),
                            None if paper.pdf_url is None else str(paper.pdf_url),
                            json.dumps(paper.categories, ensure_ascii=False),
                            discovered_at,
                        ),
                    )
                    inserted += cursor.rowcount
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not store papers: {exc}") from exc
        return inserted

    def get(self, source: PaperSource, external_id: str) -> Paper | None:
        """Find a paper by its stable source identity."""

        try:
            with self._database.transaction() as connection:
                row = connection.execute(
                    """
                    SELECT source, external_id, title, abstract, authors_json,
                           published_at, updated_at, url, pdf_url, categories_json
                    FROM papers
                    WHERE source = ? AND external_id = ?
                    """,
                    (source.value, external_id),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not read paper: {exc}") from exc
        return None if row is None else _paper_from_row(row)

    def list_all(self) -> list[Paper]:
        """Return all stored papers newest first with deterministic ties."""

        try:
            with self._database.transaction() as connection:
                rows = connection.execute(
                    """
                    SELECT source, external_id, title, abstract, authors_json,
                           published_at, updated_at, url, pdf_url, categories_json
                    FROM papers
                    ORDER BY published_at DESC, source, external_id
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not list papers: {exc}") from exc
        return [_paper_from_row(row) for row in rows]

    def count(self) -> int:
        """Return the number of stored papers."""

        try:
            with self._database.transaction() as connection:
                row = connection.execute("SELECT COUNT(*) AS count FROM papers").fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not count papers: {exc}") from exc
        return int(row["count"])


class SQLiteRepositoryStore:
    """Store normalized software repositories with source-level deduplication."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, repository: SoftwareRepository) -> bool:
        """Store a repository, returning whether it was newly inserted."""

        return self.add_many([repository]) == 1

    def add_many(self, repositories: Iterable[SoftwareRepository]) -> int:
        """Atomically store repositories and return the number newly inserted."""

        inserted = 0
        discovered_at = _timestamp(_utc_now())
        try:
            with self._database.transaction() as connection:
                for repository in repositories:
                    cursor = connection.execute(
                        """
                        INSERT INTO repositories (
                            source, external_id, full_name, owner, name,
                            description, readme, url, default_branch,
                            primary_language, topics_json, stars, forks, archived,
                            created_at, updated_at, pushed_at, discovered_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source, external_id) DO NOTHING
                        """,
                        (
                            repository.source.value,
                            repository.external_id,
                            repository.full_name,
                            repository.owner,
                            repository.name,
                            repository.description,
                            repository.readme,
                            str(repository.url),
                            repository.default_branch,
                            repository.primary_language,
                            json.dumps(repository.topics, ensure_ascii=False),
                            repository.stars,
                            repository.forks,
                            int(repository.archived),
                            _timestamp(repository.created_at),
                            _timestamp(repository.updated_at),
                            _optional_timestamp(repository.pushed_at),
                            discovered_at,
                        ),
                    )
                    inserted += cursor.rowcount
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not store repositories: {exc}") from exc
        return inserted

    def get(
        self,
        source: RepositorySource,
        external_id: str,
    ) -> SoftwareRepository | None:
        """Find a repository by its stable source identity."""

        try:
            with self._database.transaction() as connection:
                row = connection.execute(
                    """
                    SELECT source, external_id, full_name, owner, name,
                           description, readme, url, default_branch,
                           primary_language, topics_json, stars, forks, archived,
                           created_at, updated_at, pushed_at
                    FROM repositories
                    WHERE source = ? AND external_id = ?
                    """,
                    (source.value, external_id),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not read repository: {exc}") from exc
        return None if row is None else _repository_from_row(row)

    def list_all(self) -> list[SoftwareRepository]:
        """Return stored repositories by recent activity with deterministic ties."""

        try:
            with self._database.transaction() as connection:
                rows = connection.execute(
                    """
                    SELECT source, external_id, full_name, owner, name,
                           description, readme, url, default_branch,
                           primary_language, topics_json, stars, forks, archived,
                           created_at, updated_at, pushed_at
                    FROM repositories
                    ORDER BY COALESCE(pushed_at, updated_at) DESC,
                             source, external_id
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not list repositories: {exc}") from exc
        return [_repository_from_row(row) for row in rows]

    def count(self) -> int:
        """Return the number of stored repositories."""

        try:
            with self._database.transaction() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM repositories"
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not count repositories: {exc}") from exc
        return int(row["count"])


class SQLiteRunRepository:
    """Store lifecycle history for ResearchPilot command runs."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def start(self, command: str, started_at: datetime | None = None) -> RunRecord:
        """Create a running history record."""

        command = command.strip()
        if not command:
            raise ValueError("command must not be empty")
        start_time = _utc_now() if started_at is None else started_at
        if start_time.tzinfo is None:
            raise ValueError("started_at must include a timezone")

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO runs(command, status, started_at)
                    VALUES (?, ?, ?)
                    """,
                    (command, RunStatus.RUNNING.value, _timestamp(start_time)),
                )
                row = connection.execute(
                    "SELECT * FROM runs WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not start run history: {exc}") from exc
        return _run_from_row(row)

    def finish(
        self,
        run_id: int,
        status: RunStatus,
        *,
        finished_at: datetime | None = None,
        error: str | None = None,
    ) -> RunRecord:
        """Finish a running history record exactly once."""

        if status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            raise ValueError("finished run status must be succeeded or failed")
        if status is RunStatus.SUCCEEDED and error is not None:
            raise ValueError("a succeeded run cannot have an error")
        finish_time = _utc_now() if finished_at is None else finished_at
        if finish_time.tzinfo is None:
            raise ValueError("finished_at must include a timezone")

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE runs
                    SET status = ?, finished_at = ?, error = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        status.value,
                        _timestamp(finish_time),
                        error,
                        run_id,
                        RunStatus.RUNNING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PersistenceError(
                        f"run {run_id} does not exist or is already finished"
                    )
                row = connection.execute(
                    "SELECT * FROM runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not finish run history: {exc}") from exc
        return _run_from_row(row)

    def get(self, run_id: int) -> RunRecord | None:
        """Find one history record by ID."""

        try:
            with self._database.transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not read run history: {exc}") from exc
        return None if row is None else _run_from_row(row)


class SQLitePipelineRepository:
    """Persist resumable pipeline runs and ordered step outcomes."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def begin_or_resume(
        self,
        run_key: str,
        command: str,
        steps: Sequence[tuple[str, bool]],
        *,
        started_at: datetime | None = None,
    ) -> PipelineSession:
        """Start a pipeline run or resume its unfinished matching run."""

        run_key = run_key.strip()
        command = command.strip()
        if not run_key or not command:
            raise ValueError("run_key and command must not be empty")
        if not steps:
            raise ValueError("pipeline requires at least one step")
        names = [name.strip() for name, _ in steps]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("pipeline step names must be non-empty and unique")
        start_time = _utc_now() if started_at is None else started_at
        if start_time.tzinfo is None:
            raise ValueError("started_at must include a timezone")

        try:
            with self._database.transaction() as connection:
                run_row = connection.execute(
                    """
                    SELECT * FROM runs
                    WHERE run_key = ? AND status = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (run_key, RunStatus.RUNNING.value),
                ).fetchone()
                resumed = run_row is not None
                if run_row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO runs(command, run_key, status, started_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            command,
                            run_key,
                            RunStatus.RUNNING.value,
                            _timestamp(start_time),
                        ),
                    )
                    run_id = int(cursor.lastrowid)
                    for position, ((_, enabled), name) in enumerate(
                        zip(steps, names, strict=True)
                    ):
                        if enabled:
                            status = PipelineStepStatus.PENDING.value
                            result_json = None
                            finished_at = None
                        else:
                            status = PipelineStepStatus.SKIPPED.value
                            result_json = json.dumps(
                                {"reason": "disabled"},
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            finished_at = _timestamp(start_time)
                        connection.execute(
                            """
                            INSERT INTO run_steps (
                                run_id, name, position, status, result_json,
                                finished_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                run_id,
                                name,
                                position,
                                status,
                                result_json,
                                finished_at,
                            ),
                        )
                    run_row = connection.execute(
                        "SELECT * FROM runs WHERE id = ?",
                        (run_id,),
                    ).fetchone()
                run = _run_from_row(run_row)
                step_rows = connection.execute(
                    PIPELINE_STEP_SELECT
                    + " WHERE run_id = ? ORDER BY position",
                    (run.id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not begin pipeline run: {exc}") from exc

        records = [_pipeline_step_from_row(row) for row in step_rows]
        if [record.name for record in records] != names:
            raise PersistenceError(
                f"active pipeline run {run.id} has a different step definition"
            )
        return PipelineSession(run=run, steps=records, resumed=resumed)

    def start_step(
        self,
        run_id: int,
        name: str,
        *,
        started_at: datetime | None = None,
    ) -> PipelineStepRecord:
        """Start or restart an incomplete step and increment its attempt count."""

        start_time = _utc_now() if started_at is None else started_at
        if start_time.tzinfo is None:
            raise ValueError("started_at must include a timezone")
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE run_steps
                    SET status = ?, attempt_count = attempt_count + 1,
                        result_json = NULL, error = NULL, started_at = ?,
                        finished_at = NULL
                    WHERE run_id = ? AND name = ?
                      AND status IN (?, ?, ?)
                      AND EXISTS (
                          SELECT 1 FROM runs
                          WHERE runs.id = run_steps.run_id AND runs.status = ?
                      )
                    """,
                    (
                        PipelineStepStatus.RUNNING.value,
                        _timestamp(start_time),
                        run_id,
                        name,
                        PipelineStepStatus.PENDING.value,
                        PipelineStepStatus.RUNNING.value,
                        PipelineStepStatus.FAILED.value,
                        RunStatus.RUNNING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PersistenceError(
                        f"pipeline step {run_id}:{name} cannot be started"
                    )
                row = connection.execute(
                    PIPELINE_STEP_SELECT + " WHERE run_id = ? AND name = ?",
                    (run_id, name),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not start pipeline step: {exc}") from exc
        return _pipeline_step_from_row(row)

    def succeed_step(
        self,
        run_id: int,
        name: str,
        result: dict[str, str | int | float | bool | None],
        *,
        finished_at: datetime | None = None,
    ) -> PipelineStepRecord:
        """Complete one running step successfully."""

        return self._finish_step(
            run_id,
            name,
            PipelineStepStatus.SUCCEEDED,
            result=result,
            finished_at=finished_at,
        )

    def skip_step(
        self,
        run_id: int,
        name: str,
        result: dict[str, str | int | float | bool | None],
        *,
        finished_at: datetime | None = None,
    ) -> PipelineStepRecord:
        """Complete one running step as intentionally skipped."""

        return self._finish_step(
            run_id,
            name,
            PipelineStepStatus.SKIPPED,
            result=result,
            finished_at=finished_at,
        )

    def fail_step(
        self,
        run_id: int,
        name: str,
        error: str,
        *,
        finished_at: datetime | None = None,
    ) -> PipelineStepRecord:
        """Complete one running step with an error."""

        error = error.strip()
        if not error:
            raise ValueError("pipeline step error must not be empty")
        return self._finish_step(
            run_id,
            name,
            PipelineStepStatus.FAILED,
            error=error,
            finished_at=finished_at,
        )

    def _finish_step(
        self,
        run_id: int,
        name: str,
        status: PipelineStepStatus,
        *,
        result: dict[str, str | int | float | bool | None] | None = None,
        error: str | None = None,
        finished_at: datetime | None = None,
    ) -> PipelineStepRecord:
        finish_time = _utc_now() if finished_at is None else finished_at
        if finish_time.tzinfo is None:
            raise ValueError("finished_at must include a timezone")
        result_json = (
            None
            if result is None
            else json.dumps(result, sort_keys=True, separators=(",", ":"))
        )
        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE run_steps
                    SET status = ?, result_json = ?, error = ?, finished_at = ?
                    WHERE run_id = ? AND name = ? AND status = ?
                    """,
                    (
                        status.value,
                        result_json,
                        error,
                        _timestamp(finish_time),
                        run_id,
                        name,
                        PipelineStepStatus.RUNNING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PersistenceError(
                        f"pipeline step {run_id}:{name} is missing or not running"
                    )
                row = connection.execute(
                    PIPELINE_STEP_SELECT + " WHERE run_id = ? AND name = ?",
                    (run_id, name),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not finish pipeline step: {exc}") from exc
        return _pipeline_step_from_row(row)

    def finish_run(
        self,
        run_id: int,
        status: RunStatus,
        *,
        finished_at: datetime | None = None,
        error: str | None = None,
    ) -> RunRecord:
        """Finish a pipeline run through the existing run lifecycle."""

        return SQLiteRunRepository(self._database).finish(
            run_id,
            status,
            finished_at=finished_at,
            error=error,
        )

    def list_steps(self, run_id: int) -> list[PipelineStepRecord]:
        """Return pipeline steps in configured order."""

        try:
            with self._database.transaction() as connection:
                rows = connection.execute(
                    PIPELINE_STEP_SELECT + " WHERE run_id = ? ORDER BY position",
                    (run_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not list pipeline steps: {exc}") from exc
        return [_pipeline_step_from_row(row) for row in rows]

    def list_runs(self, *, limit: int = 20) -> list[RunRecord]:
        """Return recent pipeline runs newest first."""

        if not 1 <= limit <= 100:
            raise ValueError("pipeline run limit must be between 1 and 100")
        try:
            with self._database.transaction() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM runs
                    WHERE run_key IS NOT NULL
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not list pipeline runs: {exc}") from exc
        return [_run_from_row(row) for row in rows]

    def get_run(self, run_id: int) -> RunRecord | None:
        """Find one pipeline run by ID without exposing legacy command runs."""

        try:
            with self._database.transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM runs WHERE id = ? AND run_key IS NOT NULL",
                    (run_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not read pipeline run: {exc}") from exc
        return None if row is None else _run_from_row(row)


class SQLiteAnalysisRepository:
    """Persist immutable history for abstract-analysis attempts."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_success(
        self,
        source: PaperSource,
        external_id: str,
        provider: str,
        model: str,
        content_kind: AnalysisContentKind = AnalysisContentKind.ABSTRACT,
    ) -> PaperAnalysisRecord | None:
        """Return a successful matching provider/model analysis."""

        try:
            with self._database.transaction() as connection:
                row = connection.execute(
                    ANALYSIS_SELECT
                    + """
                    WHERE p.source = ?
                      AND p.external_id = ?
                      AND a.provider = ?
                      AND a.model = ?
                      AND a.content_kind = ?
                      AND a.status = ?
                    """,
                    (
                        source.value,
                        external_id,
                        provider,
                        model,
                        content_kind.value,
                        AnalysisStatus.SUCCEEDED.value,
                    ),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not read paper analysis: {exc}") from exc
        return None if row is None else _analysis_from_row(row)

    def begin_attempt(
        self,
        paper: Paper,
        provider: str,
        model: str,
        *,
        content_trace: AnalysisContentTrace | None = None,
        started_at: datetime | None = None,
    ) -> PaperAnalysisRecord:
        """Create a new running attempt without overwriting prior diagnostics."""

        provider = provider.strip()
        model = model.strip()
        if not provider or not model:
            raise ValueError("provider and model must not be empty")
        trace = content_trace or AnalysisContentTrace(
            kind=AnalysisContentKind.ABSTRACT
        )
        if trace.kind not in {
            AnalysisContentKind.ABSTRACT,
            AnalysisContentKind.FULL_PAPER,
        }:
            raise ValueError("paper analysis requires paper content provenance")
        start_time = _utc_now() if started_at is None else started_at
        if start_time.tzinfo is None:
            raise ValueError("started_at must include a timezone")

        try:
            with self._database.transaction() as connection:
                paper_row = connection.execute(
                    "SELECT id FROM papers WHERE source = ? AND external_id = ?",
                    (paper.source.value, paper.external_id),
                ).fetchone()
                if paper_row is None:
                    raise PersistenceError(
                        f"paper {paper.source.value}:{paper.external_id} is not stored"
                    )
                paper_id = int(paper_row["id"])
                succeeded = connection.execute(
                    """
                    SELECT 1 FROM paper_analysis_attempts
                    WHERE paper_id = ? AND provider = ? AND model = ?
                      AND content_kind = ?
                      AND status = ?
                    """,
                    (
                        paper_id,
                        provider,
                        model,
                        trace.kind.value,
                        AnalysisStatus.SUCCEEDED.value,
                    ),
                ).fetchone()
                if succeeded is not None:
                    raise PersistenceError(
                        "a successful analysis already exists for "
                        f"{paper.source.value}:{paper.external_id} with "
                        f"{provider}/{model}"
                    )
                number_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(attempt_number), 0) + 1 AS next_number
                    FROM paper_analysis_attempts
                    WHERE paper_id = ? AND provider = ? AND model = ?
                    """,
                    (paper_id, provider, model),
                ).fetchone()
                cursor = connection.execute(
                    """
                    INSERT INTO paper_analysis_attempts (
                        paper_id, provider, model, attempt_number, status,
                        content_kind, content_trace_json, started_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        paper_id,
                        provider,
                        model,
                        int(number_row["next_number"]),
                        AnalysisStatus.RUNNING.value,
                        trace.kind.value,
                        trace.model_dump_json(),
                        _timestamp(start_time),
                    ),
                )
                row = connection.execute(
                    ANALYSIS_SELECT + " WHERE a.id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not start paper analysis: {exc}") from exc
        return _analysis_from_row(row)

    def succeed(
        self,
        attempt_id: int,
        result: AbstractAnalysis,
        raw_output: str,
        *,
        completed_at: datetime | None = None,
    ) -> PaperAnalysisRecord:
        """Complete a running attempt and retain its raw model output."""

        if not raw_output.strip():
            raise ValueError("raw_output must not be empty")
        completion_time = _utc_now() if completed_at is None else completed_at
        if completion_time.tzinfo is None:
            raise ValueError("completed_at must include a timezone")

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE paper_analysis_attempts
                    SET status = ?, result_json = ?, raw_output = ?,
                        error = NULL, completed_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        AnalysisStatus.SUCCEEDED.value,
                        result.model_dump_json(),
                        raw_output,
                        _timestamp(completion_time),
                        attempt_id,
                        AnalysisStatus.RUNNING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PersistenceError(
                        f"analysis attempt {attempt_id} is missing or already finished"
                    )
                row = connection.execute(
                    ANALYSIS_SELECT + " WHERE a.id = ?",
                    (attempt_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not complete paper analysis: {exc}") from exc
        return _analysis_from_row(row)

    def fail(
        self,
        attempt_id: int,
        error: str,
        *,
        raw_output: str | None = None,
        completed_at: datetime | None = None,
    ) -> PaperAnalysisRecord:
        """Fail a running attempt while retaining available diagnostics."""

        error = error.strip()
        if not error:
            raise ValueError("error must not be empty")
        completion_time = _utc_now() if completed_at is None else completed_at
        if completion_time.tzinfo is None:
            raise ValueError("completed_at must include a timezone")

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE paper_analysis_attempts
                    SET status = ?, result_json = NULL, raw_output = ?,
                        error = ?, completed_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        AnalysisStatus.FAILED.value,
                        raw_output,
                        error,
                        _timestamp(completion_time),
                        attempt_id,
                        AnalysisStatus.RUNNING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PersistenceError(
                        f"analysis attempt {attempt_id} is missing or already finished"
                    )
                row = connection.execute(
                    ANALYSIS_SELECT + " WHERE a.id = ?",
                    (attempt_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not fail paper analysis: {exc}") from exc
        return _analysis_from_row(row)

    def list_attempts(
        self,
        source: PaperSource,
        external_id: str,
    ) -> list[PaperAnalysisRecord]:
        """Return all attempts for a paper in creation order."""

        try:
            with self._database.transaction() as connection:
                rows = connection.execute(
                    ANALYSIS_SELECT
                    + """
                    WHERE p.source = ? AND p.external_id = ?
                    ORDER BY a.id
                    """,
                    (source.value, external_id),
                ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(f"could not list paper analyses: {exc}") from exc
        return [_analysis_from_row(row) for row in rows]


class SQLiteRepositoryAnalysisStore:
    """Persist immutable history for repository-content analysis attempts."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_success(
        self,
        source: RepositorySource,
        external_id: str,
        provider: str,
        model: str,
        content_kind: AnalysisContentKind = AnalysisContentKind.README,
    ) -> RepositoryAnalysisRecord | None:
        """Return a successful matching provider/model analysis."""

        try:
            with self._database.transaction() as connection:
                row = connection.execute(
                    REPOSITORY_ANALYSIS_SELECT
                    + """
                    WHERE r.source = ?
                      AND r.external_id = ?
                      AND a.provider = ?
                      AND a.model = ?
                      AND a.content_kind = ?
                      AND a.status = ?
                    """,
                    (
                        source.value,
                        external_id,
                        provider,
                        model,
                        content_kind.value,
                        AnalysisStatus.SUCCEEDED.value,
                    ),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"could not read repository analysis: {exc}"
            ) from exc
        return None if row is None else _repository_analysis_from_row(row)

    def begin_attempt(
        self,
        repository: SoftwareRepository,
        provider: str,
        model: str,
        *,
        content_trace: AnalysisContentTrace | None = None,
        started_at: datetime | None = None,
    ) -> RepositoryAnalysisRecord:
        """Create a new running attempt without overwriting diagnostics."""

        provider = provider.strip()
        model = model.strip()
        if not provider or not model:
            raise ValueError("provider and model must not be empty")
        trace = content_trace or AnalysisContentTrace(
            kind=AnalysisContentKind.README
        )
        if trace.kind not in {
            AnalysisContentKind.README,
            AnalysisContentKind.SOURCE_FILES,
            AnalysisContentKind.README_AND_SOURCE_FILES,
        }:
            raise ValueError(
                "repository analysis requires repository content provenance"
            )
        start_time = _utc_now() if started_at is None else started_at
        if start_time.tzinfo is None:
            raise ValueError("started_at must include a timezone")

        try:
            with self._database.transaction() as connection:
                repository_row = connection.execute(
                    "SELECT id FROM repositories WHERE source = ? AND external_id = ?",
                    (repository.source.value, repository.external_id),
                ).fetchone()
                if repository_row is None:
                    raise PersistenceError(
                        "repository "
                        f"{repository.source.value}:{repository.external_id} "
                        "is not stored"
                    )
                repository_id = int(repository_row["id"])
                succeeded = connection.execute(
                    """
                    SELECT 1 FROM repository_analysis_attempts
                    WHERE repository_id = ? AND provider = ? AND model = ?
                      AND content_kind = ?
                      AND status = ?
                    """,
                    (
                        repository_id,
                        provider,
                        model,
                        trace.kind.value,
                        AnalysisStatus.SUCCEEDED.value,
                    ),
                ).fetchone()
                if succeeded is not None:
                    raise PersistenceError(
                        "a successful analysis already exists for "
                        f"{repository.source.value}:{repository.external_id} with "
                        f"{provider}/{model}"
                    )
                number_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(attempt_number), 0) + 1 AS next_number
                    FROM repository_analysis_attempts
                    WHERE repository_id = ? AND provider = ? AND model = ?
                    """,
                    (repository_id, provider, model),
                ).fetchone()
                cursor = connection.execute(
                    """
                    INSERT INTO repository_analysis_attempts (
                        repository_id, provider, model, attempt_number,
                        status, content_kind, content_trace_json, started_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        repository_id,
                        provider,
                        model,
                        int(number_row["next_number"]),
                        AnalysisStatus.RUNNING.value,
                        trace.kind.value,
                        trace.model_dump_json(),
                        _timestamp(start_time),
                    ),
                )
                row = connection.execute(
                    REPOSITORY_ANALYSIS_SELECT + " WHERE a.id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"could not start repository analysis: {exc}"
            ) from exc
        return _repository_analysis_from_row(row)

    def succeed(
        self,
        attempt_id: int,
        result: RepositoryAnalysis,
        raw_output: str,
        *,
        completed_at: datetime | None = None,
    ) -> RepositoryAnalysisRecord:
        """Complete a running attempt and retain its raw model output."""

        if not raw_output.strip():
            raise ValueError("raw_output must not be empty")
        completion_time = _utc_now() if completed_at is None else completed_at
        if completion_time.tzinfo is None:
            raise ValueError("completed_at must include a timezone")

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE repository_analysis_attempts
                    SET status = ?, result_json = ?, raw_output = ?,
                        error = NULL, completed_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        AnalysisStatus.SUCCEEDED.value,
                        result.model_dump_json(),
                        raw_output,
                        _timestamp(completion_time),
                        attempt_id,
                        AnalysisStatus.RUNNING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PersistenceError(
                        "repository analysis attempt "
                        f"{attempt_id} is missing or already finished"
                    )
                row = connection.execute(
                    REPOSITORY_ANALYSIS_SELECT + " WHERE a.id = ?",
                    (attempt_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"could not complete repository analysis: {exc}"
            ) from exc
        return _repository_analysis_from_row(row)

    def fail(
        self,
        attempt_id: int,
        error: str,
        *,
        raw_output: str | None = None,
        completed_at: datetime | None = None,
    ) -> RepositoryAnalysisRecord:
        """Fail a running attempt while retaining available diagnostics."""

        error = error.strip()
        if not error:
            raise ValueError("error must not be empty")
        completion_time = _utc_now() if completed_at is None else completed_at
        if completion_time.tzinfo is None:
            raise ValueError("completed_at must include a timezone")

        try:
            with self._database.transaction() as connection:
                cursor = connection.execute(
                    """
                    UPDATE repository_analysis_attempts
                    SET status = ?, result_json = NULL, raw_output = ?,
                        error = ?, completed_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        AnalysisStatus.FAILED.value,
                        raw_output,
                        error,
                        _timestamp(completion_time),
                        attempt_id,
                        AnalysisStatus.RUNNING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PersistenceError(
                        "repository analysis attempt "
                        f"{attempt_id} is missing or already finished"
                    )
                row = connection.execute(
                    REPOSITORY_ANALYSIS_SELECT + " WHERE a.id = ?",
                    (attempt_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"could not fail repository analysis: {exc}"
            ) from exc
        return _repository_analysis_from_row(row)

    def list_attempts(
        self,
        source: RepositorySource,
        external_id: str,
    ) -> list[RepositoryAnalysisRecord]:
        """Return all attempts for a repository in creation order."""

        try:
            with self._database.transaction() as connection:
                rows = connection.execute(
                    REPOSITORY_ANALYSIS_SELECT
                    + """
                    WHERE r.source = ? AND r.external_id = ?
                    ORDER BY a.id
                    """,
                    (source.value, external_id),
                ).fetchall()
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"could not list repository analyses: {exc}"
            ) from exc
        return [_repository_analysis_from_row(row) for row in rows]
