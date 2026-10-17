from datetime import UTC, datetime

import pytest

from scorenow_api_observer.upcoming.response import (
    InvalidUpcomingResponseShapeError,
    analyze_upcoming_response,
)


def _event(
    event_id: str,
    *,
    sport_id: str = "16",
    league_id: str = "225",
    scheduled_time: object = "0",
) -> dict[str, object]:
    return {
        "id": event_id,
        "sport_id": sport_id,
        "time": scheduled_time,
        "time_status": "0",
        "league": {"id": league_id, "name": "MLB", "cc": "us"},
        "home": {"id": "HOME", "name": "Home Team"},
        "away": {"id": "AWAY", "name": "Away Team"},
    }


def test_analyze_upcoming_response_extracts_discovery_event() -> None:
    result = analyze_upcoming_response(
        response_json={"results": [_event("A")], "pager": {"total": 1}},
        requested_sport_id="16",
        requested_league_id="225",
        sport_code="baseball",
    )

    assert result.returned_event_ids == ["A"]
    assert result.issues == []
    assert len(result.observable_events) == 1
    event = result.observable_events[0]
    assert event.event_id == "A"
    assert event.scheduled_at_utc == datetime(1970, 1, 1, tzinfo=UTC)
    assert event.scheduled_at_kst.isoformat() == "1970-01-01T09:00:00+09:00"
    assert event.league.country_code == "us"
    assert event.home.name == "Home Team"
    assert event.result_index == 0


def test_analyze_upcoming_response_preserves_returned_order_and_reports_issues() -> (
    None
):
    result = analyze_upcoming_response(
        response_json={
            "results": [
                "not-an-object",
                {"sport_id": "16"},
                _event("DUPLICATE"),
                _event("DUPLICATE"),
                _event("WRONG", sport_id="1", league_id="349"),
                _event("BAD_TIME", scheduled_time="unknown"),
            ],
            "pager": {"total": "10"},
        },
        requested_sport_id="16",
        requested_league_id="225",
        sport_code="baseball",
    )

    assert result.returned_event_ids == [
        "DUPLICATE",
        "DUPLICATE",
        "WRONG",
        "BAD_TIME",
    ]
    assert result.observable_events == []
    assert [issue.code for issue in result.issues] == [
        "invalid_event_shape",
        "missing_event_id",
        "duplicate_event_id",
        "unexpected_sport_id",
        "unexpected_league_id",
        "invalid_scheduled_time",
        "pagination_required",
    ]
    duplicate_issue = result.issues[2]
    assert duplicate_issue.event_id == "DUPLICATE"
    assert duplicate_issue.result_indices == [2, 3]
    pagination_issue = result.issues[-1]
    assert pagination_issue.expected_value == 6
    assert pagination_issue.actual_value == 10


@pytest.mark.parametrize(
    "response_json",
    [[], {}, {"results": {}}, {"results": None}],
)
def test_analyze_upcoming_response_rejects_invalid_top_level_shape(
    response_json: object,
) -> None:
    with pytest.raises(InvalidUpcomingResponseShapeError):
        analyze_upcoming_response(
            response_json=response_json,
            requested_sport_id="16",
            requested_league_id="225",
            sport_code="baseball",
        )
