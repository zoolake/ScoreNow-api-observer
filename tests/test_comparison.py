from datetime import UTC, datetime
from pathlib import Path

import pytest

from scorenow_api_observer.comparison import (
    CaptureComparison,
    StructureComparison,
    TypeChange,
    compare_observations,
    convert_to_structure_change_record,
    find_latest_observations,
    find_previous_observation,
)
from scorenow_api_observer.models import CaptureMetadata, EventObservation
from scorenow_api_observer.storage import (
    save_capture_metadata,
    save_event_observation,
    save_raw_response,
)


def _capture(
    *,
    event_id: str,
    captured_at: datetime,
    raw_file_path: str,
) -> CaptureMetadata:
    return CaptureMetadata(
        captured_at=captured_at,
        response_analysis_status="completed",
        provider="betsapi",
        endpoint="/v1/event/view",
        http_method="GET",
        requested_event_ids=[event_id],
        returned_event_ids=[event_id],
        response_issues=[],
        http_status_code=200,
        elapsed_ms=100,
        response_size_bytes=100,
        content_type="application/json",
        raw_file_path=raw_file_path,
    )


def test_has_changes_is_false_when_comparison_has_no_changes() -> None:
    comparison = StructureComparison(
        added_paths=[],
        removed_paths=[],
        type_changes=[],
    )

    assert comparison.has_changes is False


def test_has_changes_is_true_when_path_is_added() -> None:
    comparison = StructureComparison(
        added_paths=["$.results[].scores"],
        removed_paths=[],
        type_changes=[],
    )

    assert comparison.has_changes is True


def test_has_changes_is_true_when_path_is_removed() -> None:
    comparison = StructureComparison(
        added_paths=[],
        removed_paths=["$.results[].scores"],
        type_changes=[],
    )

    assert comparison.has_changes is True


def test_has_changes_is_true_when_type_changes() -> None:
    comparison = StructureComparison(
        added_paths=[],
        removed_paths=[],
        type_changes=[
            TypeChange(
                path="$.results[].ss",
                previous_types={"null"},
                current_types={"string"},
            )
        ],
    )

    assert comparison.has_changes is True


def test_find_previous_observation_returns_none_without_earlier_observation(
    tmp_path: Path,
) -> None:
    result = find_previous_observation(
        "123",
        reference_captured_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        base_directory=tmp_path / "observations",
    )

    assert result is None


def test_find_previous_observation_selects_latest_earlier_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_directory = tmp_path / "metadata"
    observation_directory = tmp_path / "observations"

    def save_observation(
        *,
        event_id: str,
        captured_at: datetime,
        raw_file_name: str,
    ) -> tuple[EventObservation, Path]:
        metadata = _capture(
            event_id=event_id,
            captured_at=captured_at,
            raw_file_path=str(tmp_path / "raw" / raw_file_name),
        )
        metadata_path = save_capture_metadata(metadata, metadata_directory)
        observation = EventObservation(
            event_id=event_id,
            capture_metadata_file_path=str(metadata_path),
            result_index=0,
        )
        observation_path = save_event_observation(
            observation,
            observation_directory,
        )
        return observation, observation_path

    latest_earlier, latest_earlier_path = save_observation(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 11, 0, tzinfo=UTC),
        raw_file_name="latest-earlier.json",
    )
    _, older_path = save_observation(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
        raw_file_name="older.json",
    )
    _, later_path = save_observation(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 13, 0, tzinfo=UTC),
        raw_file_name="later.json",
    )
    _, other_event_path = save_observation(
        event_id="456",
        captured_at=datetime(2026, 9, 13, 11, 30, tzinfo=UTC),
        raw_file_name="other-event.json",
    )
    observation_paths = [
        latest_earlier_path,
        older_path,
        later_path,
        other_event_path,
    ]

    def unordered_observation_paths(_directory: Path, pattern: str) -> list[Path]:
        assert pattern == "*.json"
        return observation_paths

    monkeypatch.setattr(
        type(observation_directory),
        "rglob",
        unordered_observation_paths,
    )

    result = find_previous_observation(
        "123",
        reference_captured_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        base_directory=observation_directory,
    )

    assert result == latest_earlier


def test_find_latest_observations_returns_empty_list_without_observations(
    tmp_path: Path,
) -> None:
    result = find_latest_observations(
        "123",
        base_directory=tmp_path / "observations",
    )

    assert result == []


def test_find_latest_observations_rejects_non_positive_limit(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="limit은 1 이상이어야 합니다"):
        find_latest_observations(
            "123",
            limit=0,
            base_directory=tmp_path / "observations",
        )


def test_find_latest_observations_selects_recent_observations_in_time_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_directory = tmp_path / "metadata"
    observation_directory = tmp_path / "observations"

    def save_observation(
        *,
        event_id: str,
        captured_at: datetime,
        raw_file_name: str,
    ) -> tuple[EventObservation, Path]:
        metadata = _capture(
            event_id=event_id,
            captured_at=captured_at,
            raw_file_path=str(tmp_path / "raw" / raw_file_name),
        )
        metadata_path = save_capture_metadata(metadata, metadata_directory)
        observation = EventObservation(
            event_id=event_id,
            capture_metadata_file_path=str(metadata_path),
            result_index=0,
        )
        observation_path = save_event_observation(
            observation,
            observation_directory,
        )
        return observation, observation_path

    latest, latest_path = save_observation(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 13, 0, tzinfo=UTC),
        raw_file_name="latest.json",
    )
    previous, previous_path = save_observation(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 11, 0, tzinfo=UTC),
        raw_file_name="previous.json",
    )
    _, older_path = save_observation(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
        raw_file_name="older.json",
    )
    _, other_event_path = save_observation(
        event_id="456",
        captured_at=datetime(2026, 9, 13, 14, 0, tzinfo=UTC),
        raw_file_name="other-event.json",
    )
    observation_paths = [
        latest_path,
        older_path,
        other_event_path,
        previous_path,
    ]

    def unordered_observation_paths(_directory: Path, pattern: str) -> list[Path]:
        assert pattern == "*.json"
        return observation_paths

    monkeypatch.setattr(
        type(observation_directory),
        "rglob",
        unordered_observation_paths,
    )

    result = find_latest_observations(
        "123",
        limit=2,
        base_directory=observation_directory,
    )
    limited_result = find_latest_observations(
        "123",
        limit=1,
        base_directory=observation_directory,
    )

    assert result == [previous, latest]
    assert limited_result == [latest]


def test_compare_observations_compares_only_referenced_event(
    tmp_path: Path,
) -> None:
    previous_captured_at = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
    current_captured_at = datetime(2026, 9, 13, 11, 0, tzinfo=UTC)
    previous_raw_path = save_raw_response(
        response_body=b'{"results":[{"id":"A","score":1},{"id":"B","old":true}]}',
        captured_at=previous_captured_at,
        base_directory=tmp_path / "raw",
    )
    current_raw_path = save_raw_response(
        response_body=b'{"results":[{"id":"A","score":2},{"id":"B","new":{}}]}',
        captured_at=current_captured_at,
        base_directory=tmp_path / "raw",
    )
    previous_metadata_path = save_capture_metadata(
        _capture(
            event_id="A",
            captured_at=previous_captured_at,
            raw_file_path=str(previous_raw_path),
        ),
        tmp_path / "metadata",
    )
    current_metadata_path = save_capture_metadata(
        _capture(
            event_id="A",
            captured_at=current_captured_at,
            raw_file_path=str(current_raw_path),
        ),
        tmp_path / "metadata",
    )
    previous_observation = EventObservation(
        event_id="A",
        capture_metadata_file_path=str(previous_metadata_path),
        result_index=0,
    )
    current_observation = EventObservation(
        event_id="A",
        capture_metadata_file_path=str(current_metadata_path),
        result_index=0,
    )

    result = compare_observations(previous_observation, current_observation)

    assert result.event_id == "A"
    assert result.previous_capture.captured_at == previous_captured_at
    assert result.current_capture.captured_at == current_captured_at
    assert result.structure_comparison.has_changes is False


def test_compare_observations_rejects_different_event_ids() -> None:
    previous_observation = EventObservation(
        event_id="A",
        capture_metadata_file_path="data/metadata/previous.json",
        result_index=0,
    )
    current_observation = EventObservation(
        event_id="B",
        capture_metadata_file_path="data/metadata/current.json",
        result_index=0,
    )

    with pytest.raises(ValueError, match="event_id가 일치하지 않습니다"):
        compare_observations(previous_observation, current_observation)


def test_convert_to_structure_change_record_returns_none_without_changes() -> None:
    previous_capture = _capture(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/previous.json",
    )
    current_capture = _capture(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 11, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    capture_comparison = CaptureComparison(
        event_id="123",
        previous_capture=previous_capture,
        current_capture=current_capture,
        structure_comparison=StructureComparison([], [], []),
    )

    result = convert_to_structure_change_record(
        capture_comparison,
        detected_at=datetime(2026, 9, 13, 11, 0, 1, tzinfo=UTC),
    )

    assert result is None


def test_convert_to_structure_change_record_maps_and_sorts_changes() -> None:
    previous_capture = _capture(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/previous.json",
    )
    current_capture = _capture(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 11, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    detected_at = datetime(2026, 9, 13, 11, 0, 1, tzinfo=UTC)
    capture_comparison = CaptureComparison(
        event_id="123",
        previous_capture=previous_capture,
        current_capture=current_capture,
        structure_comparison=StructureComparison(
            added_paths=["$.z", "$.a"],
            removed_paths=["$.y", "$.b"],
            type_changes=[
                TypeChange("$.z", {"string", "null"}, {"number", "integer"}),
                TypeChange("$.a", {"string"}, {"null"}),
            ],
        ),
    )

    result = convert_to_structure_change_record(capture_comparison, detected_at)

    assert result is not None
    assert result.detected_at == detected_at
    assert result.event_id == "123"
    assert result.previous_captured_at == previous_capture.captured_at
    assert result.current_captured_at == current_capture.captured_at
    assert result.previous_raw_file_path == previous_capture.raw_file_path
    assert result.current_raw_file_path == current_capture.raw_file_path
    assert result.added_paths == ["$.a", "$.z"]
    assert result.removed_paths == ["$.b", "$.y"]
    assert [type_change.path for type_change in result.type_changes] == ["$.a", "$.z"]
    assert result.type_changes[1].previous_types == ["null", "string"]
    assert result.type_changes[1].current_types == ["integer", "number"]
