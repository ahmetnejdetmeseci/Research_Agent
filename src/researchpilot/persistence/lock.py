"""Process-level lock for overlapping scheduled pipeline invocations."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO


class RunLockError(Exception):
    """A pipeline lock cannot be acquired safely."""


class LocalRunLock:
    """Hold a non-blocking advisory lock for the lifetime of one pipeline run."""

    def __init__(self, database_path: str | Path) -> None:
        database = Path(database_path)
        self.path = database.with_name(f"{database.name}.run.lock")

    @contextmanager
    def acquire(self) -> Iterator[None]:
        """Acquire the lock or fail immediately when another run owns it."""

        handle: TextIO | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if handle is not None:
                handle.close()
            raise RunLockError(
                "another ResearchPilot pipeline is already running for "
                f"database {self.path.name.removesuffix('.run.lock')}"
            ) from exc
        except OSError as exc:
            if handle is not None:
                handle.close()
            raise RunLockError(
                f"could not acquire pipeline lock {self.path}: {exc}"
            ) from exc
        assert handle is not None
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
