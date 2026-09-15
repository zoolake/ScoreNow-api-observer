import json
from datetime import UTC, datetime
from pathlib import Path

from scorenow_api_observer.models import (
    CaptureMetadata,
    StructureChangeRecord,
    TypeChangeRecord,
)
from scorenow_api_observer.storage import (
    save_capture_metadata,
    save_raw_response,
    save_structure_change_record,
)


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
        event_id=event_id,
        response_body=response_body,
        captured_at=captured_at,
        base_directory=tmp_path / "raw",
    )

    metadata = CaptureMetadata(
        captured_at=captured_at,
        provider="betsapi",
        endpoint="v1/event/view",
        http_method="GET",
        event_ids=[event_id],
        http_status_code=200,
        elapsed_ms=182.47,
        response_size_bytes=len(response_body),
        content_type="application/json",
        raw_file_path=str(raw_path),
    )

    metadata_path = save_capture_metadata(metadata, tmp_path / "metadata")

    # then
    expected_file_name = "20260909T150000000000Z_event-1234567.json"

    assert raw_path == (tmp_path / "raw" / "2026-09-09" / expected_file_name)
    assert metadata_path == (tmp_path / "metadata" / "2026-09-09" / expected_file_name)

    assert raw_path.read_bytes() == response_body

    saved_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert saved_metadata["provider"] == "betsapi"
    assert saved_metadata["event_ids"] == ["1234567"]
    assert saved_metadata["http_status_code"] == 200
    assert saved_metadata["response_size_bytes"] == len(response_body)
    assert saved_metadata["raw_file_path"] == str(raw_path)


def test_save_structure_change_record_uses_current_capture_date_and_file_name(
    tmp_path: Path,
) -> None:
    record = StructureChangeRecord(
        detected_at=datetime(2026, 9, 10, 1, 0, tzinfo=UTC),
        event_id="1234567",
        previous_captured_at=datetime(2026, 9, 8, 14, 59, tzinfo=UTC),
        current_captured_at=datetime(2026, 9, 9, 15, 0, tzinfo=UTC),
        previous_raw_file_path=(
            "data/raw/event-view/2026-09-08/20260908T145900000000Z_event-1234567.json"
        ),
        current_raw_file_path=(
            "data/raw/event-view/2026-09-09/20260909T150000000000Z_event-1234567.json"
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
        / "2026-09-09"
        / "20260909T150000000000Z_event-1234567.json"
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
    existing_path = tmp_path / "changes" / "2026-09-09" / "current.json"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text("existing contents", encoding="utf-8")

    saved_path = save_structure_change_record(record, tmp_path / "changes")

    assert saved_path == existing_path
    assert existing_path.read_text(encoding="utf-8") == "existing contents"
