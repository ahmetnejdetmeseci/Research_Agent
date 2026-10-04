"""SQLite connection, transaction, and migration management."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

DATABASE_PATH_ENV = "RESEARCHPILOT_DATABASE"
DEFAULT_DATABASE_PATH = Path("researchpilot.db")
MIGRATION_FILENAME = re.compile(r"^(?P<version>\d{3})_(?P<name>[a-z0-9_]+)\.sql$")
MIGRATIONS_PACKAGE = "researchpilot.persistence.migrations"


class PersistenceError(Exception):
    """A local persistence problem that can be shown to a user."""


@dataclass(frozen=True)
class Migration:
    """One ordered SQL schema migration bundled with the package."""

    version: int
    name: str
    sql: str


@dataclass(frozen=True)
class DatabaseStatus:
    """A read-only summary of a ResearchPilot database."""

    path: Path
    exists: bool
    initialized: bool
    current_version: int
    latest_version: int
    paper_count: int
    run_count: int
    analysis_attempt_count: int

    @property
    def pending_migrations(self) -> int:
        """Return the number of bundled migrations not yet applied."""

        return max(0, self.latest_version - self.current_version)


def resolve_database_path(
    explicit_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve database path with CLI, environment, then default precedence."""

    if explicit_path is not None:
        return Path(explicit_path).expanduser()

    environment = os.environ if environ is None else environ
    if configured_path := environment.get(DATABASE_PATH_ENV):
        return Path(configured_path).expanduser()

    return DEFAULT_DATABASE_PATH


def load_migrations() -> tuple[Migration, ...]:
    """Load and validate numbered SQL migrations from package resources."""

    migrations: list[Migration] = []
    for resource in files(MIGRATIONS_PACKAGE).iterdir():
        match = MIGRATION_FILENAME.fullmatch(resource.name)
        if match is None:
            continue
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                sql=resource.read_text(encoding="utf-8"),
            )
        )

    migrations.sort(key=lambda migration: migration.version)
    versions = [migration.version for migration in migrations]
    if not migrations:
        raise PersistenceError("no database migrations are bundled")
    if len(versions) != len(set(versions)):
        raise PersistenceError("database migration versions must be unique")
    if versions != list(range(1, len(versions) + 1)):
        raise PersistenceError("database migrations must be consecutively numbered")
    return tuple(migrations)


def _sql_statements(script: str) -> Iterator[str]:
    """Yield complete SQLite statements without losing transaction control."""

    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        raise PersistenceError("database migration contains incomplete SQL")


class Database:
    """Own SQLite connections, atomic transactions, and schema migrations."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits on success and rolls back on error."""

        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> tuple[Migration, ...]:
        """Create the database and atomically apply every pending migration."""

        migrations = load_migrations()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.transaction() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                            DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    )
                    """
                )

            applied: list[Migration] = []
            for migration in migrations:
                with self.transaction() as connection:
                    existing = connection.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = ?",
                        (migration.version,),
                    ).fetchone()
                    if existing is not None:
                        continue
                    for statement in _sql_statements(migration.sql):
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                        (migration.version, migration.name),
                    )
                    applied.append(migration)
            return tuple(applied)
        except (OSError, sqlite3.Error) as exc:
            raise PersistenceError(
                f"could not initialize database {self.path}: {exc}"
            ) from exc

    def status(self) -> DatabaseStatus:
        """Inspect schema and row counts without creating a missing database."""

        migrations = load_migrations()
        latest_version = migrations[-1].version
        if not self.path.exists():
            return DatabaseStatus(
                path=self.path,
                exists=False,
                initialized=False,
                current_version=0,
                latest_version=latest_version,
                paper_count=0,
                run_count=0,
                analysis_attempt_count=0,
            )

        try:
            with self.transaction() as connection:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if "schema_migrations" not in tables:
                    current_version = 0
                else:
                    row = connection.execute(
                        "SELECT COALESCE(MAX(version), 0) AS version "
                        "FROM schema_migrations"
                    ).fetchone()
                    current_version = int(row["version"])

                paper_count = self._table_count(connection, tables, "papers")
                run_count = self._table_count(connection, tables, "runs")
                analysis_attempt_count = self._table_count(
                    connection,
                    tables,
                    "paper_analysis_attempts",
                )
                initialized = (
                    current_version == latest_version
                    and {
                        "papers",
                        "runs",
                        "paper_analysis_attempts",
                    }.issubset(tables)
                )
        except sqlite3.Error as exc:
            raise PersistenceError(
                f"could not inspect database {self.path}: {exc}"
            ) from exc

        return DatabaseStatus(
            path=self.path,
            exists=True,
            initialized=initialized,
            current_version=current_version,
            latest_version=latest_version,
            paper_count=paper_count,
            run_count=run_count,
            analysis_attempt_count=analysis_attempt_count,
        )

    @staticmethod
    def _table_count(
        connection: sqlite3.Connection,
        tables: set[str],
        table: str,
    ) -> int:
        if table not in tables:
            return 0
        row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"])
