import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scorenow_api_observer.event_view_response import EventViewResponseIssue
from scorenow_api_observer.models import (
    CaptureMetadata,
    EventObservation,
    StructureChangeRecord,
    TypeChangeRecord,
)
from scorenow_api_observer.storage import (
    find_capture_metadata_paths,
    find_event_observation_paths,
    load_capture_metadata,
    load_event_observation,
    save_capture_metadata,
    save_event_observation,
    save_raw_response,
    save_structure_change_record,
)


def test_find_capture_metadata_paths_returns_recursive_json_paths_in_order(
    tmp_path: Path,
) -> None:
    metadata_directory = tmp_path / "metadata"
    first_path = metadata_directory / "2026-09-21" / "capture-a.json"
    second_path = metadata_directory / "2026-09-21" / "capture-b.json"
    third_path = metadata_directory / "2026-09-22" / "capture-a.json"

    for metadata_path in [third_path, second_path, first_path]:
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text("{}", encoding="utf-8")

    ignored_path = metadata_directory / "2026-09-21" / "notes.txt"
    ignored_path.write_text("not metadata", encoding="utf-8")

    result = find_capture_metadata_paths(metadata_directory)

    assert result == [first_path, second_path, third_path]


def test_find_capture_metadata_paths_returns_empty_list_for_missing_directory(
    tmp_path: Path,
) -> None:
    result = find_capture_metadata_paths(tmp_path / "does-not-exist")

    assert result == []


def test_find_event_observation_paths_returns_recursive_json_paths_in_order(
    tmp_path: Path,
) -> None:
    observation_directory = tmp_path / "observations"
    first_path = observation_directory / "A" / "20260921_capture.json"
    second_path = observation_directory / "A" / "20260922_capture.json"
    third_path = observation_directory / "B" / "20260920_capture.json"

    for observation_path in [third_path, second_path, first_path]:
        observation_path.parent.mkdir(parents=True, exist_ok=True)
        observation_path.write_text("{}", encoding="utf-8")

    ignored_path = observation_directory / "A" / "notes.txt"
    ignored_path.write_text("not an observation", encoding="utf-8")

    result = find_event_observation_paths(observation_directory)

    assert result == [first_path, second_path, third_path]


def test_find_event_observation_paths_returns_empty_list_for_missing_directory(
    tmp_path: Path,
) -> None:
    result = find_event_observation_paths(tmp_path / "does-not-exist")

    assert result == []


def test_save_raw_response_and_metadata(
    tmp_path: Path,
) -> None:
    """원문과 메타데이터가 같은 파일명으로 저장되는지 테스트"""

    # given
    captured_at = datetime(2026, 9, 9, 15, 0, 0, 0, UTC)

    event_id = "1234567"
    response_body = b'{"success":1,"results":[{"id":"1234567"}]}'

    # when
    raw_path = save_raw_response(
        response_body=response_body,
        captured_at=captured_at,
        base_directory=tmp_path / "raw",
    )

    metadata = CaptureMetadata(
        captured_at=captured_at,
        response_analysis_status="completed",
        provider="betsapi",
        endpoint="v1/event/view",
        http_method="GET",
        requested_event_ids=[event_id],
        returned_event_ids=[event_id],
        response_issues=[],
        http_status_code=200,
        elapsed_ms=182.47,
        response_size_bytes=len(response_body),
        content_type="application/json",
        raw_file_path=str(raw_path),
    )

    metadata_path = save_capture_metadata(metadata, tmp_path / "metadata")

    # then
    expected_file_name = "20260909T150000000000Z_capture.json"

    assert raw_path == (tmp_path / "raw" / "2026-09-09" / expected_file_name)
    assert metadata_path == (tmp_path / "metadata" / "2026-09-09" / expected_file_name)

    assert raw_path.read_bytes() == response_body

    saved_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert saved_metadata["provider"] == "betsapi"
    assert saved_metadata["schema_version"] == 1
    assert saved_metadata["response_analysis_status"] == "completed"
    assert saved_metadata["requested_event_ids"] == ["1234567"]
    assert saved_metadata["returned_event_ids"] == ["1234567"]
    assert saved_metadata["response_issues"] == []
    assert "event_ids" not in saved_metadata
    assert saved_metadata["http_status_code"] == 200
    assert saved_metadata["response_size_bytes"] == len(response_body)
    assert saved_metadata["raw_file_path"] == str(raw_path)


def test_load_capture_metadata_reads_current_schema_without_raw_file(
    tmp_path: Path,
) -> None:
    metadata = CaptureMetadata(
        captured_at=datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
        response_analysis_status="completed",
        provider="betsapi",
        endpoint="/v1/event/view",
        http_method="GET",
        requested_event_ids=["A", "B"],
        returned_event_ids=["A", "C"],
        response_issues=[EventViewResponseIssue("unexpected_event_id", "C", [1])],
        http_status_code=200,
        elapsed_ms=182.47,
        response_size_bytes=100,
        content_type="application/json",
        raw_file_path="data/raw/does-not-exist.json",
    )
    metadata_path = save_capture_metadata(metadata, tmp_path / "metadata")

    loaded_metadata = load_capture_metadata(metadata_path)

    assert loaded_metadata == metadata


def test_load_capture_metadata_converts_legacy_schema_using_raw_response(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(
        json.dumps(
            {
                "success": 1,
                "results": [
                    {"id": "A"},
                    {"id": "C"},
                    {"id": "C"},
                    {"sport_id": "3"},
                ],
            }
        ),
        encoding="utf-8",
    )
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "captured_at": "2026-09-09T15:00:00Z",
                "provider": "betsapi",
                "endpoint": "/v1/event/view",
                "http_method": "GET",
                "event_ids": ["A", "B"],
                "http_status_code": 200,
                "elapsed_ms": 182.47,
                "response_size_bytes": raw_path.stat().st_size,
                "content_type": "application/json",
                "raw_file_path": str(raw_path),
            }
        ),
        encoding="utf-8",
    )

    loaded_metadata = load_capture_metadata(metadata_path)

    assert loaded_metadata.schema_version == 1
    assert loaded_metadata.response_analysis_status == "completed"
    assert loaded_metadata.requested_event_ids == ["A", "B"]
    assert loaded_metadata.returned_event_ids == ["A", "C", "C"]
    assert loaded_metadata.response_issues == [
        EventViewResponseIssue("missing_event_id", None, [3]),
        EventViewResponseIssue("missing_requested_event", "B", []),
        EventViewResponseIssue("unexpected_event_id", "C", [1, 2]),
        EventViewResponseIssue("duplicate_event_id", "C", [1, 2]),
    ]


def test_load_capture_metadata_rejects_null_schema_version(tmp_path: Path) -> None:
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": None,
                "response_analysis_status": "completed",
                "captured_at": "2026-09-09T15:00:00Z",
                "provider": "betsapi",
                "endpoint": "/v1/event/view",
                "http_method": "GET",
                "requested_event_ids": ["A"],
                "returned_event_ids": ["A"],
                "response_issues": [],
                "http_status_code": 200,
                "elapsed_ms": 182.47,
                "response_size_bytes": 100,
                "content_type": "application/json",
                "raw_file_path": "data/raw/current.json",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_capture_metadata(metadata_path)


def test_save_event_observation_uses_event_directory_and_capture_file_name(
    tmp_path: Path,
) -> None:
    observation = EventObservation(
        event_id="A/B",
        capture_metadata_file_path=("data/metadata/event-view/2026-09-18/capture.json"),
        result_index=2,
    )

    saved_path = save_event_observation(observation, tmp_path / "observations")

    assert saved_path == tmp_path / "observations" / "A_B" / "capture.json"
    assert (
        EventObservation.model_validate_json(saved_path.read_text(encoding="utf-8"))
        == observation
    )


def test_save_event_observation_overwrites_recreated_observation(
    tmp_path: Path,
) -> None:
    original = EventObservation(
        event_id="A",
        capture_metadata_file_path="data/metadata/capture.json",
        result_index=0,
    )
    recreated = EventObservation(
        event_id="A",
        capture_metadata_file_path="data/metadata/capture.json",
        result_index=1,
    )

    original_path = save_event_observation(original, tmp_path / "observations")
    recreated_path = save_event_observation(recreated, tmp_path / "observations")

    assert recreated_path == original_path
    assert (
        EventObservation.model_validate_json(recreated_path.read_text(encoding="utf-8"))
        == recreated
    )


def test_load_event_observation_reads_saved_observation(tmp_path: Path) -> None:
    observation = EventObservation(
        event_id="A",
        capture_metadata_file_path="data/metadata/capture.json",
        result_index=1,
    )
    observation_path = save_event_observation(
        observation,
        tmp_path / "observations",
    )

    loaded_observation = load_event_observation(observation_path)

    assert loaded_observation == observation


def test_load_event_observation_rejects_negative_result_index(
    tmp_path: Path,
) -> None:
    observation_path = tmp_path / "observation.json"
    observation_path.write_text(
        json.dumps(
            {
                "event_id": "A",
                "capture_metadata_file_path": "data/metadata/capture.json",
                "result_index": -1,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_event_observation(observation_path)


def test_save_structure_change_record_uses_event_id_date_and_capture_file_name(
    tmp_path: Path,
) -> None:
    record = StructureChangeRecord(
        detected_at=datetime(2026, 9, 10, 1, 0, tzinfo=UTC),
        event_id="1234567",
        previous_captured_at=datetime(2026, 9, 8, 14, 59, tzinfo=UTC),
        current_captured_at=datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
        previous_raw_file_path=(
            "data/raw/event-view/2026-09-08/20260908T145900000000Z_capture.json"
        ),
        current_raw_file_path=(
            "data/raw/event-view/2026-09-09/20260909T150000000000Z_capture.json"
        ),
        added_paths=["$.results[].scores"],
        removed_paths=["$.results[].status"],
        type_changes=[
            TypeChangeRecord(
                path="$.results[].time",
                previous_types=["string"],
                current_types=["integer"],
            )
        ],
    )

    saved_path = save_structure_change_record(record, tmp_path / "changes")

    assert saved_path == (
        tmp_path
        / "changes"
        / "1234567"
        / "2026-09-09"
        / "20260909T150000000000Z_capture.json"
    )
    assert (
        StructureChangeRecord.model_validate_json(
            saved_path.read_text(encoding="utf-8")
        )
        == record
    )


def test_save_structure_change_record_does_not_overwrite_existing_file(
    tmp_path: Path,
) -> None:
    record = StructureChangeRecord(
        detected_at=datetime(2026, 9, 9, 15, 0, 1, tzinfo=UTC),
        event_id="1234567",
        previous_captured_at=datetime(2026, 9, 9, 14, 59, tzinfo=UTC),
        current_captured_at=datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
        previous_raw_file_path="data/raw/previous.json",
        current_raw_file_path="data/raw/current.json",
        added_paths=["$.new"],
        removed_paths=[],
        type_changes=[],
    )
    existing_path = tmp_path / "changes" / "1234567" / "2026-09-09" / "current.json"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text("existing contents", encoding="utf-8")

    saved_path = save_structure_change_record(record, tmp_path / "changes")

    assert saved_path == existing_path
    assert existing_path.read_text(encoding="utf-8") == "existing contents"


def test_save_structure_change_record_uses_safe_event_id_directory(
    tmp_path: Path,
) -> None:
    record = StructureChangeRecord(
        detected_at=datetime(2026, 9, 9, 15, 0, 1, tzinfo=UTC),
        event_id="A/B",
        previous_captured_at=datetime(2026, 9, 9, 14, 59, tzinfo=UTC),
        current_captured_at=datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
        previous_raw_file_path="data/raw/previous.json",
        current_raw_file_path="data/raw/current.json",
        added_paths=["$.new"],
        removed_paths=[],
        type_changes=[],
    )

    saved_path = save_structure_change_record(record, tmp_path / "changes")

    assert saved_path == (tmp_path / "changes" / "A_B" / "2026-09-09" / "current.json")


def test_save_structure_change_record_separates_events_in_same_capture(
    tmp_path: Path,
) -> None:
    record_a = StructureChangeRecord(
        detected_at=datetime(2026, 9, 9, 15, 0, 1, tzinfo=UTC),
        event_id="A",
        previous_captured_at=datetime(2026, 9, 9, 14, 59, tzinfo=UTC),
        current_captured_at=datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
        previous_raw_file_path="data/raw/previous.json",
        current_raw_file_path="data/raw/current.json",
        added_paths=["$.new"],
        removed_paths=[],
        type_changes=[],
    )
    record_c = record_a.model_copy(update={"event_id": "C"})

    saved_path_a = save_structure_change_record(record_a, tmp_path / "changes")
    saved_path_c = save_structure_change_record(record_c, tmp_path / "changes")

    assert saved_path_a != saved_path_c
    assert (
        StructureChangeRecord.model_validate_json(
            saved_path_a.read_text(encoding="utf-8")
        )
        == record_a
    )
    assert (
        StructureChangeRecord.model_validate_json(
            saved_path_c.read_text(encoding="utf-8")
        )
        == record_c
    )
