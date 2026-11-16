from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scorenow_api_observer.auto_watch.exceptions import (
    AutoWatchExceptionRecord,
    build_auto_watch_exception_path,
    build_auto_watch_exception_record,
    save_auto_watch_exception_record,
)
from scorenow_api_observer.auto_watch.models import AutoWatchActiveEvent

KST = ZoneInfo("Asia/Seoul")


def test_auto_watch_exception_uses_utc_path_and_includes_kst_schedule(
    tmp_path: Path,
) -> None:
    scheduled_at = datetime(2026, 11, 15, 10, tzinfo=UTC)
    stopped_at = datetime(2026, 11, 15, 15, 30, 0, 123456, tzinfo=UTC)
    event = AutoWatchActiveEvent(
        event_id="12345678",
        sport_code="baseball",
        league_id="349",
        league_label="kbo",
        scheduled_at_utc=scheduled_at,
        added_at=datetime(2026, 11, 15, 9, 50, tzinfo=UTC),
        last_time_status=10,
        status_policy_group="temporarily_stopped",
        status_policy_started_at=datetime(2026, 11, 15, 13, 30, tzinfo=UTC),
        last_capture_metadata_path="data/metadata/event-view/latest.json",
        stop_decided_at=stopped_at,
    )
    record = build_auto_watch_exception_record(
        event=event,
        stopped_at=stopped_at,
    )

    expected_path = (
        tmp_path
        / "time-status-10"
        / "2026-11-15"
        / "20261115T153000123456Z_12345678.json"
    )
    assert (
        build_auto_watch_exception_path(
            record,
            base_directory=tmp_path,
        )
        == expected_path
    )
    assert record.scheduled_at_utc == scheduled_at
    assert record.scheduled_at_kst == scheduled_at.astimezone(KST)

    first_path = save_auto_watch_exception_record(record, base_directory=tmp_path)
    second_path = save_auto_watch_exception_record(record, base_directory=tmp_path)

    assert first_path == second_path == expected_path
    assert len(list(tmp_path.rglob("*.json"))) == 1
    loaded = AutoWatchExceptionRecord.model_validate_json(
        expected_path.read_text(encoding="utf-8")
    )
    assert loaded.stop_time_status == 10
    assert loaded.scheduled_at_kst.utcoffset() == KST.utcoffset(scheduled_at)


def test_unknown_status_uses_unknown_directory(tmp_path: Path) -> None:
    stopped_at = datetime(2026, 11, 15, 15, 30, tzinfo=UTC)
    record = AutoWatchExceptionRecord(
        event_id="123",
        sport_code="football",
        league_id="94",
        league_label="premier-league",
        scheduled_at_utc=stopped_at,
        scheduled_at_kst=stopped_at.astimezone(KST),
        observation_started_at=stopped_at,
        stopped_at=stopped_at,
        stop_time_status=None,
        last_capture_metadata_path=None,
    )

    path = build_auto_watch_exception_path(record, base_directory=tmp_path)

    assert path.parent.parent.name == "time-status-unknown"
