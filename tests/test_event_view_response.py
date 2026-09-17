from typing import Any

import pytest

from scorenow_api_observer.event_view_response import (
    EventViewResponseIssue,
    InvalidEventViewResponseShapeError,
    ObservableEvent,
    analyze_event_view_response,
)


def _response(*results: dict[str, Any]) -> dict[str, Any]:
    return {"success": 1, "results": list(results)}


def _issue_values(
    analysis_issues: list[EventViewResponseIssue],
) -> list[tuple[str, str | None, list[int]]]:
    return [
        (issue.code, issue.event_id, issue.result_indices) for issue in analysis_issues
    ]


@pytest.mark.parametrize(
    "response_json",
    [
        [],
        {},
        {"results": None},
        {"results": ["not-an-object"]},
    ],
)
def test_analyze_event_view_response_rejects_invalid_response_shape(
    response_json: Any,
) -> None:
    with pytest.raises(InvalidEventViewResponseShapeError):
        analyze_event_view_response(
            requested_event_ids=["A"],
            response_json=response_json,
        )


def test_analyze_event_view_response_with_requested_events() -> None:
    result = analyze_event_view_response(
        requested_event_ids=["A", "B"],
        response_json=_response({"id": "A"}, {"id": "B"}),
    )

    assert result.returned_event_ids == ["A", "B"]
    assert result.observable_events == [
        ObservableEvent(event_id="A", result_index=0),
        ObservableEvent(event_id="B", result_index=1),
    ]
    assert result.issues == []


def test_analyze_event_view_response_with_missing_requested_event() -> None:
    result = analyze_event_view_response(
        requested_event_ids=["A", "B"],
        response_json=_response({"id": "A"}),
    )

    assert result.returned_event_ids == ["A"]
    assert result.observable_events == [ObservableEvent(event_id="A", result_index=0)]
    assert _issue_values(result.issues) == [
        ("missing_requested_event", "B", []),
    ]


def test_analyze_event_view_response_with_unexpected_event() -> None:
    result = analyze_event_view_response(
        requested_event_ids=["A", "B"],
        response_json=_response({"id": "A"}, {"id": "C"}),
    )

    assert result.returned_event_ids == ["A", "C"]
    assert result.observable_events == [
        ObservableEvent(event_id="A", result_index=0),
        ObservableEvent(event_id="C", result_index=1),
    ]
    assert _issue_values(result.issues) == [
        ("missing_requested_event", "B", []),
        ("unexpected_event_id", "C", [1]),
    ]


def test_analyze_event_view_response_excludes_duplicate_event() -> None:
    result = analyze_event_view_response(
        requested_event_ids=["A", "B"],
        response_json=_response({"id": "A"}, {"id": "A"}, {"id": "B"}),
    )

    assert result.returned_event_ids == ["A", "A", "B"]
    assert result.observable_events == [ObservableEvent(event_id="B", result_index=2)]
    assert _issue_values(result.issues) == [
        ("duplicate_event_id", "A", [0, 1]),
    ]


def test_analyze_event_view_response_with_missing_event_id() -> None:
    result = analyze_event_view_response(
        requested_event_ids=["A"],
        response_json=_response({"sport_id": "3"}, {"id": "A"}),
    )

    assert result.returned_event_ids == ["A"]
    assert result.observable_events == [ObservableEvent(event_id="A", result_index=1)]
    assert _issue_values(result.issues) == [
        ("missing_event_id", None, [0]),
    ]


def test_analyze_event_view_response_sorts_classified_issue_event_ids() -> None:
    result = analyze_event_view_response(
        requested_event_ids=["D", "B", "A"],
        response_json=_response({"id": "C"}, {"id": "A"}, {"id": "E"}),
    )

    assert result.returned_event_ids == ["C", "A", "E"]
    assert result.observable_events == [
        ObservableEvent(event_id="A", result_index=1),
        ObservableEvent(event_id="C", result_index=0),
        ObservableEvent(event_id="E", result_index=2),
    ]
    assert _issue_values(result.issues) == [
        ("missing_requested_event", "B", []),
        ("missing_requested_event", "D", []),
        ("unexpected_event_id", "C", [0]),
        ("unexpected_event_id", "E", [2]),
    ]


def test_analyze_event_view_response_handles_combined_issues() -> None:
    result = analyze_event_view_response(
        requested_event_ids=["A", "B"],
        response_json=_response(
            {"id": "A"},
            {"id": "C"},
            {"id": "C"},
            {"sport_id": "3"},
        ),
    )

    assert result.returned_event_ids == ["A", "C", "C"]
    assert result.observable_events == [ObservableEvent(event_id="A", result_index=0)]
    assert _issue_values(result.issues) == [
        ("missing_event_id", None, [3]),
        ("missing_requested_event", "B", []),
        ("unexpected_event_id", "C", [1, 2]),
        ("duplicate_event_id", "C", [1, 2]),
    ]
