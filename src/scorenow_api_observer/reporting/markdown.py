import json
import shlex
from dataclasses import dataclass
from datetime import datetime
from html import escape

from jinja2 import Environment, PackageLoader, StrictUndefined

from scorenow_api_observer.reporting.field_inspection import (
    FieldInspectionAnalysis,
)
from scorenow_api_observer.reporting.field_path import JsonScalar
from scorenow_api_observer.reporting.models import (
    EventViewReportAnalysis,
    LeagueFieldSummary,
    LeagueObservationSummary,
)


@dataclass(frozen=True)
class LeagueComparisonColumn:
    """종목 보고서의 리그 비교 표에 표시할 열 정보입니다."""

    summary: LeagueObservationSummary
    report_link: str | None


@dataclass(frozen=True)
class LeagueFieldComparisonCell:
    """리그 비교 표의 필드 제공 상태와 표본 수입니다."""

    status_icon: str
    status_label: str
    present_observation_count: int
    total_observation_count: int
    present_event_count: int
    total_event_count: int


@dataclass(frozen=True)
class LeagueFieldComparisonRow:
    """JSON 경로 하나에 대한 리그별 비교 셀 목록입니다."""

    path: str
    cells: list[LeagueFieldComparisonCell]


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
    league_report_links_by_id: dict[str | None, str] | None = None,
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
    league_comparison_columns: list[LeagueComparisonColumn] = []
    league_comparison_rows: list[LeagueFieldComparisonRow] = []
    unobserved_configured_leagues: list[LeagueObservationSummary] = []

    if sport_code is not None:
        sport_league_summaries = [
            summary
            for summary in analysis.league_observation_summaries
            if summary.sport_code == sport_code
        ]
        observed_league_summaries = [
            summary
            for summary in sport_league_summaries
            if summary.observation_count > 0
        ]
        unobserved_configured_leagues = [
            summary
            for summary in sport_league_summaries
            if summary.configured and summary.observation_count == 0
        ]
        links_by_id = league_report_links_by_id or {}
        league_comparison_columns = [
            LeagueComparisonColumn(
                summary=summary,
                report_link=links_by_id.get(summary.league_id),
            )
            for summary in observed_league_summaries
        ]

        field_summaries_by_key = {
            (summary.league_id, summary.path): summary
            for summary in analysis.league_field_summaries
            if summary.sport_code == sport_code
        }
        for sport_field_summary in sport_field_summaries:
            cells = []
            for league_summary in observed_league_summaries:
                try:
                    league_field_summary = field_summaries_by_key[
                        (league_summary.league_id, sport_field_summary.path)
                    ]
                except KeyError as error:
                    raise ValueError(
                        "리그 비교에 필요한 필드 요약이 없습니다: "
                        f"sport_code={sport_code!r}, "
                        f"league_id={league_summary.league_id!r}, "
                        f"path={sport_field_summary.path!r}"
                    ) from error

                cells.append(
                    _build_league_field_comparison_cell(
                        field_summary=league_field_summary,
                        league_summary=league_summary,
                    )
                )

            league_comparison_rows.append(
                LeagueFieldComparisonRow(
                    path=sport_field_summary.path,
                    cells=cells,
                )
            )

    template = _MARKDOWN_ENVIRONMENT.get_template("event_view_sport.md.jinja")
    content = template.render(
        generated_at=generated_at,
        sport_code=sport_code,
        sport_observation_summary=sport_observation_summary,
        sport_field_summaries=sport_field_summaries,
        sport_tracked_field_summaries=sport_tracked_field_summaries,
        league_comparison_columns=league_comparison_columns,
        league_comparison_rows=league_comparison_rows,
        unobserved_configured_leagues=unobserved_configured_leagues,
    )
    return f"{content.rstrip()}\n"


def render_league_report_markdown(
    *,
    analysis: EventViewReportAnalysis,
    sport_code: str,
    league_id: str | None,
    generated_at: datetime,
) -> str:
    """선택한 리그의 표본·필드 제공·추적 값 현황을 렌더링합니다."""

    league_summary = next(
        (
            summary
            for summary in analysis.league_observation_summaries
            if summary.sport_code == sport_code and summary.league_id == league_id
        ),
        None,
    )
    if league_summary is None or league_summary.observation_count == 0:
        raise ValueError(
            "분석 결과에 표본이 있는 요청 리그 요약이 없습니다: "
            f"sport_code={sport_code!r}, league_id={league_id!r}"
        )

    league_field_summaries = [
        summary
        for summary in analysis.league_field_summaries
        if summary.sport_code == sport_code and summary.league_id == league_id
    ]
    league_tracked_field_summaries = [
        summary
        for summary in analysis.league_tracked_field_summaries
        if summary.sport_code == sport_code and summary.league_id == league_id
    ]

    template = _MARKDOWN_ENVIRONMENT.get_template("event_view_league.md.jinja")
    content = template.render(
        generated_at=generated_at,
        league_summary=league_summary,
        league_field_summaries=league_field_summaries,
        league_tracked_field_summaries=league_tracked_field_summaries,
    )
    return f"{content.rstrip()}\n"


def _build_league_field_comparison_cell(
    *,
    field_summary: LeagueFieldSummary,
    league_summary: LeagueObservationSummary,
) -> LeagueFieldComparisonCell:
    if field_summary.present_observation_count == league_summary.observation_count:
        status_icon = "🟢"
        status_label = "항상"
    elif field_summary.present_observation_count > 0:
        status_icon = "🟡"
        status_label = "일부"
    else:
        status_icon = "⚪"
        status_label = "미제공"

    return LeagueFieldComparisonCell(
        status_icon=status_icon,
        status_label=status_label,
        present_observation_count=field_summary.present_observation_count,
        total_observation_count=league_summary.observation_count,
        present_event_count=(
            field_summary.always_present_event_count
            + field_summary.sometimes_present_event_count
        ),
        total_event_count=league_summary.unique_event_count,
    )


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
