from datetime import UTC, datetime
from pathlib import Path

import pytest

from scorenow_api_observer.markdown_report import (
    render_endpoint_report_markdown,
    render_sport_report_markdown,
)
from scorenow_api_observer.report_analysis import (
    CaptureMetadataLoadFailure,
    EventViewReportAnalysis,
    ObservedEventResolutionFailure,
    ResponseAnalysisStatusSummary,
    ResponseIssueSummary,
    SportFieldSummary,
    SportObservationSummary,
)


def test_render_endpoint_report_markdown_renders_response_analysis_statuses() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[
            ResponseAnalysisStatusSummary(status="completed", capture_count=3),
            ResponseAnalysisStatusSummary(status="invalid_json", capture_count=1),
            ResponseAnalysisStatusSummary(
                status="invalid_response_shape",
                capture_count=0,
            ),
        ],
        response_issue_summaries=[],
        sport_observation_summaries=[],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[],
    )

    result = render_endpoint_report_markdown(
        analysis=analysis,
        generated_at=datetime(2026, 9, 24, 12, 30, tzinfo=UTC),
    )

    assert result.startswith(
        "# Event View Endpoint 보고서\n\n- 생성 시각: `2026-09-24T12:30:00+00:00`\n"
    )
    assert (
        "| 상태 | Capture 수 |\n"
        "| --- | ---: |\n"
        "| `completed` | 3 |\n"
        "| `invalid_json` | 1 |\n"
        "| `invalid_response_shape` | 0 |\n"
    ) in result


def test_render_endpoint_report_markdown_renders_file_processing_overview() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[
            ResponseAnalysisStatusSummary(status="completed", capture_count=3),
            ResponseAnalysisStatusSummary(status="invalid_json", capture_count=1),
        ],
        response_issue_summaries=[],
        sport_observation_summaries=[
            SportObservationSummary(
                sport_code="baseball",
                observation_count=4,
                unique_event_count=2,
            ),
            SportObservationSummary(
                sport_code=None,
                observation_count=2,
                unique_event_count=1,
            ),
        ],
        capture_metadata_load_failures=[
            CaptureMetadataLoadFailure(
                metadata_file_path=Path("/captures/broken.json"),
                error_message="invalid metadata",
            )
        ],
        observed_event_resolution_failures=[
            ObservedEventResolutionFailure(
                observation_file_path=Path("/observations/first.json"),
                error_message="missing metadata",
            ),
            ObservedEventResolutionFailure(
                observation_file_path=Path("/observations/second.json"),
                error_message="invalid reference",
            ),
        ],
        sport_field_summaries=[],
    )

    result = render_endpoint_report_markdown(
        analysis=analysis,
        generated_at=datetime(2026, 9, 24, 12, 30, tzinfo=UTC),
    )

    assert (
        "## 파일 처리 개요\n\n"
        "| 처리 단계 | 입력 파일 수 | 처리 완료 | 처리 실패 |\n"
        "| --- | ---: | ---: | ---: |\n"
        "| CaptureMetadata 읽기 | 5 | 4 | 1 |\n"
        "| EventObservation 해석 | 8 | 6 | 2 |\n"
    ) in result


def test_render_endpoint_report_markdown_renders_failure_details_safely() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[],
        capture_metadata_load_failures=[
            CaptureMetadataLoadFailure(
                metadata_file_path=Path("/captures/meta|bad.json"),
                error_message="ValueError: invalid | shape\r\nline two <detail>",
            )
        ],
        observed_event_resolution_failures=[
            ObservedEventResolutionFailure(
                observation_file_path=Path("/observations/event\\bad.json"),
                error_message="OSError: first line\nsecond line",
            )
        ],
        sport_field_summaries=[],
    )

    result = render_endpoint_report_markdown(
        analysis=analysis,
        generated_at=datetime(2026, 9, 24, 12, 30, tzinfo=UTC),
    )

    assert (
        "## CaptureMetadata 읽기 실패\n\n"
        "| 파일 경로 | 오류 |\n"
        "| --- | --- |\n"
        "| /captures/meta\\|bad.json | "
        "ValueError: invalid \\| shape<br>line two &lt;detail&gt; |\n"
    ) in result
    assert (
        "## EventObservation 해석 실패\n\n"
        "| 파일 경로 | 오류 |\n"
        "| --- | --- |\n"
        "| /observations/event\\\\bad.json | "
        "OSError: first line<br>second line |\n"
    ) in result


def test_render_endpoint_report_markdown_describes_empty_failure_lists() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[],
    )

    result = render_endpoint_report_markdown(
        analysis=analysis,
        generated_at=datetime(2026, 9, 24, 12, 30, tzinfo=UTC),
    )

    assert "읽기에 실패한 CaptureMetadata 파일이 없습니다." in result
    assert "해석에 실패한 EventObservation 파일이 없습니다." in result
    assert "## 응답 이슈\n\n기록된 응답 이슈가 없습니다.\n" in result
    assert result.endswith("\n")
    assert not result.endswith("\n\n")


def test_render_endpoint_report_markdown_renders_response_issues() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[
            ResponseIssueSummary(
                code="duplicate_event_id",
                occurrence_count=2,
                affected_capture_count=1,
            ),
            ResponseIssueSummary(
                code="missing_requested_event",
                occurrence_count=4,
                affected_capture_count=3,
            ),
        ],
        sport_observation_summaries=[],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[],
    )

    result = render_endpoint_report_markdown(
        analysis=analysis,
        generated_at=datetime(2026, 9, 24, 12, 30, tzinfo=UTC),
    )

    assert (
        "## 응답 이슈\n\n"
        "| 이슈 코드 | 총 발생 건수 | 영향을 받은 Capture 수 |\n"
        "| --- | ---: | ---: |\n"
        "| `duplicate_event_id` | 2 | 1 |\n"
        "| `missing_requested_event` | 4 | 3 |\n"
    ) in result
    assert "기록된 응답 이슈가 없습니다." not in result


def test_render_endpoint_report_markdown_renders_sport_observation_summaries() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[
            SportObservationSummary(
                sport_code="baseball",
                observation_count=3,
                unique_event_count=2,
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
        ],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[],
    )

    result = render_endpoint_report_markdown(
        analysis=analysis,
        generated_at=datetime(2026, 9, 24, 12, 30, tzinfo=UTC),
    )

    assert (
        "## 종목별 Observation 현황\n\n"
        "| 종목 코드 | Observation 수 | 고유 이벤트 수 |\n"
        "| --- | ---: | ---: |\n"
        "| `baseball` | 3 | 2 |\n"
        "| `football` | 0 | 0 |\n"
        "| 분류 불가 | 1 | 1 |\n"
    ) in result


def test_render_sport_report_markdown_renders_selected_sport_fields() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[
            SportObservationSummary(
                sport_code="baseball",
                observation_count=4,
                unique_event_count=2,
            ),
            SportObservationSummary(
                sport_code="football",
                observation_count=1,
                unique_event_count=1,
            ),
            SportObservationSummary(
                sport_code=None,
                observation_count=0,
                unique_event_count=0,
            ),
        ],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[
            SportFieldSummary(
                sport_code="baseball",
                path="$.timer|md",
                observed_types={"null", "integer"},
                present_observation_count=4,
                always_present_event_count=1,
                sometimes_present_event_count=1,
                never_present_event_count=0,
            ),
            SportFieldSummary(
                sport_code="football",
                path="$.football_only",
                observed_types={"string"},
                present_observation_count=1,
                always_present_event_count=1,
                sometimes_present_event_count=0,
                never_present_event_count=0,
            ),
        ],
    )

    result = render_sport_report_markdown(
        analysis=analysis,
        sport_code="baseball",
        generated_at=datetime(2026, 9, 24, 12, 30, tzinfo=UTC),
    )

    assert result.startswith(
        "# Event View 종목 보고서\n\n"
        "- 종목: `baseball`\n"
        "- 생성 시각: `2026-09-24T12:30:00+00:00`\n"
    )
    assert (
        "| Observation 수 | 고유 이벤트 수 |\n| ---: | ---: |\n| 4 | 2 |\n"
    ) in result
    assert "값이 `null`이어도 해당 필드는 존재한 것으로 집계합니다." in result
    assert ("| $.timer\\|md | integer, null | 4 | 1 | 1 | 0 |\n") in result
    assert "$.football_only" not in result
    assert result.endswith("\n")
    assert not result.endswith("\n\n")


def test_render_sport_report_markdown_describes_sport_without_fields() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[
            SportObservationSummary(
                sport_code="baseball",
                observation_count=0,
                unique_event_count=0,
            )
        ],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[],
    )

    result = render_sport_report_markdown(
        analysis=analysis,
        sport_code="baseball",
        generated_at=datetime(2026, 9, 24, 12, 30, tzinfo=UTC),
    )

    assert "| 0 | 0 |" in result
    assert "관측된 필드가 없습니다." in result


def test_render_sport_report_markdown_renders_unclassified_sport() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[
            SportObservationSummary(
                sport_code=None,
                observation_count=1,
                unique_event_count=1,
            )
        ],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[],
    )

    result = render_sport_report_markdown(
        analysis=analysis,
        sport_code=None,
        generated_at=datetime(2026, 9, 24, 12, 30, tzinfo=UTC),
    )

    assert "- 종목: 분류 불가\n" in result


def test_render_sport_report_markdown_rejects_missing_sport_summary() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[],
    )

    with pytest.raises(ValueError, match="baseball"):
        render_sport_report_markdown(
            analysis=analysis,
            sport_code="baseball",
            generated_at=datetime(2026, 9, 24, 12, 30, tzinfo=UTC),
        )
