from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from scorenow_api_observer import cli
from scorenow_api_observer.collector import CaptureResult
from scorenow_api_observer.comparison import CaptureComparison, StructureComparison
from scorenow_api_observer.models import CaptureMetadata, StructureChangeRecord


class _FakeSettings:
    bets_api_base_url = "https://example.test"
    bets_api_token = SecretStr("test-token")


def _capture(
    *,
    captured_at: datetime,
    raw_file_path: str,
) -> CaptureMetadata:
    return CaptureMetadata(
        captured_at=captured_at,
        provider="betsapi",
        endpoint="/v1/event/view",
        http_method="GET",
        requested_event_ids=["123"],
        returned_event_ids=["123"],
        response_issues=[],
        http_status_code=200,
        elapsed_ms=100,
        response_size_bytes=100,
        content_type="application/json",
        raw_file_path=raw_file_path,
    )


def _capture_result(current_capture: CaptureMetadata) -> CaptureResult:
    return CaptureResult(
        response=httpx.Response(200, json={"success": 1}),
        raw_file_path=Path(current_capture.raw_file_path),
        metadata_file_path=Path("data/metadata/current.json"),
        metadata=current_capture,
    )


def _comparison(
    current_capture: CaptureMetadata,
    structure_comparison: StructureComparison,
) -> CaptureComparison:
    return CaptureComparison(
        event_id="123",
        previous_capture=_capture(
            captured_at=datetime(2026, 9, 15, 9, 59, tzinfo=UTC),
            raw_file_path="data/raw/previous.json",
        ),
        current_capture=current_capture,
        structure_comparison=structure_comparison,
    )


def test_watch_waits_between_captures_when_structure_has_not_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_capture = _capture(
        captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    capture_result = _capture_result(current_capture)
    comparison = _comparison(current_capture, StructureComparison([], [], []))
    sleep_calls: list[float] = []
    saved_records: list[StructureChangeRecord] = []

    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(cli, "capture_event_view", lambda **_kwargs: capture_result)
    monkeypatch.setattr(
        cli,
        "compare_with_previous_capture",
        lambda _event_id, _current_capture: comparison,
    )
    monkeypatch.setattr(cli.time, "sleep", sleep_calls.append)
    monkeypatch.setattr(
        cli,
        "save_structure_change_record",
        lambda record: saved_records.append(record),
    )

    result = CliRunner().invoke(
        cli.app,
        ["watch", "--event-id", "123", "--interval", "7", "--count", "2"],
    )

    assert result.exit_code == 0
    assert sleep_calls == [7]
    assert saved_records == []


def test_watch_saves_structure_change_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_capture = _capture(
        captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    capture_result = _capture_result(current_capture)
    comparison = _comparison(
        current_capture,
        StructureComparison(added_paths=["$.new"], removed_paths=[], type_changes=[]),
    )
    saved_records: list[StructureChangeRecord] = []
    expected_path = Path("data/changes/event-view/2026-09-15/current.json")

    def save_record(record: StructureChangeRecord) -> Path:
        saved_records.append(record)
        return expected_path

    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(cli, "capture_event_view", lambda **_kwargs: capture_result)
    monkeypatch.setattr(
        cli,
        "compare_with_previous_capture",
        lambda _event_id, _current_capture: comparison,
    )
    monkeypatch.setattr(cli, "save_structure_change_record", save_record)

    result = CliRunner().invoke(
        cli.app,
        ["watch", "--event-id", "123", "--count", "1"],
    )

    assert result.exit_code == 0
    assert len(saved_records) == 1
    assert saved_records[0].event_id == "123"
    assert saved_records[0].current_captured_at == current_capture.captured_at
    assert f"응답 구조 변화 기록 위치: {expected_path}" in result.output


def test_watch_continues_after_structure_change_record_save_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_capture = _capture(
        captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    capture_result = _capture_result(current_capture)
    comparison = _comparison(
        current_capture,
        StructureComparison(added_paths=["$.new"], removed_paths=[], type_changes=[]),
    )
    capture_count = 0
    sleep_calls: list[float] = []

    def capture_event_view(**_kwargs: str) -> CaptureResult:
        nonlocal capture_count
        capture_count += 1
        return capture_result

    def fail_to_save(_record: StructureChangeRecord) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(cli, "capture_event_view", capture_event_view)
    monkeypatch.setattr(
        cli,
        "compare_with_previous_capture",
        lambda _event_id, _current_capture: comparison,
    )
    monkeypatch.setattr(cli, "save_structure_change_record", fail_to_save)
    monkeypatch.setattr(cli.time, "sleep", sleep_calls.append)

    result = CliRunner().invoke(
        cli.app,
        ["watch", "--event-id", "123", "--interval", "7", "--count", "2"],
    )

    assert result.exit_code == 0
    assert capture_count == 2
    assert sleep_calls == [7]
    assert "응답 구조 변화 저장에 실패하였습니다." in result.output
