import json
import shlex
from datetime import datetime
from html import escape

from jinja2 import Environment, PackageLoader, StrictUndefined

from scorenow_api_observer.reporting.analysis import EventViewReportAnalysis
from scorenow_api_observer.reporting.field_inspection import (
    FieldInspectionAnalysis,
)
from scorenow_api_observer.reporting.field_path import JsonScalar


def _escape_markdown_table_cell(value: object) -> str:
    """동적 값을 Markdown 표의 단일 셀에 안전하게 표시합니다."""

    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = escape(text, quote=False)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _create_markdown_environment() -> Environment:
    """패키지의 Markdown 템플릿을 읽는 공통 Jinja 환경을 만듭니다."""

    environment = Environment(
        loader=PackageLoader("scorenow_api_observer.reporting", "templates/markdown"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    environment.filters["markdown_table_cell"] = _escape_markdown_table_cell
    environment.filters["field_value"] = _format_field_value
    environment.filters["inspect_field_command"] = _build_inspect_field_command
    return environment


def _format_field_value(present: bool, value: JsonScalar) -> str:
    """필드의 누락 여부와 JSON 단일 값을 서로 구분하여 표시합니다."""

    if not present:
        return "<필드 없음>"
    return json.dumps(value, ensure_ascii=False)


def _build_inspect_field_command(path: str, sport_code: str) -> str:
    """종목 보고서의 필드 경로를 다시 분석할 CLI 명령을 만듭니다."""

    return shlex.join(
        [
            "uv",
            "run",
            "observer",
            "inspect-field",
            "--sport-code",
            sport_code,
            "--path",
            path,
        ]
    )


_MARKDOWN_ENVIRONMENT = _create_markdown_environment()


def render_endpoint_report_markdown(
    *,
    analysis: EventViewReportAnalysis,
    generated_at: datetime,
) -> str:
    """Event View endpoint 전체 분석 결과를 Markdown 문자열로 렌더링합니다."""

    loaded_capture_metadata_count = sum(
        summary.capture_count for summary in analysis.response_analysis_status_summaries
    )
    capture_metadata_load_failure_count = len(analysis.capture_metadata_load_failures)
    resolved_event_observation_count = sum(
        summary.observation_count for summary in analysis.sport_observation_summaries
    )
    event_observation_resolution_failure_count = len(
        analysis.observed_event_resolution_failures
    )

    template = _MARKDOWN_ENVIRONMENT.get_template("event_view_endpoint.md.jinja")
    return template.render(
        analysis=analysis,
        generated_at=generated_at,
        capture_metadata_input_count=(
            loaded_capture_metadata_count + capture_metadata_load_failure_count
        ),
        loaded_capture_metadata_count=loaded_capture_metadata_count,
        capture_metadata_load_failure_count=capture_metadata_load_failure_count,
        event_observation_input_count=(
            resolved_event_observation_count
            + event_observation_resolution_failure_count
        ),
        resolved_event_observation_count=resolved_event_observation_count,
        event_observation_resolution_failure_count=event_observation_resolution_failure_count,
    )


def render_sport_report_markdown(
    *,
    analysis: EventViewReportAnalysis,
    sport_code: str | None,
    generated_at: datetime,
) -> str:
    """선택한 종목의 표본과 필드 제공 현황을 Markdown 문자열로 렌더링합니다."""

    sport_observation_summary = next(
        (
            summary
            for summary in analysis.sport_observation_summaries
            if summary.sport_code == sport_code
        ),
        None,
    )
    if sport_observation_summary is None:
        raise ValueError(
            f"분석 결과에 요청한 종목 요약이 없습니다: sport_code={sport_code!r}"
        )

    sport_field_summaries = [
        summary
        for summary in analysis.sport_field_summaries
        if summary.sport_code == sport_code
    ]
    sport_tracked_field_summaries = [
        summary
        for summary in analysis.sport_tracked_field_summaries
        if summary.sport_code == sport_code
    ]

    template = _MARKDOWN_ENVIRONMENT.get_template("event_view_sport.md.jinja")
    content = template.render(
        generated_at=generated_at,
        sport_code=sport_code,
        sport_observation_summary=sport_observation_summary,
        sport_field_summaries=sport_field_summaries,
        sport_tracked_field_summaries=sport_tracked_field_summaries,
    )
    return f"{content.rstrip()}\n"


def render_field_inspection_markdown(
    *,
    analysis: FieldInspectionAnalysis,
    generated_at: datetime,
) -> str:
    """Event View 필드 변화 분석 결과를 Markdown 문자열로 렌더링합니다."""

    template = _MARKDOWN_ENVIRONMENT.get_template("event_view_field.md.jinja")
    return template.render(
        analysis=analysis,
        generated_at=generated_at,
        value_change_labels={
            "initial": "최초 상태",
            "appeared": "등장",
            "changed": "값 변경",
            "disappeared": "사라짐",
        },
        presence_change_labels={
            "initial": "최초 상태",
            "appeared": "등장",
            "disappeared": "사라짐",
        },
    )
