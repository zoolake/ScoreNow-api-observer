from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scorenow_api_observer.reporting.analysis import ObservedEvent
from scorenow_api_observer.reporting.field_inspection import (
    FieldValueChange,
    UnsupportedArrayFieldPathError,
    analyze_field_inspection,
    validate_field_path,
)


def _observed_event(
    *,
    minute: int,
    event_data: dict,
    event_id: str = "123",
) -> ObservedEvent:
    captured_at = datetime(2026, 10, 20, 12, 0, tzinfo=UTC) + timedelta(minutes=minute)
    return ObservedEvent(
        event_id=event_id,
        captured_at=captured_at,
        raw_file_path=Path(f"data/raw/{minute}.json"),
        result_index=0,
        sport_code="baseball",
        event_data=event_data,
    )


def test_validate_field_path_parses_object_keys_and_rejects_arrays() -> None:
    assert validate_field_path("$") == ()
    assert validate_field_path("$.scores.10.home") == ("scores", "10", "home")

    with pytest.raises(UnsupportedArrayFieldPathError, match="배열"):
        validate_field_path("$.incidents[]")


def test_analyze_field_inspection_tracks_scalar_value_changes_and_missing() -> None:
    observed_events = [
        _observed_event(minute=0, event_data={"time_status": "0"}),
        _observed_event(minute=1, event_data={"time_status": "0"}),
        _observed_event(minute=2, event_data={"time_status": "1"}),
        _observed_event(minute=3, event_data={}),
        _observed_event(minute=4, event_data={"time_status": None}),
    ]

    result = analyze_field_inspection(
        observed_events=observed_events,
        resolution_failures=[],
        sport_code="baseball",
        path="$.time_status",
    )

    assert result.input_observation_count == 5
    assert result.analyzed_observation_count == 5
    assert result.field_failures == []
    assert len(result.events) == 1
    timeline = result.events[0].value_timelines[0]
    assert timeline.path == "$.time_status"
    assert [change.kind for change in timeline.changes] == [
        "initial",
        "changed",
        "disappeared",
        "appeared",
    ]
    assert timeline.changes[-1] == FieldValueChange(
        captured_at=datetime(2026, 10, 20, 12, 4, tzinfo=UTC),
        raw_file_path=Path("data/raw/4.json"),
        kind="appeared",
        previous_present=False,
        previous_value=None,
        current_present=True,
        current_value=None,
    )


def test_analyze_field_inspection_expands_nested_object_into_leaf_timelines() -> None:
    observed_events = [
        _observed_event(minute=0, event_data={"scores": {}}),
        _observed_event(
            minute=1,
            event_data={"scores": {"10": {"home": "0", "away": "0"}}},
        ),
        _observed_event(
            minute=2,
            event_data={"scores": {"10": {"home": "1", "away": "0"}}},
        ),
        _observed_event(minute=3, event_data={"scores": {}}),
    ]

    result = analyze_field_inspection(
        observed_events=observed_events,
        resolution_failures=[],
        sport_code="baseball",
        path="$.scores.10",
    )

    event = result.events[0]
    assert [change.kind for change in event.object_presence_changes] == [
        "initial",
        "appeared",
        "disappeared",
    ]
    assert [timeline.path for timeline in event.value_timelines] == [
        "$.scores.10.away",
        "$.scores.10.home",
    ]
    changes_by_path = {
        timeline.path: timeline.changes for timeline in event.value_timelines
    }
    assert [change.kind for change in changes_by_path["$.scores.10.home"]] == [
        "initial",
        "appeared",
        "changed",
        "disappeared",
    ]
    assert [change.current_value for change in changes_by_path["$.scores.10.home"]] == [
        None,
        "0",
        "1",
        None,
    ]
    assert [change.kind for change in changes_by_path["$.scores.10.away"]] == [
        "initial",
        "appeared",
        "disappeared",
    ]


def test_analyze_field_inspection_sorts_numeric_object_keys_naturally() -> None:
    result = analyze_field_inspection(
        observed_events=[
            _observed_event(
                minute=0,
                event_data={
                    "scores": {
                        "10": {"home": "0"},
                        "2": {"home": "1"},
                    }
                },
            )
        ],
        resolution_failures=[],
        sport_code="baseball",
        path="$.scores",
    )

    assert [timeline.path for timeline in result.events[0].value_timelines] == [
        "$.scores.2.home",
        "$.scores.10.home",
    ]


def test_analyze_field_inspection_excludes_array_observation_and_continues() -> None:
    result = analyze_field_inspection(
        observed_events=[
            _observed_event(
                minute=0,
                event_data={"stats": {"state": "ready"}},
            ),
            _observed_event(
                minute=1,
                event_data={"stats": {"state": "ready", "items": [1, 2]}},
            ),
            _observed_event(
                minute=2,
                event_data={"stats": {"state": "live"}},
            ),
        ],
        resolution_failures=[],
        sport_code="baseball",
        path="$.stats",
    )

    assert result.input_observation_count == 3
    assert result.analyzed_observation_count == 2
    assert len(result.field_failures) == 1
    assert "$.stats.items에서 배열" in result.field_failures[0].error_message
    state_timeline = result.events[0].value_timelines[0]
    assert state_timeline.path == "$.stats.state"
    assert [change.current_value for change in state_timeline.changes] == [
        "ready",
        "live",
    ]


def test_analyze_field_inspection_filters_sport_and_event_id() -> None:
    selected = _observed_event(minute=0, event_data={"status": "selected"})
    another_event = _observed_event(
        minute=1,
        event_data={"status": "other"},
        event_id="456",
    )
    another_sport = ObservedEvent(
        event_id="123",
        captured_at=datetime(2026, 10, 20, 12, 2, tzinfo=UTC),
        raw_file_path=Path("data/raw/football.json"),
        result_index=0,
        sport_code="football",
        event_data={"status": "football"},
    )

    result = analyze_field_inspection(
        observed_events=[another_event, another_sport, selected],
        resolution_failures=[],
        sport_code="baseball",
        event_id="123",
        path="$.status",
    )

    assert result.input_observation_count == 1
    assert result.input_event_count == 1
    assert result.observed_event_count == 1
    assert result.unobserved_event_count == 0
    assert [event.event_id for event in result.events] == ["123"]
    assert result.events[0].value_timelines[0].changes[0].current_value == "selected"


def test_analyze_field_inspection_omits_events_where_path_never_appears() -> None:
    result = analyze_field_inspection(
        observed_events=[
            _observed_event(minute=0, event_id="never", event_data={}),
            _observed_event(minute=1, event_id="never", event_data={}),
            _observed_event(minute=0, event_id="observed", event_data={}),
            _observed_event(
                minute=1,
                event_id="observed",
                event_data={"scores": {"10": {"home": "1"}}},
            ),
        ],
        resolution_failures=[],
        sport_code="baseball",
        path="$.scores.10",
    )

    assert result.input_observation_count == 4
    assert result.analyzed_observation_count == 4
    assert result.input_event_count == 2
    assert result.observed_event_count == 1
    assert result.unobserved_event_count == 1
    assert [event.event_id for event in result.events] == ["observed"]
    assert [change.kind for change in result.events[0].object_presence_changes] == [
        "initial",
        "appeared",
    ]


def test_analyze_field_inspection_reports_explicit_event_without_requested_path() -> (
    None
):
    result = analyze_field_inspection(
        observed_events=[
            _observed_event(minute=0, event_data={"scores": {}}),
            _observed_event(minute=1, event_data={"scores": {}}),
        ],
        resolution_failures=[],
        sport_code="baseball",
        event_id="123",
        path="$.scores.10",
    )

    assert result.input_event_count == 1
    assert result.events == []
    assert result.unobserved_event_count == 1
