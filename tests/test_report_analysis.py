import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scorenow_api_observer.event_view.models import CaptureMetadata, EventObservation
from scorenow_api_observer.event_view.observation import (
    InvalidEventObservationReferenceError,
)
from scorenow_api_observer.event_view.response import EventViewResponseIssue
from scorenow_api_observer.event_view.storage import (
    save_capture_metadata,
    save_event_observation,
)
from scorenow_api_observer.reporting.analysis import (
    analyze_event_view_report,
    extract_event_league_id,
    summarize_league_fields,
    summarize_league_observations,
    summarize_league_tracked_field_values,
    summarize_response_analysis_statuses,
    summarize_response_issues,
    summarize_sport_fields,
    summarize_sport_observations,
    summarize_tracked_field_values,
)
from scorenow_api_observer.reporting.models import (
    LeagueDefinition,
    LeagueFieldSummary,
    LeagueObservationSummary,
    LeagueTrackedFieldSummary,
    ObservedEvent,
    ResponseAnalysisStatusSummary,
    ResponseIssueSummary,
    SportFieldSummary,
    SportObservationSummary,
    SportTrackedFieldSummary,
    TrackedFieldUnsupportedTypeSummary,
    TrackedFieldValueSummary,
)
from scorenow_api_observer.reporting.sources import (
    load_capture_metadata_files,
    resolve_observed_event,
    resolve_observed_events,
)


def _save_observation_source(
    *,
    tmp_path: Path,
    response_json: object,
    captured_at: datetime,
    event_id: str,
    result_index: int,
) -> tuple[EventObservation, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    raw_file_path = tmp_path / "capture.json"
    raw_file_path.write_text(json.dumps(response_json), encoding="utf-8")

    metadata = CaptureMetadata(
        response_analysis_status="completed",
        captured_at=captured_at,
        provider="betsapi",
        endpoint="/v1/event/view",
        http_method="GET",
        requested_event_ids=[event_id],
        returned_event_ids=[event_id],
        response_issues=[],
        http_status_code=200,
        elapsed_ms=10.5,
        response_size_bytes=raw_file_path.stat().st_size,
        content_type="application/json",
        raw_file_path=str(raw_file_path),
    )
    metadata_path = save_capture_metadata(
        metadata,
        base_directory=tmp_path / "metadata",
    )

    observation = EventObservation(
        event_id=event_id,
        capture_metadata_file_path=str(metadata_path),
        result_index=result_index,
    )
    return observation, raw_file_path


def _observed_event(
    *,
    event_id: str,
    sport_code: str | None,
    event_data: dict[str, object],
    index: int = 0,
) -> ObservedEvent:
    return ObservedEvent(
        event_id=event_id,
        captured_at=datetime(2026, 10, 20, 12, index, tzinfo=UTC),
        raw_file_path=Path(f"{event_id}-{index}.json"),
        result_index=0,
        sport_code=sport_code,
        event_data=event_data,
    )


def test_resolve_observed_event_resolves_reference_and_classifies_sport(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    event_data = {"id": "B", "sport_id": "16", "score": "3-2"}
    observation, raw_file_path = _save_observation_source(
        tmp_path=tmp_path,
        response_json={"results": [{"id": "A"}, event_data]},
        captured_at=captured_at,
        event_id="B",
        result_index=1,
    )

    result = resolve_observed_event(
        observation=observation,
        sport_code_by_id={"1": "football", "16": "baseball"},
    )

    assert result == ObservedEvent(
        event_id="B",
        captured_at=captured_at,
        raw_file_path=raw_file_path,
        result_index=1,
        sport_code="baseball",
        event_data=event_data,
    )


def test_resolve_observed_event_leaves_unclassified_sport_as_none(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    event_data = {"id": "A", "sport_id": "999"}
    observation, _ = _save_observation_source(
        tmp_path=tmp_path,
        response_json={"results": [event_data]},
        captured_at=captured_at,
        event_id="A",
        result_index=0,
    )

    result = resolve_observed_event(
        observation=observation,
        sport_code_by_id={"16": "baseball"},
    )

    assert result.sport_code is None


def test_resolve_observed_event_propagates_invalid_reference(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    observation, _ = _save_observation_source(
        tmp_path=tmp_path,
        response_json={"results": [{"id": "A", "sport_id": "16"}]},
        captured_at=captured_at,
        event_id="B",
        result_index=0,
    )

    with pytest.raises(InvalidEventObservationReferenceError):
        resolve_observed_event(
            observation=observation,
            sport_code_by_id={"16": "baseball"},
        )


def test_resolve_observed_events_continues_after_file_failure_and_preserves_order(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    first_observation, _ = _save_observation_source(
        tmp_path=tmp_path / "first",
        response_json={"results": [{"id": "A", "sport_id": "1"}]},
        captured_at=captured_at,
        event_id="A",
        result_index=0,
    )
    second_observation, _ = _save_observation_source(
        tmp_path=tmp_path / "second",
        response_json={"results": [{"id": "B", "sport_id": "16"}]},
        captured_at=captured_at,
        event_id="B",
        result_index=0,
    )
    first_observation_path = save_event_observation(
        first_observation,
        base_directory=tmp_path / "first-observations",
    )
    second_observation_path = save_event_observation(
        second_observation,
        base_directory=tmp_path / "second-observations",
    )
    missing_observation_path = tmp_path / "missing.json"

    result = resolve_observed_events(
        observation_file_paths=[
            first_observation_path,
            missing_observation_path,
            second_observation_path,
        ],
        sport_code_by_id={"1": "football", "16": "baseball"},
    )

    assert [event.event_id for event in result.observed_events] == ["A", "B"]
    assert len(result.failures) == 1
    assert result.failures[0].observation_file_path == missing_observation_path
    assert result.failures[0].error_message.startswith("FileNotFoundError: ")


def test_load_capture_metadata_files_continues_after_failure_and_preserves_order(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    first_observation, _ = _save_observation_source(
        tmp_path=tmp_path / "first",
        response_json={"results": [{"id": "A"}]},
        captured_at=captured_at,
        event_id="A",
        result_index=0,
    )
    second_observation, _ = _save_observation_source(
        tmp_path=tmp_path / "second",
        response_json={"results": [{"id": "B"}]},
        captured_at=captured_at,
        event_id="B",
        result_index=0,
    )
    first_metadata_path = Path(first_observation.capture_metadata_file_path)
    second_metadata_path = Path(second_observation.capture_metadata_file_path)
    missing_metadata_path = tmp_path / "missing.json"

    result = load_capture_metadata_files(
        metadata_file_paths=[
            first_metadata_path,
            missing_metadata_path,
            second_metadata_path,
        ]
    )

    assert [item.requested_event_ids for item in result.metadata_items] == [
        ["A"],
        ["B"],
    ]
    assert len(result.failures) == 1
    assert result.failures[0].metadata_file_path == missing_metadata_path
    assert result.failures[0].error_message.startswith("FileNotFoundError: ")


def test_summarize_response_issues_counts_occurrences_and_affected_captures() -> None:
    first_metadata = CaptureMetadata(
        response_analysis_status="completed",
        captured_at=datetime(2026, 9, 22, 12, 30, tzinfo=UTC),
        provider="betsapi",
        endpoint="/v1/event/view",
        http_method="GET",
        requested_event_ids=["A", "B"],
        returned_event_ids=["C"],
        response_issues=[
            EventViewResponseIssue("missing_requested_event", "A", []),
            EventViewResponseIssue("missing_requested_event", "B", []),
            EventViewResponseIssue("unexpected_event_id", "C", [0]),
        ],
        http_status_code=200,
        elapsed_ms=10,
        response_size_bytes=100,
        content_type="application/json",
        raw_file_path="first.json",
    )
    second_metadata = CaptureMetadata(
        response_analysis_status="completed",
        captured_at=datetime(2026, 9, 22, 12, 31, tzinfo=UTC),
        provider="betsapi",
        endpoint="/v1/event/view",
        http_method="GET",
        requested_event_ids=["D"],
        returned_event_ids=["E", "E"],
        response_issues=[
            EventViewResponseIssue("missing_requested_event", "D", []),
            EventViewResponseIssue("duplicate_event_id", "E", [0, 1]),
        ],
        http_status_code=200,
        elapsed_ms=10,
        response_size_bytes=100,
        content_type="application/json",
        raw_file_path="second.json",
    )

    result = summarize_response_issues([first_metadata, second_metadata])

    assert result == [
        ResponseIssueSummary(
            code="duplicate_event_id",
            occurrence_count=1,
            affected_capture_count=1,
        ),
        ResponseIssueSummary(
            code="missing_requested_event",
            occurrence_count=3,
            affected_capture_count=2,
        ),
        ResponseIssueSummary(
            code="unexpected_event_id",
            occurrence_count=1,
            affected_capture_count=1,
        ),
    ]


def test_summarize_response_issues_returns_empty_list_for_empty_input() -> None:
    assert summarize_response_issues([]) == []


def test_summarize_response_analysis_statuses_includes_zero_count_statuses() -> None:
    completed_metadata = CaptureMetadata(
        response_analysis_status="completed",
        captured_at=datetime(2026, 9, 22, 12, 30, tzinfo=UTC),
        provider="betsapi",
        endpoint="/v1/event/view",
        http_method="GET",
        requested_event_ids=["A"],
        returned_event_ids=["A"],
        response_issues=[],
        http_status_code=200,
        elapsed_ms=10,
        response_size_bytes=100,
        content_type="application/json",
        raw_file_path="capture.json",
    )
    invalid_json_metadata = completed_metadata.model_copy(
        update={"response_analysis_status": "invalid_json"}
    )

    result = summarize_response_analysis_statuses(
        [completed_metadata, invalid_json_metadata]
    )

    assert result == [
        ResponseAnalysisStatusSummary(status="completed", capture_count=1),
        ResponseAnalysisStatusSummary(status="invalid_json", capture_count=1),
        ResponseAnalysisStatusSummary(
            status="invalid_response_shape",
            capture_count=0,
        ),
    ]


def test_status_summary_includes_all_statuses_for_empty_input() -> None:
    result = summarize_response_analysis_statuses([])

    assert result == [
        ResponseAnalysisStatusSummary(status="completed", capture_count=0),
        ResponseAnalysisStatusSummary(status="invalid_json", capture_count=0),
        ResponseAnalysisStatusSummary(
            status="invalid_response_shape",
            capture_count=0,
        ),
    ]


def test_summarize_sport_observations_counts_depth_and_unique_events() -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    observed_events = [
        ObservedEvent(
            event_id="baseball-a",
            captured_at=captured_at,
            raw_file_path=Path("baseball-a-1.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"id": "baseball-a"},
        ),
        ObservedEvent(
            event_id="baseball-a",
            captured_at=captured_at,
            raw_file_path=Path("baseball-a-2.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"id": "baseball-a"},
        ),
        ObservedEvent(
            event_id="baseball-b",
            captured_at=captured_at,
            raw_file_path=Path("baseball-b.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"id": "baseball-b"},
        ),
        ObservedEvent(
            event_id="unknown-a",
            captured_at=captured_at,
            raw_file_path=Path("unknown-a.json"),
            result_index=0,
            sport_code=None,
            event_data={"id": "unknown-a"},
        ),
    ]

    result = summarize_sport_observations(
        observed_events=observed_events,
        registered_sport_codes={"football", "baseball", "basketball"},
    )

    assert result == [
        SportObservationSummary(
            sport_code="baseball",
            observation_count=3,
            unique_event_count=2,
        ),
        SportObservationSummary(
            sport_code="basketball",
            observation_count=0,
            unique_event_count=0,
        ),
        SportObservationSummary(
            sport_code="football",
            observation_count=0,
            unique_event_count=0,
        ),
        SportObservationSummary(
            sport_code=None,
            observation_count=1,
            unique_event_count=1,
        ),
    ]


def test_sport_summary_includes_zero_count_rows_for_empty_input() -> None:
    result = summarize_sport_observations(
        observed_events=[],
        registered_sport_codes={"football", "baseball"},
    )

    assert result == [
        SportObservationSummary(
            sport_code="baseball",
            observation_count=0,
            unique_event_count=0,
        ),
        SportObservationSummary(
            sport_code="football",
            observation_count=0,
            unique_event_count=0,
        ),
        SportObservationSummary(
            sport_code=None,
            observation_count=0,
            unique_event_count=0,
        ),
    ]


def test_summarize_sport_fields_counts_presence_and_event_reliability() -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    observed_events = [
        ObservedEvent(
            event_id="A",
            captured_at=captured_at,
            raw_file_path=Path("baseball-a-1.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"id": "A", "score": None, "details": {"inning": 1}},
        ),
        ObservedEvent(
            event_id="A",
            captured_at=captured_at,
            raw_file_path=Path("baseball-a-2.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"id": "A", "details": {"inning": "1"}},
        ),
        ObservedEvent(
            event_id="B",
            captured_at=captured_at,
            raw_file_path=Path("baseball-b.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"id": "B", "details": {}},
        ),
        ObservedEvent(
            event_id="A",
            captured_at=captured_at,
            raw_file_path=Path("football-a.json"),
            result_index=0,
            sport_code="football",
            event_data={"id": "A", "clock": "90"},
        ),
        ObservedEvent(
            event_id="U",
            captured_at=captured_at,
            raw_file_path=Path("unclassified-u.json"),
            result_index=0,
            sport_code=None,
            event_data={"id": "U", "mystery": True},
        ),
    ]

    result = summarize_sport_fields(observed_events)
    summaries_by_key = {
        (summary.sport_code, summary.path): summary for summary in result
    }

    assert all(summary.path != "$" for summary in result)
    assert summaries_by_key[("baseball", "$.score")] == SportFieldSummary(
        sport_code="baseball",
        path="$.score",
        observed_types={"null"},
        present_observation_count=1,
        always_present_event_count=0,
        sometimes_present_event_count=1,
        never_present_event_count=1,
    )
    assert summaries_by_key[("baseball", "$.details.inning")] == SportFieldSummary(
        sport_code="baseball",
        path="$.details.inning",
        observed_types={"integer", "string"},
        present_observation_count=2,
        always_present_event_count=1,
        sometimes_present_event_count=0,
        never_present_event_count=1,
    )
    assert summaries_by_key[("football", "$.clock")].always_present_event_count == 1
    assert summaries_by_key[(None, "$.mystery")].observed_types == {"boolean"}


def test_summarize_sport_fields_returns_empty_list_for_empty_input() -> None:
    assert summarize_sport_fields([]) == []


def test_summarize_sport_fields_sorts_sports_and_paths_deterministically() -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    observed_events = [
        ObservedEvent(
            event_id="U",
            captured_at=captured_at,
            raw_file_path=Path("unclassified.json"),
            result_index=0,
            sport_code=None,
            event_data={"z": 1, "a": 1},
        ),
        ObservedEvent(
            event_id="F",
            captured_at=captured_at,
            raw_file_path=Path("football.json"),
            result_index=0,
            sport_code="football",
            event_data={"z": 1, "a": 1},
        ),
        ObservedEvent(
            event_id="B",
            captured_at=captured_at,
            raw_file_path=Path("baseball.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"z": 1, "a": 1},
        ),
    ]

    result = summarize_sport_fields(observed_events)
    reversed_input_result = summarize_sport_fields(list(reversed(observed_events)))

    expected_keys = [
        ("baseball", "$.a"),
        ("baseball", "$.z"),
        ("football", "$.a"),
        ("football", "$.z"),
        (None, "$.a"),
        (None, "$.z"),
    ]
    assert [(summary.sport_code, summary.path) for summary in result] == expected_keys
    assert [
        (summary.sport_code, summary.path) for summary in reversed_input_result
    ] == expected_keys


@pytest.mark.parametrize(
    ("event_data", "expected"),
    [
        ({"league": {"id": "349"}}, "349"),
        ({"league": {"id": " 349 "}}, "349"),
        ({"league": {"name": "KBO"}}, None),
        ({"league": {"id": ""}}, None),
        ({"league": {"id": 349}}, None),
        ({"league": []}, None),
        ({}, None),
    ],
)
def test_extract_event_league_id_accepts_only_non_empty_strings(
    event_data: dict[str, object],
    expected: str | None,
) -> None:
    assert extract_event_league_id(event_data) == expected


def test_summarize_league_observations_preserves_config_order_and_classifies_rest() -> (
    None
):
    definitions = [
        LeagueDefinition("football", "94", "england-premier-league"),
        LeagueDefinition("football", "8914", "k-league-2"),
        LeagueDefinition("baseball", "225", "mlb"),
    ]
    observed_events = [
        _observed_event(
            event_id="EPL-A",
            sport_code="football",
            event_data={"league": {"id": "94"}},
            index=1,
        ),
        _observed_event(
            event_id="EPL-A",
            sport_code="football",
            event_data={"league": {"id": "94"}},
            index=2,
        ),
        _observed_event(
            event_id="UNKNOWN",
            sport_code="football",
            event_data={"league": {"id": "999"}},
        ),
        _observed_event(
            event_id="NO-ID",
            sport_code="football",
            event_data={"league": {"name": "Unknown"}},
        ),
        _observed_event(
            event_id="NO-SPORT",
            sport_code=None,
            event_data={"league": {"id": "94"}},
        ),
    ]

    result = summarize_league_observations(
        observed_events=observed_events,
        league_definitions=definitions,
    )

    assert result == [
        LeagueObservationSummary(
            "football", "94", "england-premier-league", True, 2, 1
        ),
        LeagueObservationSummary("football", "8914", "k-league-2", True, 0, 0),
        LeagueObservationSummary("baseball", "225", "mlb", True, 0, 0),
        LeagueObservationSummary("football", "999", "league-999", False, 1, 1),
        LeagueObservationSummary("football", None, "unclassified", False, 1, 1),
    ]


def test_summarize_league_fields_uses_sport_path_union_for_each_observed_league() -> (
    None
):
    observed_events = [
        _observed_event(
            event_id="A",
            sport_code="football",
            event_data={
                "league": {"id": "94"},
                "shared": None,
                "changing": 1,
                "epl_only": True,
            },
            index=1,
        ),
        _observed_event(
            event_id="A",
            sport_code="football",
            event_data={"league": {"id": "94"}, "shared": None},
            index=2,
        ),
        _observed_event(
            event_id="B",
            sport_code="football",
            event_data={"league": {"id": "8914"}, "shared": None},
        ),
    ]
    league_summaries = summarize_league_observations(
        observed_events=observed_events,
        league_definitions=[
            LeagueDefinition("football", "94", "england-premier-league"),
            LeagueDefinition("football", "8914", "k-league-2"),
        ],
    )

    result = summarize_league_fields(
        observed_events=observed_events,
        league_observation_summaries=league_summaries,
    )
    summaries_by_key = {
        (summary.league_id, summary.path): summary for summary in result
    }

    assert summaries_by_key[("94", "$.changing")] == LeagueFieldSummary(
        sport_code="football",
        league_id="94",
        path="$.changing",
        observed_types={"integer"},
        present_observation_count=1,
        always_present_event_count=0,
        sometimes_present_event_count=1,
        never_present_event_count=0,
    )
    assert summaries_by_key[("8914", "$.changing")] == LeagueFieldSummary(
        sport_code="football",
        league_id="8914",
        path="$.changing",
        observed_types=set(),
        present_observation_count=0,
        always_present_event_count=0,
        sometimes_present_event_count=0,
        never_present_event_count=1,
    )
    assert summaries_by_key[("94", "$.shared")].always_present_event_count == 1
    assert summaries_by_key[("8914", "$.epl_only")].never_present_event_count == 1


def test_summarize_league_tracked_field_values_filters_each_league() -> None:
    observed_events = [
        _observed_event(
            event_id="A",
            sport_code="baseball",
            event_data={"league": {"id": "225"}, "time_status": 1},
        ),
        _observed_event(
            event_id="B",
            sport_code="baseball",
            event_data={"league": {"id": "349"}, "time_status": 3},
        ),
        _observed_event(
            event_id="C",
            sport_code="baseball",
            event_data={"league": {"id": "349"}},
        ),
    ]
    league_summaries = summarize_league_observations(
        observed_events=observed_events,
        league_definitions=[
            LeagueDefinition("baseball", "225", "mlb"),
            LeagueDefinition("baseball", "349", "kbo"),
            LeagueDefinition("baseball", "347", "npb"),
        ],
    )

    result = summarize_league_tracked_field_values(
        observed_events=observed_events,
        league_observation_summaries=league_summaries,
        paths_by_sport_code={"baseball": ("$.time_status",)},
    )

    assert result == [
        LeagueTrackedFieldSummary(
            sport_code="baseball",
            league_id="225",
            path="$.time_status",
            value_summaries=[TrackedFieldValueSummary("integer", True, 1, 1, 1)],
            unsupported_type_summaries=[],
        ),
        LeagueTrackedFieldSummary(
            sport_code="baseball",
            league_id="349",
            path="$.time_status",
            value_summaries=[
                TrackedFieldValueSummary("integer", True, 3, 1, 1),
                TrackedFieldValueSummary("missing", False, None, 1, 1),
            ],
            unsupported_type_summaries=[],
        ),
    ]


def test_summarize_tracked_field_values_distinguishes_json_scalar_states() -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    values: list[tuple[str, dict[str, object]]] = [
        ("A", {"state": 1}),
        ("A", {"state": 1}),
        ("B", {"state": 1.0}),
        ("C", {"state": "1"}),
        ("D", {"state": True}),
        ("E", {"state": None}),
        ("F", {}),
    ]
    observed_events = [
        ObservedEvent(
            event_id=event_id,
            captured_at=captured_at,
            raw_file_path=Path(f"{index}.json"),
            result_index=0,
            sport_code="baseball",
            event_data=event_data,
        )
        for index, (event_id, event_data) in enumerate(values)
    ]

    result = summarize_tracked_field_values(
        observed_events=observed_events,
        paths_by_sport_code={"baseball": ("$.state",)},
    )

    assert result == [
        SportTrackedFieldSummary(
            sport_code="baseball",
            path="$.state",
            value_summaries=[
                TrackedFieldValueSummary("boolean", True, True, 1, 1),
                TrackedFieldValueSummary("integer", True, 1, 2, 1),
                TrackedFieldValueSummary("number", True, 1.0, 1, 1),
                TrackedFieldValueSummary("string", True, "1", 1, 1),
                TrackedFieldValueSummary("null", True, None, 1, 1),
                TrackedFieldValueSummary("missing", False, None, 1, 1),
            ],
            unsupported_type_summaries=[],
        )
    ]


def test_summarize_tracked_field_values_reports_objects_and_arrays_as_unsupported() -> (
    None
):
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    observed_events = [
        ObservedEvent(
            event_id="A",
            captured_at=captured_at,
            raw_file_path=Path("a-1.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"state": {"code": 1}, "wrapper": [{"state": 1}]},
        ),
        ObservedEvent(
            event_id="A",
            captured_at=captured_at,
            raw_file_path=Path("a-2.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"state": {}, "wrapper": [{"state": 2}]},
        ),
        ObservedEvent(
            event_id="B",
            captured_at=captured_at,
            raw_file_path=Path("b.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"state": [], "wrapper": []},
        ),
    ]

    result = summarize_tracked_field_values(
        observed_events=observed_events,
        paths_by_sport_code={"baseball": ("$.state", "$.wrapper.state")},
    )

    assert result == [
        SportTrackedFieldSummary(
            sport_code="baseball",
            path="$.state",
            value_summaries=[],
            unsupported_type_summaries=[
                TrackedFieldUnsupportedTypeSummary("array", 1, 1),
                TrackedFieldUnsupportedTypeSummary("object", 2, 1),
            ],
        ),
        SportTrackedFieldSummary(
            sport_code="baseball",
            path="$.wrapper.state",
            value_summaries=[],
            unsupported_type_summaries=[
                TrackedFieldUnsupportedTypeSummary("array", 3, 2),
            ],
        ),
    ]


def test_summarize_tracked_field_values_uses_config_order_and_sport_filter() -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    observed_events = [
        ObservedEvent(
            event_id="B",
            captured_at=captured_at,
            raw_file_path=Path("baseball.json"),
            result_index=0,
            sport_code="baseball",
            event_data={"time_status": 3},
        ),
        ObservedEvent(
            event_id="F",
            captured_at=captured_at,
            raw_file_path=Path("football.json"),
            result_index=0,
            sport_code="football",
            event_data={"timer": {"md": 2}, "time_status": 1},
        ),
    ]

    result = summarize_tracked_field_values(
        observed_events=observed_events,
        paths_by_sport_code={
            "football": ("$.timer.md", "$.time_status"),
            "baseball": ("$.time_status",),
            "basketball": ("$.time_status",),
        },
    )

    assert [(summary.sport_code, summary.path) for summary in result] == [
        ("football", "$.timer.md"),
        ("football", "$.time_status"),
        ("baseball", "$.time_status"),
        ("basketball", "$.time_status"),
    ]
    assert result[0].value_summaries == [
        TrackedFieldValueSummary("integer", True, 2, 1, 1)
    ]
    assert result[2].value_summaries == [
        TrackedFieldValueSummary("integer", True, 3, 1, 1)
    ]
    assert result[3].value_summaries == []


def test_analyze_event_view_report_combines_summaries_and_failures(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 9, 22, 12, 30, tzinfo=UTC)
    observation, _ = _save_observation_source(
        tmp_path=tmp_path / "valid",
        response_json={"results": [{"id": "A", "sport_id": "16"}]},
        captured_at=captured_at,
        event_id="A",
        result_index=0,
    )
    observation_path = save_event_observation(
        observation,
        base_directory=tmp_path / "observations",
    )
    metadata_path = Path(observation.capture_metadata_file_path)
    missing_metadata_path = tmp_path / "missing-metadata.json"
    missing_observation_path = tmp_path / "missing-observation.json"

    result = analyze_event_view_report(
        metadata_file_paths=[metadata_path, missing_metadata_path],
        observation_file_paths=[observation_path, missing_observation_path],
        sport_code_by_id={"1": "football", "16": "baseball"},
        tracked_field_paths_by_sport_code={
            "football": ("$.time_status",),
            "baseball": ("$.time_status",),
        },
    )

    assert result.response_analysis_status_summaries == [
        ResponseAnalysisStatusSummary(status="completed", capture_count=1),
        ResponseAnalysisStatusSummary(status="invalid_json", capture_count=0),
        ResponseAnalysisStatusSummary(
            status="invalid_response_shape",
            capture_count=0,
        ),
    ]
    assert result.response_issue_summaries == []
    assert result.sport_observation_summaries == [
        SportObservationSummary(
            sport_code="baseball",
            observation_count=1,
            unique_event_count=1,
        ),
        SportObservationSummary(
            sport_code="football",
            observation_count=0,
            unique_event_count=0,
        ),
        SportObservationSummary(
            sport_code=None,
            observation_count=0,
            unique_event_count=0,
        ),
    ]
    assert result.sport_field_summaries == [
        SportFieldSummary(
            sport_code="baseball",
            path="$.id",
            observed_types={"string"},
            present_observation_count=1,
            always_present_event_count=1,
            sometimes_present_event_count=0,
            never_present_event_count=0,
        ),
        SportFieldSummary(
            sport_code="baseball",
            path="$.sport_id",
            observed_types={"string"},
            present_observation_count=1,
            always_present_event_count=1,
            sometimes_present_event_count=0,
            never_present_event_count=0,
        ),
    ]
    assert result.sport_tracked_field_summaries == [
        SportTrackedFieldSummary(
            sport_code="football",
            path="$.time_status",
            value_summaries=[],
            unsupported_type_summaries=[],
        ),
        SportTrackedFieldSummary(
            sport_code="baseball",
            path="$.time_status",
            value_summaries=[TrackedFieldValueSummary("missing", False, None, 1, 1)],
            unsupported_type_summaries=[],
        ),
    ]
    assert len(result.capture_metadata_load_failures) == 1
    assert (
        result.capture_metadata_load_failures[0].metadata_file_path
        == missing_metadata_path
    )
    assert len(result.observed_event_resolution_failures) == 1
    assert (
        result.observed_event_resolution_failures[0].observation_file_path
        == missing_observation_path
    )
