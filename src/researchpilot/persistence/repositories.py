"""SQLite implementations of ResearchPilot repository ports."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone

from pydantic import ValidationError

from researchpilot.domain import (
    AbstractAnalysis,
    AnalysisStatus,
    Paper,
    PaperAnalysisRecord,
    PaperSource,
    RunRecord,
    RunStatus,
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


def _run_from_row(row: sqlite3.Row) -> RunRecord:
    try:
        return RunRecord.model_validate(dict(row))
    except ValidationError as exc:
        raise PersistenceError(f"stored run {row['id']} is invalid: {exc}") from exc


def _analysis_from_row(row: sqlite3.Row) -> PaperAnalysisRecord:
    try:
        result = (
            None
            if row["result_json"] is None
            else AbstractAnalysis.model_validate_json(row["result_json"])
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
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )
    except ValidationError as exc:
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
           a.started_at,
           a.completed_at
    FROM paper_analysis_attempts AS a
    JOIN papers AS p ON p.id = a.paper_id
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
                      AND a.status = ?
                    """,
                    (
                        source.value,
                        external_id,
                        provider,
                        model,
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
        started_at: datetime | None = None,
    ) -> PaperAnalysisRecord:
        """Create a new running attempt without overwriting prior diagnostics."""

        provider = provider.strip()
        model = model.strip()
        if not provider or not model:
            raise ValueError("provider and model must not be empty")
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
                      AND status = ?
                    """,
                    (
                        paper_id,
                        provider,
                        model,
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
                        paper_id, provider, model, attempt_number, status, started_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        paper_id,
                        provider,
                        model,
                        int(number_row["next_number"]),
                        AnalysisStatus.RUNNING.value,
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
