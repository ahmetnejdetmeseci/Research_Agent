import pytest

from researchpilot.persistence import LocalRunLock, RunLockError


def test_local_run_lock_prevents_overlap_and_releases(tmp_path) -> None:
    database_path = tmp_path / "researchpilot.db"
    first = LocalRunLock(database_path)
    second = LocalRunLock(database_path)

    with first.acquire():
        with pytest.raises(RunLockError, match="already running"):
            with second.acquire():
                raise AssertionError("overlapping lock was acquired")

    with second.acquire():
        pass

    assert first.path.exists()


def test_local_run_lock_does_not_relabel_body_os_errors(tmp_path) -> None:
    lock = LocalRunLock(tmp_path / "researchpilot.db")

    with pytest.raises(OSError, match="body failure"):
        with lock.acquire():
            raise OSError("body failure")
