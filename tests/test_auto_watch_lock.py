from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scorenow_api_observer.auto_watch.lock import (
    AutoWatchAlreadyRunningError,
    AutoWatchLockMetadata,
    acquire_auto_watch_process_lock,
)


def test_lock_rejects_second_owner_and_can_be_reacquired_after_release(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "auto-watch.lock"
    started_at = datetime(2026, 11, 17, 1, tzinfo=UTC)
    first_lock = acquire_auto_watch_process_lock(
        now=started_at,
        process_id=1001,
        host_name="first-host",
        file_path=lock_path,
    )

    with pytest.raises(AutoWatchAlreadyRunningError) as error_info:
        acquire_auto_watch_process_lock(
            now=started_at + timedelta(minutes=1),
            process_id=1002,
            host_name="second-host",
            file_path=lock_path,
        )

    error = error_info.value
    assert error.file_path == lock_path
    assert error.metadata is not None
    assert error.metadata.process_id == 1001
    assert error.metadata.started_at == started_at
    assert error.metadata.host_name == "first-host"

    first_lock.release()
    assert lock_path.exists()

    second_lock = acquire_auto_watch_process_lock(
        now=started_at + timedelta(minutes=2),
        process_id=1002,
        host_name="second-host",
        file_path=lock_path,
    )
    second_lock.release()

    stored_metadata = AutoWatchLockMetadata.model_validate_json(
        lock_path.read_text(encoding="utf-8")
    )
    assert stored_metadata.process_id == 1002
    assert stored_metadata.host_name == "second-host"


def test_lock_context_releases_after_exception(tmp_path: Path) -> None:
    lock_path = tmp_path / "auto-watch.lock"
    now = datetime(2026, 11, 17, 1, tzinfo=UTC)

    with (
        pytest.raises(RuntimeError, match="test failure"),
        acquire_auto_watch_process_lock(
            now=now,
            process_id=1001,
            host_name="test-host",
            file_path=lock_path,
        ),
    ):
        raise RuntimeError("test failure")

    reacquired_lock = acquire_auto_watch_process_lock(
        now=now + timedelta(seconds=1),
        process_id=1002,
        host_name="test-host",
        file_path=lock_path,
    )
    reacquired_lock.release()
