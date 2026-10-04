import sqlite3
from pathlib import Path

import pytest

from researchpilot.persistence import Database, resolve_database_path
from researchpilot.persistence.database import DATABASE_PATH_ENV, load_migrations


def test_bundled_migrations_are_consecutively_numbered() -> None:
    migrations = load_migrations()

    assert [(migration.version, migration.name) for migration in migrations] == [
        (1, "initial"),
        (2, "paper_analysis_attempts"),
    ]


def test_missing_database_status_does_not_create_file(tmp_path) -> None:
    path = tmp_path / "researchpilot.db"

    status = Database(path).status()

    assert status.exists is False
    assert status.initialized is False
    assert status.current_version == 0
    assert status.latest_version == 2
    assert path.exists() is False


def test_initialization_is_idempotent(tmp_path) -> None:
    database = Database(tmp_path / "nested" / "researchpilot.db")

    first_applied = database.initialize()
    second_applied = database.initialize()
    status = database.status()

    assert [migration.version for migration in first_applied] == [1, 2]
    assert second_applied == ()
    assert status.initialized is True
    assert status.current_version == status.latest_version == 2
    assert status.paper_count == 0
    assert status.run_count == 0
    assert status.analysis_attempt_count == 0


def test_failed_transaction_rolls_back(tmp_path) -> None:
    database = Database(tmp_path / "researchpilot.db")
    database.initialize()

    with pytest.raises(RuntimeError, match="simulated failure"):
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO runs(command, status, started_at)
                VALUES ('test', 'running', '2026-10-03T12:00:00+00:00')
                """
            )
            raise RuntimeError("simulated failure")

    assert database.status().run_count == 0


def test_database_path_precedence() -> None:
    environment = {DATABASE_PATH_ENV: "environment.db"}

    assert resolve_database_path("explicit.db", environment) == Path("explicit.db")
    assert resolve_database_path(None, environment) == Path("environment.db")
    assert resolve_database_path(None, {}) == Path("researchpilot.db")


def test_existing_version_one_database_is_upgraded(tmp_path) -> None:
    path = tmp_path / "researchpilot.db"
    first = load_migrations()[0]
    connection = sqlite3.connect(path)
    connection.executescript(first.sql)
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (1, 'initial', ?)",
        ("2026-10-03T12:00:00+00:00",),
    )
    connection.commit()
    connection.close()

    applied = Database(path).initialize()

    assert [(migration.version, migration.name) for migration in applied] == [
        (2, "paper_analysis_attempts")
    ]
    assert Database(path).status().initialized is True
