from datetime import UTC, datetime
from pathlib import Path

import pytest

from scorenow_api_observer.reporting.event_timeline import (
    EventTimelineAnalysis,
    EventTimelineRow,
    TimelineFieldChange,
    TimelineFieldFailure,
    TimelineFieldState,
)
from scorenow_api_observer.reporting.field_inspection import (
    EventFieldInspection,
    FieldInspectionAnalysis,
    FieldInspectionFailure,
    FieldPresenceChange,
    FieldValueChange,
    FieldValueTimeline,
)
from scorenow_api_observer.reporting.markdown import (
    render_endpoint_report_markdown,
    render_event_timeline_markdown,
    render_field_inspection_markdown,
    render_league_report_markdown,
    render_sport_report_markdown,
)
from scorenow_api_observer.reporting.models import (
    CaptureMetadataLoadFailure,
    EventViewReportAnalysis,
    LeagueFieldSummary,
    LeagueObservationSummary,
    LeagueTrackedFieldSummary,
    ObservedEventResolutionFailure,
    ResponseAnalysisStatusSummary,
    ResponseIssueSummary,
    SportFieldSummary,
    SportObservationSummary,
    SportTrackedFieldSummary,
    TrackedFieldUnsupportedTypeSummary,
    TrackedFieldValueSummary,
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
            SportFieldSummary(
                sport_code="baseball",
                path="$.incidents[]",
                observed_types={"object"},
                present_observation_count=1,
                always_present_event_count=0,
                sometimes_present_event_count=1,
                never_present_event_count=1,
            ),
        ],
        sport_tracked_field_summaries=[
            SportTrackedFieldSummary(
                sport_code="baseball",
                path="$.time_status",
                value_summaries=[
                    TrackedFieldValueSummary("integer", True, 1, 2, 1),
                    TrackedFieldValueSummary("string", True, "1|live", 1, 1),
                    TrackedFieldValueSummary("null", True, None, 1, 1),
                    TrackedFieldValueSummary("missing", False, None, 1, 1),
                ],
                unsupported_type_summaries=[
                    TrackedFieldUnsupportedTypeSummary("object", 1, 1)
                ],
            ),
            SportTrackedFieldSummary(
                sport_code="football",
                path="$.time_status",
                value_summaries=[TrackedFieldValueSummary("integer", True, 3, 1, 1)],
                unsupported_type_summaries=[],
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
    assert (
        "| $.timer\\|md | integer, null | 4 | 1 | 1 | 0 | "
        "`uv run observer inspect-field --sport-code baseball --path '$.timer\\|md'` |\n"
    ) in result
    assert "| $.incidents[] | object | 1 | 0 | 1 | 1 | 배열 경로 미지원 |" in result
    assert "$.football_only" not in result
    assert "## 추적 필드 값 현황" in result
    assert "### `$.time_status`" in result
    assert (
        "`uv run observer inspect-field --sport-code baseball --path '$.time_status'`"
        in result
    )
    assert "| integer | 1 | 2 | 1 |" in result
    assert '| string | "1\\|live" | 1 | 1 |' in result
    assert "| null | null | 1 | 1 |" in result
    assert "| missing | &lt;필드 없음&gt; | 1 | 1 |" in result
    assert "| object | 1 | 1 |" in result
    assert "| integer | 3 | 1 | 1 |" not in result
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


def test_render_sport_report_markdown_renders_league_comparison_and_empty_samples() -> (
    None
):
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[SportObservationSummary("baseball", 3, 2)],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[
            SportFieldSummary("baseball", "$.time_status", {"integer"}, 2, 1, 1, 0)
        ],
        league_observation_summaries=[
            LeagueObservationSummary("baseball", "225", "mlb", True, 2, 1),
            LeagueObservationSummary("baseball", "349", "kbo", True, 1, 1),
            LeagueObservationSummary("baseball", "347", "npb", True, 0, 0),
        ],
        league_field_summaries=[
            LeagueFieldSummary(
                "baseball", "225", "$.time_status", {"integer"}, 2, 1, 0, 0
            ),
            LeagueFieldSummary("baseball", "349", "$.time_status", set(), 0, 0, 0, 1),
        ],
    )

    result = render_sport_report_markdown(
        analysis=analysis,
        sport_code="baseball",
        generated_at=datetime(2026, 10, 20, 12, 30, tzinfo=UTC),
        league_report_links_by_id={
            "225": "league/baseball/mlb.md",
            "349": "league/baseball/kbo.md",
        },
    )

    assert "## 리그별 필드 제공 비교" in result
    assert "[mlb (`225`)](league/baseball/mlb.md)" in result
    assert "[kbo (`349`)](league/baseball/kbo.md)" in result
    assert "🟢 항상<br>Observation 2/2<br>이벤트 1/1" in result
    assert "⚪ 미제공<br>Observation 0/1<br>이벤트 0/1" in result
    assert "### 표본이 없는 설정 리그" in result
    assert "- `npb` (`347`)" in result


def test_render_league_report_markdown_renders_scoped_fields_and_values() -> None:
    analysis = EventViewReportAnalysis(
        response_analysis_status_summaries=[],
        response_issue_summaries=[],
        sport_observation_summaries=[],
        capture_metadata_load_failures=[],
        observed_event_resolution_failures=[],
        sport_field_summaries=[],
        league_observation_summaries=[
            LeagueObservationSummary("baseball", "349", "kbo", True, 3, 2)
        ],
        league_field_summaries=[
            LeagueFieldSummary(
                "baseball", "349", "$.scores.ot", {"string"}, 1, 0, 1, 1
            ),
            LeagueFieldSummary("football", "94", "$.ignored", {"string"}, 1, 1, 0, 0),
        ],
        league_tracked_field_summaries=[
            LeagueTrackedFieldSummary(
                sport_code="baseball",
                league_id="349",
                path="$.time_status",
                value_summaries=[
                    TrackedFieldValueSummary("integer", True, 1, 2, 1),
                    TrackedFieldValueSummary("integer", True, 3, 1, 1),
                ],
                unsupported_type_summaries=[],
            )
        ],
    )

    result = render_league_report_markdown(
        analysis=analysis,
        sport_code="baseball",
        league_id="349",
        generated_at=datetime(2026, 10, 20, 12, 30, tzinfo=UTC),
    )

    assert result.startswith("# Event View 리그 상세 보고서\n")
    assert "- 리그 ID: `349`" in result
    assert "- 설정 label: `kbo`" in result
    assert "- 설정 등록 여부: 등록" in result
    assert "| 3 | 2 |" in result
    assert "| $.scores.ot | string | 1 | 0 | 1 | 1 |" in result
    assert "$.ignored" not in result
    assert "### `$.time_status`" in result
    assert "| integer | 3 | 1 | 1 |" in result
    assert "관측된 API 리그명" not in result


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


def test_render_field_inspection_markdown_renders_nested_object_timeline() -> None:
    initial_time = datetime(2026, 10, 20, 12, 30, tzinfo=UTC)
    appeared_time = datetime(2026, 10, 20, 12, 31, tzinfo=UTC)
    analysis = FieldInspectionAnalysis(
        sport_code="baseball",
        requested_path="$.scores.10",
        event_id_filter="123",
        input_observation_count=2,
        analyzed_observation_count=2,
        input_event_count=1,
        events=[
            EventFieldInspection(
                event_id="123",
                input_observation_count=2,
                analyzed_observation_count=2,
                object_presence_changes=[
                    FieldPresenceChange(
                        captured_at=initial_time,
                        raw_file_path=Path("data/raw/first.json"),
                        kind="initial",
                        present=False,
                    ),
                    FieldPresenceChange(
                        captured_at=appeared_time,
                        raw_file_path=Path("data/raw/second.json"),
                        kind="appeared",
                        present=True,
                    ),
                ],
                value_timelines=[
                    FieldValueTimeline(
                        path="$.scores.10.home",
                        changes=[
                            FieldValueChange(
                                captured_at=initial_time,
                                raw_file_path=Path("data/raw/first.json"),
                                kind="initial",
                                previous_present=False,
                                previous_value=None,
                                current_present=False,
                                current_value=None,
                            ),
                            FieldValueChange(
                                captured_at=appeared_time,
                                raw_file_path=Path("data/raw/second.json"),
                                kind="appeared",
                                previous_present=False,
                                previous_value=None,
                                current_present=True,
                                current_value="1",
                            ),
                        ],
                    )
                ],
            )
        ],
        resolution_failures=[],
        field_failures=[
            FieldInspectionFailure(
                event_id="123",
                captured_at=appeared_time,
                raw_file_path=Path("data/raw/array.json"),
                error_message="$.scores.10.items에서 배열이 발견됨",
            )
        ],
    )

    result = render_field_inspection_markdown(
        analysis=analysis,
        generated_at=datetime(2026, 10, 20, 13, 0, tzinfo=UTC),
    )

    assert result.startswith("# Event View 필드 변화 보고서\n")
    assert "- 요청 경로: `$.scores.10`" in result
    assert "| 1 | 1 | 0 |" in result
    assert "### 이벤트 `123`" in result
    assert "#### `$.scores.10` 객체 존재 변화" in result
    assert "#### `$.scores.10.home`" in result
    assert "<필드 없음>" in result
    assert '등장 | &lt;필드 없음&gt; | "1" | data/raw/second.json' in result
    assert "$.scores.10.items에서 배열이 발견됨" in result
    assert result.endswith("\n")


def test_render_field_inspection_markdown_describes_explicit_event_without_field() -> (
    None
):
    analysis = FieldInspectionAnalysis(
        sport_code="baseball",
        requested_path="$.scores.10",
        event_id_filter="123",
        input_observation_count=3,
        analyzed_observation_count=3,
        input_event_count=1,
        events=[],
        resolution_failures=[],
        field_failures=[],
    )

    result = render_field_inspection_markdown(
        analysis=analysis,
        generated_at=datetime(2026, 10, 20, 13, 0, tzinfo=UTC),
    )

    assert "| 1 | 0 | 1 |" in result
    assert (
        "이벤트 `123`에서는 `$.scores.10` 경로가 한 번도 관측되지 않았습니다." in result
    )


def test_render_event_timeline_markdown_renders_all_row_kinds() -> None:
    initial_time = datetime(2026, 10, 20, 12, 30, tzinfo=UTC)
    analysis = EventTimelineAnalysis(
        event_id="123",
        sport_code="baseball",
        configured_paths=("$.time_status", "$.scores"),
        input_observation_count=4,
        analyzed_observation_count=3,
        rows=[
            EventTimelineRow(
                captured_at=initial_time,
                raw_file_path=Path("data/raw/initial.json"),
                kind="initial",
                initial_states=[
                    TimelineFieldState(
                        path="$.time_status",
                        kind="scalar",
                        value=1,
                    ),
                    TimelineFieldState(path="$.scores", kind="object"),
                    TimelineFieldState(
                        path="$.scores.10.home",
                        kind="missing",
                    ),
                ],
                changes=[],
                failures=[],
            ),
            EventTimelineRow(
                captured_at=initial_time,
                raw_file_path=Path("data/raw/unchanged.json"),
                kind="unchanged",
                initial_states=[],
                changes=[],
                failures=[],
            ),
            EventTimelineRow(
                captured_at=initial_time,
                raw_file_path=Path("data/raw/changed.json"),
                kind="changed",
                initial_states=[],
                changes=[
                    TimelineFieldChange(
                        path="$.scores.10.home",
                        previous=TimelineFieldState(
                            path="$.scores.10.home",
                            kind="missing",
                        ),
                        current=TimelineFieldState(
                            path="$.scores.10.home",
                            kind="scalar",
                            value="1|0",
                        ),
                    )
                ],
                failures=[],
            ),
            EventTimelineRow(
                captured_at=initial_time,
                raw_file_path=Path("data/raw/failed.json"),
                kind="failed",
                initial_states=[],
                changes=[],
                failures=[
                    TimelineFieldFailure(
                        path="$.scores",
                        error_message="배열 값",
                    )
                ],
            ),
        ],
        resolution_failures=[],
    )

    result = render_event_timeline_markdown(
        analysis=analysis,
        generated_at=datetime(2026, 10, 20, 13, 0, tzinfo=UTC),
    )

    assert result.startswith("# Event View 이벤트 타임라인 보고서\n")
    assert "- 이벤트 ID: `123`" in result
    assert "| 4 | 3 | 1 | 1 |" in result
    assert "최초 상태<br>`$.time_status` = 1" in result
    assert "`$.scores` = &lt;객체&gt;" in result
    assert "`$.scores.10.home` = &lt;필드 없음&gt;" in result
    assert "|  | 변화 없음 | data/raw/unchanged.json |" in result
    assert '| 🟠 | `$.scores.10.home`: &lt;필드 없음&gt; → "1\\|0"' in result
    assert "| 🔴 | `$.scores`: 배열 값 | data/raw/failed.json |" in result
    assert result.endswith("\n")
