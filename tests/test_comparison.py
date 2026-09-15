from datetime import UTC, datetime
from pathlib import Path

import pytest

from scorenow_api_observer.comparison import (
    CaptureComparison,
    StructureComparison,
    TypeChange,
    convert_to_structure_change_record,
    find_previous_capture,
)
from scorenow_api_observer.models import CaptureMetadata
from scorenow_api_observer.storage import save_capture_metadata


def _capture(
    *,
    event_id: str,
    captured_at: datetime,
    raw_file_path: str,
) -> CaptureMetadata:
    return CaptureMetadata(
        captured_at=captured_at,
        provider="betsapi",
        endpoint="/v1/event/view",
        http_method="GET",
        event_ids=[event_id],
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


def test_find_previous_capture_returns_none_without_earlier_capture(
    tmp_path: Path,
) -> None:
    current_capture = _capture(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )

    result = find_previous_capture("123", current_capture, tmp_path)

    assert result is None


def test_find_previous_capture_selects_latest_earlier_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_directory = tmp_path / "metadata"
    latest_earlier_capture = _capture(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 11, 0, tzinfo=UTC),
        raw_file_path="data/raw/latest-earlier.json",
    )
    older_capture = _capture(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/older.json",
    )
    later_capture = _capture(
        event_id="123",
        captured_at=datetime(2026, 9, 13, 13, 0, tzinfo=UTC),
        raw_file_path="data/raw/later.json",
    )
    other_event_capture = _capture(
        event_id="456",
        captured_at=datetime(2026, 9, 13, 11, 30, tzinfo=UTC),
        raw_file_path="data/raw/other-event.json",
    )

    metadata_paths = [
        save_capture_metadata(latest_earlier_capture, base_directory),
        save_capture_metadata(older_capture, base_directory),
        save_capture_metadata(later_capture, base_directory),
        save_capture_metadata(other_event_capture, base_directory),
    ]

    def unordered_metadata_paths(_directory: Path, pattern: str) -> list[Path]:
        assert pattern == "*.json"
        return metadata_paths

    monkeypatch.setattr(type(base_directory), "rglob", unordered_metadata_paths)

    result = find_previous_capture(
        "123",
        current_capture=_capture(
            event_id="123",
            captured_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
            raw_file_path="data/raw/current.json",
        ),
        base_directory=base_directory,
    )

    assert result == latest_earlier_capture


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
