from datetime import UTC, datetime, timedelta

from scorenow_api_observer.auto_watch.config import load_auto_watch_config
from scorenow_api_observer.auto_watch.models import (
    AutoWatchActiveEvent,
    AutoWatchState,
)
from scorenow_api_observer.auto_watch.policy import (
    apply_auto_watch_time_status,
    find_due_auto_watch_events,
)


def _event(*, now: datetime) -> AutoWatchActiveEvent:
    return AutoWatchActiveEvent(
        event_id="123",
        sport_code="baseball",
        league_id="349",
        league_label="kbo",
        scheduled_at_utc=now + timedelta(minutes=10),
        added_at=now,
    )


def test_temporarily_stopped_statuses_share_timer_and_inplay_resets_it() -> None:
    config = load_auto_watch_config()
    now = datetime(2026, 11, 17, 1, tzinfo=UTC)
    event = _event(now=now)

    first = apply_auto_watch_time_status(
        event=event,
        time_status=7,
        observed_at=now,
        capture_metadata_file_path="first.json",
        config=config,
    )
    second = apply_auto_watch_time_status(
        event=event,
        time_status="10",
        observed_at=now + timedelta(minutes=30),
        capture_metadata_file_path="second.json",
        config=config,
    )

    assert first.current_mode == "temporarily_stopped"
    assert first.deadline == now + timedelta(hours=2)
    assert not second.mode_changed
    assert second.deadline == now + timedelta(hours=2)
    assert event.last_time_status == 10

    inplay = apply_auto_watch_time_status(
        event=event,
        time_status=1,
        observed_at=now + timedelta(minutes=31),
        capture_metadata_file_path="third.json",
        config=config,
    )

    assert inplay.current_mode == "inplay"
    assert inplay.deadline is None
    assert event.status_policy_group is None
    assert event.status_policy_started_at is None


def test_waiting_to_start_status_stops_two_hours_after_scheduled_time() -> None:
    config = load_auto_watch_config()
    now = datetime(2026, 11, 17, 1, tzinfo=UTC)
    event = _event(now=now)
    apply_auto_watch_time_status(
        event=event,
        time_status=0,
        observed_at=now,
        capture_metadata_file_path="metadata.json",
        config=config,
    )
    state = AutoWatchState(updated_at=now, active_events=[event])

    assert (
        find_due_auto_watch_events(
            state=state,
            now=event.scheduled_at_utc + timedelta(minutes=119),
            config=config,
        )
        == []
    )

    due = find_due_auto_watch_events(
        state=state,
        now=event.scheduled_at_utc + timedelta(minutes=120),
        config=config,
    )

    assert len(due) == 1
    assert due[0].requires_exception_record
    assert due[0].stop_time_status == 0


def test_ended_status_is_normal_completion_after_fifteen_minutes() -> None:
    config = load_auto_watch_config()
    now = datetime(2026, 11, 17, 1, tzinfo=UTC)
    event = _event(now=now)
    apply_auto_watch_time_status(
        event=event,
        time_status=3,
        observed_at=now,
        capture_metadata_file_path="metadata.json",
        config=config,
    )
    state = AutoWatchState(updated_at=now, active_events=[event])

    due = find_due_auto_watch_events(
        state=state,
        now=now + timedelta(minutes=15),
        config=config,
    )

    assert len(due) == 1
    assert not due[0].requires_exception_record
    assert due[0].stop_time_status == 3


def test_unknown_status_has_one_hour_limit() -> None:
    config = load_auto_watch_config()
    now = datetime(2026, 11, 17, 1, tzinfo=UTC)
    event = _event(now=now)
    update = apply_auto_watch_time_status(
        event=event,
        time_status="unexpected",
        observed_at=now,
        capture_metadata_file_path="metadata.json",
        config=config,
    )
    state = AutoWatchState(updated_at=now, active_events=[event])

    assert update.current_mode == "unknown"
    assert update.time_status is None
    assert update.deadline == now + timedelta(hours=1)
    assert (
        len(
            find_due_auto_watch_events(
                state=state,
                now=now + timedelta(hours=1),
                config=config,
            )
        )
        == 1
    )
