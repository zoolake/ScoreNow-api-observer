from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from scorenow_api_observer import cli
from scorenow_api_observer.event_view.collector import (
    CaptureResult,
    EventObservationSaveFailure,
)
from scorenow_api_observer.event_view.comparison import (
    CaptureComparison,
    StructureComparison,
)
from scorenow_api_observer.event_view.models import (
    CaptureMetadata,
    EventObservation,
    StructureChangeRecord,
)
from scorenow_api_observer.event_view.observation import (
    InvalidEventObservationReferenceError,
)
from scorenow_api_observer.reporting.field_inspection import (
    EventFieldInspection,
    FieldInspectionAnalysis,
    FieldValueChange,
    FieldValueTimeline,
)
from scorenow_api_observer.reporting.models import (
    CaptureMetadataLoadFailure,
    EventViewReportAnalysis,
    ObservedEventResolutionFailure,
    ObservedEventResolutionResult,
    SportObservationSummary,
)
from scorenow_api_observer.reporting.tracked_field_config import (
    TrackedFieldsConfig,
)


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
        response_analysis_status="completed",
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


def _capture_result(
    current_capture: CaptureMetadata,
    *,
    observation_save_failures: list[EventObservationSaveFailure] | None = None,
    event_observations: list[EventObservation] | None = None,
) -> CaptureResult:
    metadata_file_path = Path("data/metadata/current.json")
    if event_observations is None:
        event_observations = [
            EventObservation(
                event_id="123",
                capture_metadata_file_path=str(metadata_file_path),
                result_index=0,
            )
        ]

    return CaptureResult(
        response=httpx.Response(200, json={"success": 1}),
        raw_file_path=Path(current_capture.raw_file_path),
        metadata_file_path=metadata_file_path,
        metadata=current_capture,
        observation_save_failures=observation_save_failures or [],
        event_observations=event_observations,
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


def test_collect_exits_when_capture_storage_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_capture(**_kwargs: str) -> CaptureResult:
        raise OSError("disk full")

    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(cli, "capture_event_view", fail_to_capture)

    result = CliRunner().invoke(
        cli.app,
        ["collect", "--event-ids", "123"],
    )

    assert result.exit_code == 1
    assert "파일 저장에 실패했습니다." in result.output


def test_collect_normalizes_multiple_event_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_capture = _capture(
        captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    capture_result = _capture_result(current_capture)
    captured_requested_event_ids: list[list[str]] = []

    def capture_event_view(
        *,
        base_url: str,
        token: str,
        requested_event_ids: list[str],
    ) -> CaptureResult:
        captured_requested_event_ids.append(requested_event_ids)
        return capture_result

    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(cli, "capture_event_view", capture_event_view)

    result = CliRunner().invoke(
        cli.app,
        ["collect", "--event-ids", " B, A, B "],
    )

    assert result.exit_code == 0
    assert captured_requested_event_ids == [["A", "B"]]


def test_collect_rejects_invalid_event_ids_before_loading_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_loaded = False

    def load_settings() -> _FakeSettings:
        nonlocal settings_loaded
        settings_loaded = True
        return _FakeSettings()

    monkeypatch.setattr(cli, "Settings", load_settings)

    result = CliRunner().invoke(
        cli.app,
        ["collect", "--event-ids", "A,,B"],
    )

    assert result.exit_code == 2
    assert not settings_loaded
    assert "이벤트 ID 입력이 올바르지 않습니다." in result.output


def test_compare_compares_latest_event_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_observation = EventObservation(
        event_id="123",
        capture_metadata_file_path="data/metadata/previous.json",
        result_index=0,
    )
    current_observation = EventObservation(
        event_id="123",
        capture_metadata_file_path="data/metadata/current.json",
        result_index=1,
    )
    current_capture = _capture(
        captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    comparison = _comparison(
        current_capture,
        StructureComparison(added_paths=["$.new"], removed_paths=[], type_changes=[]),
    )
    compared_observations: list[tuple[EventObservation, EventObservation]] = []

    def find_latest_observations(event_id: str) -> list[EventObservation]:
        assert event_id == "123"
        return [previous_observation, current_observation]

    def compare_observations(
        previous: EventObservation,
        current: EventObservation,
    ) -> CaptureComparison:
        compared_observations.append((previous, current))
        return comparison

    monkeypatch.setattr(cli, "find_latest_observations", find_latest_observations)
    monkeypatch.setattr(cli, "compare_observations", compare_observations)

    result = CliRunner().invoke(
        cli.app,
        ["compare", "--event-id", "123"],
    )

    assert result.exit_code == 0
    assert compared_observations == [(previous_observation, current_observation)]
    assert "경기 ID: 123" in result.output
    assert "직전 응답: 2026-09-15T09:59:00+00:00" in result.output
    assert "최신 응답: 2026-09-15T10:00:00+00:00" in result.output
    assert "이번 응답에서 새로 보이는 경로: 1개" in result.output


def test_compare_exits_when_observation_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_find_observations(_event_id: str) -> list[EventObservation]:
        raise OSError("metadata missing")

    monkeypatch.setattr(
        cli,
        "find_latest_observations",
        fail_to_find_observations,
    )

    result = CliRunner().invoke(
        cli.app,
        ["compare", "--event-id", "123"],
    )

    assert result.exit_code == 1
    assert "이벤트 구조 비교 과정 중에 예외가 발생했습니다." in result.output
    assert "metadata missing" in result.output


def test_watch_continues_after_capture_storage_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_capture = _capture(
        captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    capture_result = _capture_result(current_capture)
    capture_count = 0
    sleep_calls: list[float] = []

    def capture_event_view(**_kwargs: str) -> CaptureResult:
        nonlocal capture_count
        capture_count += 1
        if capture_count == 1:
            raise OSError("disk full")
        return capture_result

    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(cli, "capture_event_view", capture_event_view)
    monkeypatch.setattr(
        cli,
        "compare_with_previous_observation",
        lambda _current_observation: None,
    )
    monkeypatch.setattr(cli.time, "sleep", sleep_calls.append)

    result = CliRunner().invoke(
        cli.app,
        ["watch", "--event-ids", "123", "--interval", "7", "--count", "2"],
    )

    assert result.exit_code == 0
    assert capture_count == 2
    assert sleep_calls == [7]
    assert "파일 저장에 실패했습니다." in result.output
    assert "호출: 2회 / 저장: 1개" in result.output


def test_watch_compares_observation_after_observation_save_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_capture = _capture(
        captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    capture_result = _capture_result(
        current_capture,
        observation_save_failures=[
            EventObservationSaveFailure(
                event_id="123",
                error_message="disk full",
            )
        ],
    )
    compared_observations: list[EventObservation] = []

    def compare_with_previous_observation(observation: EventObservation) -> None:
        compared_observations.append(observation)

    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(cli, "capture_event_view", lambda **_kwargs: capture_result)
    monkeypatch.setattr(
        cli,
        "compare_with_previous_observation",
        compare_with_previous_observation,
    )

    result = CliRunner().invoke(
        cli.app,
        ["watch", "--event-ids", "123", "--count", "1"],
    )

    assert result.exit_code == 0
    assert compared_observations == capture_result.event_observations
    assert "Event Observation 저장에 실패한 1 건이 존재합니다." in result.output
    assert "실패 Event ID:123 / 사유: disk full" in result.output


def test_watch_compares_each_event_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_capture = _capture(
        captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    event_observations = [
        EventObservation(
            event_id="A",
            capture_metadata_file_path="data/metadata/current.json",
            result_index=0,
        ),
        EventObservation(
            event_id="C",
            capture_metadata_file_path="data/metadata/current.json",
            result_index=1,
        ),
    ]
    capture_result = _capture_result(
        current_capture,
        event_observations=event_observations,
    )
    compared_observations: list[EventObservation] = []

    def compare_with_previous_observation(observation: EventObservation) -> None:
        compared_observations.append(observation)

    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(cli, "capture_event_view", lambda **_kwargs: capture_result)
    monkeypatch.setattr(
        cli,
        "compare_with_previous_observation",
        compare_with_previous_observation,
    )

    result = CliRunner().invoke(
        cli.app,
        ["watch", "--event-ids", "123", "--count", "1"],
    )

    assert result.exit_code == 0
    assert compared_observations == event_observations


def test_watch_continues_with_next_observation_after_comparison_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_capture = _capture(
        captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        raw_file_path="data/raw/current.json",
    )
    event_observations = [
        EventObservation(
            event_id="A",
            capture_metadata_file_path="data/metadata/current.json",
            result_index=0,
        ),
        EventObservation(
            event_id="C",
            capture_metadata_file_path="data/metadata/current.json",
            result_index=1,
        ),
    ]
    capture_result = _capture_result(
        current_capture,
        event_observations=event_observations,
    )
    compared_event_ids: list[str] = []

    def compare_with_previous_observation(observation: EventObservation) -> None:
        compared_event_ids.append(observation.event_id)
        if observation.event_id == "A":
            raise InvalidEventObservationReferenceError("invalid reference")

    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(cli, "capture_event_view", lambda **_kwargs: capture_result)
    monkeypatch.setattr(
        cli,
        "compare_with_previous_observation",
        compare_with_previous_observation,
    )

    result = CliRunner().invoke(
        cli.app,
        ["watch", "--event-ids", "123", "--count", "1"],
    )

    assert result.exit_code == 0
    assert compared_event_ids == ["A", "C"]
    assert (
        "경기 ID A의 저장된 응답을 읽거나 비교하는데 실패하였습니다." in result.output
    )
    assert "경기 ID C의 직전 응답이 없어 구조 비교를 생략합니다." in result.output


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
        "compare_with_previous_observation",
        lambda _current_observation: comparison,
    )
    monkeypatch.setattr(cli.time, "sleep", sleep_calls.append)
    monkeypatch.setattr(
        cli,
        "save_structure_change_record",
        lambda record: saved_records.append(record),
    )

    result = CliRunner().invoke(
        cli.app,
        ["watch", "--event-ids", "123", "--interval", "7", "--count", "2"],
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
        "compare_with_previous_observation",
        lambda _current_observation: comparison,
    )
    monkeypatch.setattr(cli, "save_structure_change_record", save_record)

    result = CliRunner().invoke(
        cli.app,
        ["watch", "--event-ids", "123", "--count", "1"],
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
        "compare_with_previous_observation",
        lambda _current_observation: comparison,
    )
    monkeypatch.setattr(cli, "save_structure_change_record", fail_to_save)
    monkeypatch.setattr(cli.time, "sleep", sleep_calls.append)

    result = CliRunner().invoke(
        cli.app,
        ["watch", "--event-ids", "123", "--interval", "7", "--count", "2"],
    )

    assert result.exit_code == 0
    assert capture_count == 2
    assert sleep_calls == [7]
    assert "응답 구조 변화 저장에 실패하였습니다." in result.output


def test_report_creates_endpoint_and_all_sport_reports_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_at = datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
    metadata_paths = [Path("data/metadata/first.json")]
    observation_paths = [Path("data/observations/first.json")]
    sport_code_by_id = {"1": "football", "16": "baseball"}
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[
            SportObservationSummary("baseball", 2, 1),
            SportObservationSummary("football", 0, 0),
            SportObservationSummary(None, 1, 1),
        ],
        capture_metadata_load_failures=[
            CaptureMetadataLoadFailure(
                metadata_file_path=Path("data/metadata/broken.json"),
                error_message="invalid metadata",
            )
        ],
        observed_event_resolution_failures=[
            ObservedEventResolutionFailure(
                observation_file_path=Path("data/observations/broken.json"),
                error_message="invalid observation",
            )
        ],
        sport_field_summaries=[],
    )
    tracked_field_paths = {
        "baseball": ("$.time_status",),
        "football": ("$.timer.md", "$.time_status"),
    }
    analyzed_arguments: list[
        tuple[list[Path], list[Path], dict[str, str], dict[str, tuple[str, ...]]]
    ] = []
    rendered_sports: list[tuple[str | None, datetime]] = []
    built_report_names: list[str] = []
    saved_reports: list[tuple[str, Path]] = []

    class FixedDateTime:
        @classmethod
        def now(cls, tz: object) -> datetime:
            assert tz is UTC
            return generated_at

    def analyze_report(
        *,
        metadata_file_paths: list[Path],
        observation_file_paths: list[Path],
        sport_code_by_id: dict[str, str],
        tracked_field_paths_by_sport_code: dict[str, tuple[str, ...]],
    ) -> EventViewReportAnalysis:
        analyzed_arguments.append(
            (
                metadata_file_paths,
                observation_file_paths,
                sport_code_by_id,
                tracked_field_paths_by_sport_code,
            )
        )
        return analysis

    def render_sport_report(
        *,
        analysis: EventViewReportAnalysis,
        sport_code: str | None,
        generated_at: datetime,
    ) -> str:
        assert analysis is not None
        rendered_sports.append((sport_code, generated_at))
        return f"sport report: {sport_code}\n"

    def build_output_path(*, generated_at: datetime, report_name: str) -> Path:
        assert generated_at == datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
        built_report_names.append(report_name)
        return Path("reports") / f"{report_name}.md"

    def save_report(*, content: str, output_path: Path) -> Path:
        saved_reports.append((content, output_path))
        return output_path

    monkeypatch.setattr(cli, "datetime", FixedDateTime)
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: pytest.fail("report 명령은 API 설정을 읽으면 안 됩니다."),
    )
    monkeypatch.setattr(cli, "find_capture_metadata_paths", lambda: metadata_paths)
    monkeypatch.setattr(cli, "find_event_observation_paths", lambda: observation_paths)
    monkeypatch.setattr(cli, "load_sport_codes_by_id", lambda: sport_code_by_id)
    monkeypatch.setattr(
        cli,
        "load_tracked_fields_config",
        lambda: TrackedFieldsConfig(paths_by_sport_code=tracked_field_paths),
    )
    monkeypatch.setattr(cli, "analyze_event_view_report", analyze_report)
    monkeypatch.setattr(
        cli,
        "render_endpoint_report_markdown",
        lambda **_kwargs: "endpoint report\n",
    )
    monkeypatch.setattr(cli, "render_sport_report_markdown", render_sport_report)
    monkeypatch.setattr(cli, "build_report_output_path", build_output_path)
    monkeypatch.setattr(cli, "save_report_text", save_report)

    result = CliRunner().invoke(cli.app, ["report"])

    assert result.exit_code == 0
    assert analyzed_arguments == [
        (metadata_paths, observation_paths, sport_code_by_id, tracked_field_paths)
    ]
    assert rendered_sports == [
        ("baseball", generated_at),
        ("football", generated_at),
        (None, generated_at),
    ]
    assert built_report_names == [
        "endpoint",
        "sport_baseball",
        "sport_football",
        "sport_unclassified",
    ]
    assert [path for _, path in saved_reports] == [
        Path("reports/endpoint.md"),
        Path("reports/sport_baseball.md"),
        Path("reports/sport_football.md"),
        Path("reports/sport_unclassified.md"),
    ]
    assert "endpoint 보고서 저장 위치: reports/endpoint.md" in result.output
    assert "sport_unclassified 보고서 저장 위치" in result.output
    assert "일부 저장 파일을 분석하지 못했습니다." in result.output
    assert "CaptureMetadata 1건, EventObservation 1건" in result.output


def test_report_rejects_safe_file_name_collision_before_saving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[
            SportObservationSummary("unclassified", 0, 0),
            SportObservationSummary(None, 0, 0),
        ],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[],
    )
    save_called = False

    def save_report(**_kwargs: object) -> Path:
        nonlocal save_called
        save_called = True
        return Path("unused")

    monkeypatch.setattr(cli, "load_sport_codes_by_id", dict)
    monkeypatch.setattr(
        cli,
        "load_tracked_fields_config",
        lambda: TrackedFieldsConfig(paths_by_sport_code={}),
    )
    monkeypatch.setattr(cli, "find_capture_metadata_paths", list)
    monkeypatch.setattr(cli, "find_event_observation_paths", list)
    monkeypatch.setattr(cli, "analyze_event_view_report", lambda **_kwargs: analysis)
    monkeypatch.setattr(
        cli,
        "render_endpoint_report_markdown",
        lambda **_kwargs: "endpoint\n",
    )
    monkeypatch.setattr(
        cli,
        "render_sport_report_markdown",
        lambda **_kwargs: "sport\n",
    )
    monkeypatch.setattr(
        cli,
        "build_report_output_path",
        lambda *, generated_at, report_name: Path(f"reports/{report_name}.md"),
    )
    monkeypatch.setattr(cli, "save_report_text", save_report)

    result = CliRunner().invoke(cli.app, ["report"])

    assert result.exit_code == 1
    assert not save_called
    assert "안전한 파일명으로 변환한 결과가 중복됩니다." in result.output


def test_report_exits_when_sport_config_cannot_be_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_load_sport_config() -> dict[str, str]:
        raise OSError("config missing")

    monkeypatch.setattr(cli, "load_sport_codes_by_id", fail_to_load_sport_config)

    result = CliRunner().invoke(cli.app, ["report"])

    assert result.exit_code == 1
    assert "보고서 생성에 실패했습니다. config missing" in result.output


def test_report_exits_when_tracked_fields_config_cannot_be_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_load_tracked_fields_config() -> TrackedFieldsConfig:
        raise ValueError("tracked fields invalid")

    monkeypatch.setattr(cli, "load_sport_codes_by_id", dict)
    monkeypatch.setattr(
        cli,
        "load_tracked_fields_config",
        fail_to_load_tracked_fields_config,
    )

    result = CliRunner().invoke(cli.app, ["report"])

    assert result.exit_code == 1
    assert "보고서 생성에 실패했습니다. tracked fields invalid" in result.output


def test_inspect_field_creates_report_from_stored_observations_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_at = datetime(2026, 10, 20, 12, 30, tzinfo=UTC)
    observation_paths = [Path("data/observations/123/first.json")]
    analysis = FieldInspectionAnalysis(
        sport_code="baseball",
        requested_path="$.time_status",
        event_id_filter="123",
        input_observation_count=1,
        analyzed_observation_count=1,
        input_event_count=1,
        events=[
            EventFieldInspection(
                event_id="123",
                input_observation_count=1,
                analyzed_observation_count=1,
                object_presence_changes=[],
                value_timelines=[
                    FieldValueTimeline(
                        path="$.time_status",
                        changes=[
                            FieldValueChange(
                                captured_at=generated_at,
                                raw_file_path=Path("data/raw/first.json"),
                                kind="initial",
                                previous_present=False,
                                previous_value=None,
                                current_present=True,
                                current_value="1",
                            )
                        ],
                    )
                ],
            )
        ],
        resolution_failures=[],
        field_failures=[],
    )
    analyzed_arguments: list[tuple[str, str, str | None]] = []
    output_path = Path("reports/event-view/field/baseball/report.md")

    class FixedDateTime:
        @classmethod
        def now(cls, tz: object) -> datetime:
            assert tz is UTC
            return generated_at

    def analyze_field(**kwargs: object) -> FieldInspectionAnalysis:
        analyzed_arguments.append(
            (
                str(kwargs["sport_code"]),
                str(kwargs["path"]),
                str(kwargs["event_id"]) if kwargs["event_id"] is not None else None,
            )
        )
        return analysis

    monkeypatch.setattr(cli, "datetime", FixedDateTime)
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: pytest.fail("inspect-field 명령은 API 설정을 읽으면 안 됩니다."),
    )
    monkeypatch.setattr(cli, "load_sport_codes_by_id", lambda: {"16": "baseball"})
    monkeypatch.setattr(
        cli,
        "find_event_observation_paths",
        lambda: observation_paths,
    )
    monkeypatch.setattr(
        cli,
        "resolve_observed_events",
        lambda **_kwargs: ObservedEventResolutionResult([], []),
    )
    monkeypatch.setattr(cli, "analyze_field_inspection", analyze_field)
    monkeypatch.setattr(
        cli,
        "render_field_inspection_markdown",
        lambda **_kwargs: "field report\n",
    )
    monkeypatch.setattr(
        cli,
        "build_field_report_output_path",
        lambda **_kwargs: output_path,
    )
    monkeypatch.setattr(
        cli,
        "save_report_text",
        lambda *, content, output_path: output_path,
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "inspect-field",
            "--sport-code",
            "BASEBALL",
            "--event-id",
            "123",
            "--path",
            "$.time_status",
        ],
    )

    assert result.exit_code == 0
    assert analyzed_arguments == [("baseball", "$.time_status", "123")]
    assert "입력 Observation: 1개" in result.output
    assert "분석 범위 이벤트: 1개" in result.output
    assert "필드 관측 이벤트: 1개" in result.output
    assert "미관측으로 생략한 이벤트: 0개" in result.output
    assert f"필드 분석 보고서 저장 위치: {output_path}" in result.output


def test_inspect_field_rejects_array_path_before_loading_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations_searched = False

    def find_observations() -> list[Path]:
        nonlocal observations_searched
        observations_searched = True
        return []

    monkeypatch.setattr(cli, "find_event_observation_paths", find_observations)

    result = CliRunner().invoke(
        cli.app,
        [
            "inspect-field",
            "--sport-code",
            "baseball",
            "--path",
            "$.incidents[]",
        ],
    )

    assert result.exit_code == 2
    assert not observations_searched
    assert "배열을 포함한 필드 경로는 지원하지 않습니다." in result.output
