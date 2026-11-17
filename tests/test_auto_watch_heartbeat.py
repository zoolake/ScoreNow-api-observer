from datetime import UTC, datetime, timedelta
from pathlib import Path

from scorenow_api_observer.auto_watch.heartbeat import (
    finish_auto_watch_heartbeat,
    load_auto_watch_heartbeat,
    new_auto_watch_heartbeat,
    save_auto_watch_heartbeat,
    touch_auto_watch_heartbeat,
)


def test_auto_watch_heartbeat_persists_cycle_and_stop_state(tmp_path: Path) -> None:
    started_at = datetime(2026, 11, 17, 1, tzinfo=UTC)
    heartbeat = new_auto_watch_heartbeat(
        now=started_at,
        interval_seconds=300,
        process_id=1234,
    )
    touch_auto_watch_heartbeat(
        heartbeat,
        now=started_at + timedelta(minutes=5),
    )
    finish_auto_watch_heartbeat(
        heartbeat,
        now=started_at + timedelta(minutes=6),
        failed=False,
    )

    heartbeat_path = tmp_path / "heartbeat.json"
    save_auto_watch_heartbeat(heartbeat, heartbeat_path)
    loaded = load_auto_watch_heartbeat(heartbeat_path)

    assert loaded is not None
    assert loaded.status == "stopped"
    assert loaded.process_started_at == started_at
    assert loaded.last_cycle_at == started_at + timedelta(minutes=5)
    assert loaded.stopped_at == started_at + timedelta(minutes=6)


def test_auto_watch_heartbeat_persists_failure_message(tmp_path: Path) -> None:
    now = datetime(2026, 11, 17, 1, tzinfo=UTC)
    heartbeat = new_auto_watch_heartbeat(
        now=now,
        interval_seconds=30,
        process_id=1234,
    )
    finish_auto_watch_heartbeat(
        heartbeat,
        now=now + timedelta(minutes=1),
        failed=True,
        failure_message="상태 저장 실패",
    )

    heartbeat_path = tmp_path / "heartbeat.json"
    save_auto_watch_heartbeat(heartbeat, heartbeat_path)
    loaded = load_auto_watch_heartbeat(heartbeat_path)

    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.failure_message == "상태 저장 실패"
