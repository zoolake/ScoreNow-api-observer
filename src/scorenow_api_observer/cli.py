import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import typer
from jinja2 import TemplateError
from pydantic import ValidationError

from scorenow_api_observer.collector import CaptureResult, capture_event_view
from scorenow_api_observer.comparison import (
    StructureComparison,
    compare_observations,
    compare_with_previous_observation,
    convert_to_structure_change_record,
    find_latest_observations,
)
from scorenow_api_observer.event_observation import (
    InvalidEventObservationReferenceError,
)
from scorenow_api_observer.event_view_request import (
    InvalidRequestedEventIdsError,
    parse_requested_event_ids,
)
from scorenow_api_observer.markdown_report import (
    render_endpoint_report_markdown,
    render_sport_report_markdown,
)
from scorenow_api_observer.models import EventObservation
from scorenow_api_observer.report_analysis import analyze_event_view_report
from scorenow_api_observer.report_storage import (
    build_report_output_path,
    save_report_text,
)
from scorenow_api_observer.settings import Settings
from scorenow_api_observer.sport_config import load_sport_codes_by_id
from scorenow_api_observer.storage import (
    find_capture_metadata_paths,
    find_event_observation_paths,
    save_structure_change_record,
)
from scorenow_api_observer.upcoming_discovery import discover_upcoming_events
from scorenow_api_observer.upcoming_targets import load_upcoming_targets

app = typer.Typer(
    name="observer",
    help="BETS API 응답 수집 및 변화를 확인하는 CLI 도구",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """BETS API 응답 관측 도구입니다."""


def _print_capture_summary(result: CaptureResult) -> None:
    """호출 및 저장 결과를 간단하게 출력합니다."""

    typer.echo(f"HTTP 상태 코드: {result.response.status_code}")
    typer.echo(f"원문 저장 위치: {result.raw_file_path}")
    typer.echo(f"메타데이터 저장 위치: {result.metadata_file_path}")


@app.command()
def collect(
    event_ids: str = typer.Option(
        ...,
        "--event-ids",
        "-e",
        help="쉼표로 구분한 수집 대상 외부 API 경기 ID",
    ),
) -> None:
    """BETS View API를 호출하고 응답을 저장합니다."""

    requested_event_ids = _parse_requested_event_ids_or_exit(event_ids)

    # BaseSettings가 실행 시 .env 에서 필수 값을 읽어온다.
    settings = Settings()  # pyright: ignore[reportCallIssue]

    typer.echo(f"수집 대상 경기 ID: {event_ids}")
    typer.echo("BETS View API를 호출합니다.")

    try:
        result = capture_event_view(
            base_url=settings.bets_api_base_url,
            token=settings.bets_api_token.get_secret_value(),
            requested_event_ids=requested_event_ids,
        )
    except httpx.RequestError:
        typer.echo(
            "API 서버에 연결하지 못했습니다.",
            err=True,
        )
        raise typer.Exit(code=1) from None
    except OSError:
        typer.echo(
            "파일 저장에 실패했습니다.",
            err=True,
        )
        raise typer.Exit(code=1) from None

    _print_capture_summary(result)
    _print_observation_save_failures(result)

    # HTTP status code : 4xx, 5xx
    if result.response.is_error:
        typer.echo("API가 오류 응답을 반환했습니다.", err=True)
        typer.echo(result.response.text)
        raise typer.Exit(code=1)

    try:
        response_data = result.response.json()
    except ValueError:
        typer.echo("응답이 JSON 형식이 아닙니다.", err=True)
        typer.echo(result.response.text)
        raise typer.Exit(code=1) from None

    formatted_json = json.dumps(
        response_data,
        ensure_ascii=False,
        indent=2,
    )

    typer.echo(formatted_json)


@app.command()
def watch(
    event_ids: str = typer.Option(
        ...,
        "--event-ids",
        "-e",
        help="쉼표로 구분한 수집 대상 외부 API 경기 ID",
    ),
    interval_seconds: int = typer.Option(
        30, "--interval", "-i", min=1, help="호출 간격(초)"
    ),
    count: int | None = typer.Option(
        None, "--count", "-c", min=1, help="호출할 횟수. 생략하면 계속 수집"
    ),
) -> None:
    """Event View API를 반복 수집하고 응답 구조 변화를 비교·기록합니다."""

    requested_event_ids = _parse_requested_event_ids_or_exit(event_ids)

    settings = Settings()  # pyright: ignore[reportCallIssue]

    count_description = str(count) if count is not None else "제한 없음"

    typer.echo(f"수집 대상 경기 ID: {event_ids}")
    typer.echo(f"호출 간격: {interval_seconds}초")
    typer.echo(f"호출 횟수: {count_description}")
    typer.echo("중단하려면 Ctrl+C를 누르세요.")

    attempt_count = 0
    saved_count = 0

    try:
        while count is None or attempt_count < count:
            attempt_count += 1

            typer.echo("")
            typer.echo(f"[📡 {attempt_count}번째 호출]")

            try:
                result = capture_event_view(
                    base_url=settings.bets_api_base_url,
                    token=settings.bets_api_token.get_secret_value(),
                    requested_event_ids=requested_event_ids,
                )
            except httpx.RequestError:
                typer.echo("API 서버에 연결하지 못했습니다.", err=True)
            except OSError:
                typer.echo("파일 저장에 실패했습니다.", err=True)
            else:
                saved_count += 1

                _print_capture_summary(result)
                _print_observation_save_failures(result)

                if result.response.is_error:
                    typer.echo("API가 오류 응답을 반환했습니다.", err=True)
                else:
                    for observation in result.event_observations:
                        _compare_and_save_structure_change(observation)

            if count is not None and attempt_count >= count:
                break

            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        typer.echo("")
        typer.echo(
            f"❌ 반복 수집을 중단했습니다. 호출: {attempt_count}회 / 저장: {saved_count}개"
        )
        return

    typer.echo("")
    typer.echo(
        f"✅ {attempt_count} 회 수집 완료했습니다. 호출: {attempt_count}회 / 저장: {saved_count}개"
    )


@app.command("discover-upcoming")
def discover_upcoming(
    target_date_value: str = typer.Option(
        ...,
        "--target-date",
        help="BETS Upcoming API에 전달할 UTC 기준 날짜(YYYY-MM-DD)",
    ),
) -> None:
    """설정된 종목·리그의 예정 경기를 조회하여 Discovery JSON을 생성합니다."""

    target_date = _parse_target_date_or_exit(target_date_value)

    try:
        targets = load_upcoming_targets()
    except (OSError, ValueError) as error:
        typer.echo(f"Upcoming 조회 대상 설정을 읽지 못했습니다. {error}", err=True)
        raise typer.Exit(code=2) from None

    try:
        settings = Settings()  # pyright: ignore[reportCallIssue]
    except ValidationError as error:
        typer.echo(f"API 설정을 읽지 못했습니다. {error}", err=True)
        raise typer.Exit(code=2) from None

    typer.echo(f"UTC 기준 조회 날짜: {target_date.isoformat()}")
    typer.echo(f"조회 대상 종목·리그: {len(targets)}개")
    typer.echo("BETS Upcoming API를 호출합니다.")

    try:
        result = discover_upcoming_events(
            base_url=settings.bets_api_base_url,
            token=settings.bets_api_token.get_secret_value(),
            target_date=target_date,
            targets=targets,
        )
    except (OSError, ValueError, ValidationError) as error:
        typer.echo(f"Upcoming Discovery 저장에 실패했습니다. {error}", err=True)
        raise typer.Exit(code=1) from None

    discovery = result.discovery
    typer.echo(f"Discovery 상태: {discovery.status}")
    typer.echo(f"Capture 저장: {len(result.captures)}개")
    typer.echo(f"예정 경기: {len(discovery.events)}개")
    typer.echo(f"처리 실패: {len(discovery.failures)}개")
    typer.echo(f"Discovery 저장 위치: {result.discovery_file_path}")

    for failure in discovery.failures:
        typer.echo(
            f"[{failure.league_label}] {failure.error_type}: {failure.error_message}",
            err=True,
        )

    if discovery.status == "partial":
        typer.echo(
            "일부 조회 또는 응답 분석에 이상이 있습니다. "
            "저장된 Discovery와 CaptureMetadata를 확인하세요.",
            err=True,
        )
    elif discovery.status == "failed":
        typer.echo("예정 경기 조회에 모두 실패했습니다.", err=True)
        raise typer.Exit(code=1)


@app.command()
def compare(
    event_id: str = typer.Option(
        ...,
        "--event-id",
        "-e",
        help="비교할 외부 API 경기 ID",
    ),
) -> None:
    """저장된 동일 경기의 최근 응답 두 개를 비교하여 구조 변화를 출력합니다."""

    try:
        observations = find_latest_observations(event_id)

        if len(observations) < 2:
            typer.echo("비교하려면 동일 경기의 응답이 최소 2개 필요합니다.", err=True)
            raise typer.Exit(code=1)

        previous_observation = observations[0]
        current_observation = observations[1]

        comparison = compare_observations(previous_observation, current_observation)
    except (
        OSError,
        json.JSONDecodeError,
        InvalidEventObservationReferenceError,
        ValidationError,
    ) as error:
        typer.echo(f"이벤트 구조 비교 과정 중에 예외가 발생했습니다. {error}", err=True)
        raise typer.Exit(code=1)

    typer.echo("")
    typer.echo(f"경기 ID: {comparison.event_id}")
    typer.echo(f"직전 응답: {comparison.previous_capture.captured_at.isoformat()}")
    typer.echo(f"최신 응답: {comparison.current_capture.captured_at.isoformat()}")
    _print_structure_comparison(comparison.structure_comparison)


@app.command()
def report() -> None:
    """저장된 Event View 자료를 분석하여 Markdown 보고서를 생성합니다."""

    try:
        sport_code_by_id = load_sport_codes_by_id()
        analysis = analyze_event_view_report(
            metadata_file_paths=find_capture_metadata_paths(),
            observation_file_paths=find_event_observation_paths(),
            sport_code_by_id=sport_code_by_id,
        )
        generated_at = datetime.now(UTC)

        # 보고서 리스트 초기화 및 엔드포인트 보고서 추가
        rendered_reports: list[tuple[str, str]] = [
            (
                "endpoint",
                render_endpoint_report_markdown(
                    analysis=analysis,
                    generated_at=generated_at,
                ),
            )
        ]

        # 종목별 보고서 추가
        for summary in analysis.sport_observation_summaries:
            sport_code = summary.sport_code
            sport_name = sport_code if sport_code is not None else "unclassified"
            rendered_reports.append(
                (
                    f"sport_{sport_name}",
                    render_sport_report_markdown(
                        analysis=analysis,
                        sport_code=sport_code,
                        generated_at=generated_at,
                    ),
                )
            )

        output_paths = [
            build_report_output_path(
                generated_at=generated_at,
                report_name=report_name,
            )
            for report_name, _ in rendered_reports
        ]

        # 중복 여부 검증
        if len(output_paths) != len(set(output_paths)):
            raise ValueError(
                "보고서 이름을 안전한 파일명으로 변환한 결과가 중복됩니다."
            )

        # 기등록 여부 검증
        existing_paths = [path for path in output_paths if path.exists()]
        if existing_paths:
            raise FileExistsError(f"보고서 파일이 이미 존재합니다: {existing_paths[0]}")

        saved_reports: list[tuple[str, Path]] = []
        for (report_name, content), output_path in zip(
            rendered_reports,
            output_paths,
            strict=True,
        ):
            saved_path = save_report_text(content=content, output_path=output_path)
            saved_reports.append((report_name, saved_path))
    except (OSError, ValueError, TemplateError) as error:
        typer.echo(f"보고서 생성에 실패했습니다. {error}", err=True)
        raise typer.Exit(code=1) from None

    for report_name, saved_path in saved_reports:
        typer.echo(f"{report_name} 보고서 저장 위치: {saved_path}")

    metadata_failure_count = len(analysis.capture_metadata_load_failures)
    observation_failure_count = len(analysis.observed_event_resolution_failures)
    if metadata_failure_count or observation_failure_count:
        typer.echo(
            "일부 저장 파일을 분석하지 못했습니다. "
            f"CaptureMetadata {metadata_failure_count}건, "
            f"EventObservation {observation_failure_count}건. "
            "자세한 내용은 endpoint 보고서를 확인하세요.",
            err=True,
        )


def _print_structure_comparison(result: StructureComparison) -> None:

    if not result.has_changes:
        typer.echo("")
        typer.echo("JSON 구조 변화가 없습니다.")
        return

    _print_added_paths(result.added_paths)
    _print_removed_paths(result.removed_paths)
    _print_type_changes(result.type_changes)


def _compare_and_save_structure_change(current_observation: EventObservation) -> None:
    """현재 Observation과 직전 Observation을 비교하고 구조 변화가 있으면 저장합니다."""

    try:
        comparison = compare_with_previous_observation(current_observation)
    except (
        OSError,
        json.JSONDecodeError,
        InvalidEventObservationReferenceError,
        ValidationError,
    ):
        typer.echo(
            f"경기 ID {current_observation.event_id}의 저장된 응답을 읽거나 비교하는데 실패하였습니다.",
            err=True,
        )
        return

    if comparison is None:
        typer.echo(
            f"경기 ID {current_observation.event_id}의 직전 응답이 없어 구조 비교를 생략합니다."
        )
        return

    record = convert_to_structure_change_record(comparison, datetime.now(UTC))

    _print_structure_comparison(comparison.structure_comparison)

    if record is None:
        return

    try:
        saved_path = save_structure_change_record(record)
    except OSError:
        typer.echo(
            f"경기 ID {current_observation.event_id}의 응답 구조 변화 저장에 실패하였습니다.",
            err=True,
        )
        return

    typer.echo(f"🟢 응답 구조 변화 기록 위치: {saved_path}")


def _print_added_paths(added_paths: list[str]) -> None:
    typer.echo("")
    typer.echo(f"이번 응답에서 새로 보이는 경로: {len(added_paths)}개")
    for added_path in added_paths:
        typer.echo(f" + {added_path}")


def _print_removed_paths(removed_paths: list[str]) -> None:
    typer.echo("")
    typer.echo(f"이번 응답에서 보이지 않는 경로: {len(removed_paths)}개")
    for removed_path in removed_paths:
        typer.echo(f" - {removed_path}")


def _print_type_changes(type_changes: list) -> None:
    typer.echo("")
    typer.echo(f"자료형이 달라진 경로: {len(type_changes)}개")
    for type_change in type_changes:
        previous_types = ", ".join(sorted(type_change.previous_types))
        current_types = ", ".join(sorted(type_change.current_types))

        typer.echo(f" ~ {type_change.path}: {previous_types} → {current_types}")


def _print_observation_save_failures(result: CaptureResult) -> None:
    if not result.observation_save_failures:
        return

    failure_count = len(result.observation_save_failures)
    typer.echo("")
    typer.echo(
        f"Event Observation 저장에 실패한 {failure_count} 건이 존재합니다.",
        err=True,
    )

    for save_failure in result.observation_save_failures:
        typer.echo(
            f"실패 Event ID:{save_failure.event_id} / 사유: {save_failure.error_message}",
            err=True,
        )


def _parse_requested_event_ids_or_exit(value: str) -> list[str]:
    try:
        requested_event_ids = parse_requested_event_ids(value)
    except InvalidRequestedEventIdsError as error:
        typer.echo(
            f"이벤트 ID 입력이 올바르지 않습니다. {error}",
            err=True,
        )
        raise typer.Exit(code=2) from None

    return requested_event_ids


def _parse_target_date_or_exit(value: str) -> date:
    try:
        parsed_date = date.fromisoformat(value)
        if parsed_date.isoformat() != value:
            raise ValueError
        return parsed_date
    except ValueError:
        typer.echo(
            "조회 날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식으로 입력하세요.",
            err=True,
        )
        raise typer.Exit(code=2) from None


if __name__ == "__main__":
    app()
