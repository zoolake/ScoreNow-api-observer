from datetime import UTC, datetime, timedelta

import pytest

from scorenow_api_observer.event_view.watching import (
    POST_FINISH_COLLECTION_PERIOD,
    EventWatchState,
    apply_event_time_status,
    find_completed_event_ids,
    normalize_time_status,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3, 3),
        ("3", 3),
        (" 1 ", 1),
        (None, None),
        (True, None),
        ("invalid", None),
        (3.0, None),
    ],
)
def test_normalize_time_status(value: object, expected: int | None) -> None:
    assert normalize_time_status(value) == expected


def test_apply_event_time_status_preserves_first_finish_detection_time() -> None:
    first_observed_at = datetime(2026, 10, 21, 1, 0, tzinfo=UTC)
    state = EventWatchState("A")

    first_transition = apply_event_time_status(
        state=state,
        time_status="3",
        observed_at=first_observed_at,
    )
    second_transition = apply_event_time_status(
        state=state,
        time_status=3,
        observed_at=first_observed_at + timedelta(minutes=1),
    )

    assert first_transition is not None
    assert first_transition.kind == "finish_detected"
    assert second_transition is None
    assert state.finished_detected_at == first_observed_at


def test_apply_event_time_status_cancels_finish_on_progress_status() -> None:
    state = EventWatchState(
        "A",
        finished_detected_at=datetime(2026, 10, 21, 1, 0, tzinfo=UTC),
    )

    transition = apply_event_time_status(
        state=state,
        time_status="1",
        observed_at=datetime(2026, 10, 21, 1, 1, tzinfo=UTC),
    )

    assert transition is not None
    assert transition.kind == "finish_cancelled"
    assert state.finished_detected_at is None


def test_apply_event_time_status_ignores_unrecognized_value() -> None:
    finished_detected_at = datetime(2026, 10, 21, 1, 0, tzinfo=UTC)
    state = EventWatchState("A", finished_detected_at=finished_detected_at)

    transition = apply_event_time_status(
        state=state,
        time_status=None,
        observed_at=finished_detected_at + timedelta(minutes=1),
    )

    assert transition is None
    assert state.finished_detected_at == finished_detected_at


def test_find_completed_event_ids_uses_post_finish_period_per_event() -> None:
    now = datetime(2026, 10, 21, 1, 15, tzinfo=UTC)
    states = [
        EventWatchState("A", now - POST_FINISH_COLLECTION_PERIOD),
        EventWatchState("B", now - timedelta(minutes=14)),
        EventWatchState("C"),
    ]

    result = find_completed_event_ids(states=states, now=now)

    assert result == ["A"]
