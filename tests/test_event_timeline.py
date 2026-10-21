from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scorenow_api_observer.reporting.event_timeline import analyze_event_timeline
from scorenow_api_observer.reporting.models import ObservedEvent


def _observed_event(
    *,
    minute: int,
    event_data: dict,
    event_id: str = "123",
    sport_code: str | None = "baseball",
) -> ObservedEvent:
    captured_at = datetime(2026, 10, 20, 12, 0, tzinfo=UTC) + timedelta(minutes=minute)
    return ObservedEvent(
        event_id=event_id,
        captured_at=captured_at,
        raw_file_path=Path(f"data/raw/{minute}.json"),
        result_index=0,
        sport_code=sport_code,
        event_data=event_data,
    )


def test_analyze_event_timeline_expands_objects_and_keeps_every_observation() -> None:
    observed_events = [
        _observed_event(
            minute=2,
            event_data={
                "time_status": 1,
                "scores": {"10": {"home": "1", "away": "0"}},
            },
        ),
        _observed_event(
            minute=0,
            event_data={
                "time_status": 0,
                "scores": {"9": {"home": "0", "away": "0"}},
            },
        ),
        _observed_event(
            minute=1,
            sport_code=None,
            event_data={
                "time_status": 0,
                "scores": {"9": {"home": "0", "away": "0"}},
            },
        ),
        _observed_event(
            minute=3,
            event_data={"time_status": 1, "scores": []},
        ),
        _observed_event(
            minute=4,
            event_data={
                "time_status": 1,
                "scores": {"10": {"home": "1", "away": "0"}},
            },
        ),
        _observed_event(
            minute=0,
            event_id="other",
            sport_code="football",
            event_data={"time_status": 1},
        ),
    ]

    result = analyze_event_timeline(
        observed_events=observed_events,
        resolution_failures=[],
        event_id="123",
        paths_by_sport_code={
            "baseball": ("$.time_status", "$.scores"),
        },
    )

    assert result.sport_code == "baseball"
    assert result.input_observation_count == 5
    assert result.analyzed_observation_count == 4
    assert result.failed_observation_count == 1
    assert result.changed_observation_count == 1
    assert [row.kind for row in result.rows] == [
        "initial",
        "unchanged",
        "changed",
        "failed",
        "unchanged",
    ]
    assert [state.path for state in result.rows[0].initial_states] == [
        "$.time_status",
        "$.scores",
        "$.scores.9.away",
        "$.scores.9.home",
    ]
    assert [change.path for change in result.rows[2].changes] == [
        "$.time_status",
        "$.scores.9.away",
        "$.scores.9.home",
        "$.scores.10.away",
        "$.scores.10.home",
    ]
    assert result.rows[3].failures[0].path == "$.scores"
    assert "배열" in result.rows[3].failures[0].error_message


def test_analyze_event_timeline_distinguishes_missing_null_and_value_type() -> None:
    result = analyze_event_timeline(
        observed_events=[
            _observed_event(minute=0, event_data={}),
            _observed_event(minute=1, event_data={"time_status": None}),
            _observed_event(minute=2, event_data={"time_status": 1}),
            _observed_event(minute=3, event_data={"time_status": "1"}),
        ],
        resolution_failures=[],
        event_id="123",
        paths_by_sport_code={"baseball": ("$.time_status",)},
    )

    assert [row.kind for row in result.rows] == [
        "initial",
        "changed",
        "changed",
        "changed",
    ]
    assert result.rows[1].changes[0].previous.kind == "missing"
    assert result.rows[1].changes[0].current.value is None
    assert result.rows[2].changes[0].current.value == 1
    assert result.rows[3].changes[0].current.value == "1"


@pytest.mark.parametrize(
    ("observed_events", "expected_message"),
    [
        ([], "EventObservation이 없습니다"),
        (
            [_observed_event(minute=0, sport_code=None, event_data={})],
            "종목을 분류할 수 있는",
        ),
        (
            [
                _observed_event(minute=0, sport_code="baseball", event_data={}),
                _observed_event(minute=1, sport_code="football", event_data={}),
            ],
            "서로 다른 종목",
        ),
    ],
)
def test_analyze_event_timeline_rejects_ambiguous_selection(
    observed_events: list[ObservedEvent],
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        analyze_event_timeline(
            observed_events=observed_events,
            resolution_failures=[],
            event_id="123",
            paths_by_sport_code={"baseball": ("$.time_status",)},
        )


def test_analyze_event_timeline_requires_fields_for_inferred_sport() -> None:
    with pytest.raises(ValueError, match="타임라인 필드 설정이 없습니다"):
        analyze_event_timeline(
            observed_events=[_observed_event(minute=0, event_data={})],
            resolution_failures=[],
            event_id="123",
            paths_by_sport_code={"football": ("$.time_status",)},
        )
