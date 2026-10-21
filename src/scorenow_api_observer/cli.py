import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import typer
from jinja2 import TemplateError
from pydantic import ValidationError

from scorenow_api_observer.event_odds.collector import (
    DEFAULT_ODDS_MARKETS,
    OddsCollectionResult,
    collect_event_odds,
)
from scorenow_api_observer.event_odds.request import (
    InvalidOddsEventIdsError,
    parse_odds_event_ids,
)
from scorenow_api_observer.event_view.collector import (
    CaptureResult,
    capture_event_view,
)
from scorenow_api_observer.event_view.comparison import (
    StructureComparison,
    compare_observations,
    compare_with_previous_observation,
    convert_to_structure_change_record,
    find_latest_observations,
)
from scorenow_api_observer.event_view.models import EventObservation
from scorenow_api_observer.event_view.observation import (
    InvalidEventObservationReferenceError,
    extract_observed_event,
)
from scorenow_api_observer.event_view.request import (
    InvalidRequestedEventIdsError,
    build_event_view_request_batches,
    parse_requested_event_ids,
)
from scorenow_api_observer.event_view.storage import (
    find_capture_metadata_paths,
    find_event_observation_paths,
    find_event_observation_paths_for_event,
    save_structure_change_record,
)
from scorenow_api_observer.event_view.watching import (
    POST_FINISH_COLLECTION_PERIOD,
    EventWatchState,
    apply_event_time_status,
    find_completed_event_ids,
)
from scorenow_api_observer.reporting.analysis import analyze_event_view_report
from scorenow_api_observer.reporting.event_timeline import analyze_event_timeline
from scorenow_api_observer.reporting.field_inspection import analyze_field_inspection
from scorenow_api_observer.reporting.field_path import (
    InvalidFieldPathError,
    validate_field_path,
)
from scorenow_api_observer.reporting.markdown import (
    render_endpoint_report_markdown,
    render_event_timeline_markdown,
    render_field_inspection_markdown,
    render_league_report_markdown,
    render_sport_report_markdown,
)
from scorenow_api_observer.reporting.models import LeagueDefinition
from scorenow_api_observer.reporting.sources import resolve_observed_events
from scorenow_api_observer.reporting.storage import (
    build_field_report_output_path,
    build_league_report_output_path,
    build_report_output_path,
    build_timeline_report_output_path,
    save_report_text,
)
from scorenow_api_observer.reporting.timeline_config import (
    load_timeline_fields_config,
)
from scorenow_api_observer.reporting.tracked_field_config import (
    load_tracked_fields_config,
)
from scorenow_api_observer.settings import Settings
from scorenow_api_observer.sport_config import load_sport_codes_by_id
from scorenow_api_observer.upcoming.candidates import (
    InvalidUpcomingCandidateFilterError,
    LatestLeagueDiscoveries,
    UpcomingCandidate,
    normalize_candidate_sport_code,
    parse_candidate_league_labels,
    resolve_latest_league_discoveries,
    select_upcoming_candidates,
)
from scorenow_api_observer.upcoming.discovery import discover_upcoming_events
from scorenow_api_observer.upcoming.storage import (
    find_league_upcoming_discovery_paths,
)
from scorenow_api_observer.upcoming.targets import (
    InvalidUpcomingTargetSelectionError,
    load_upcoming_targets,
    select_upcoming_targets,
)

app = typer.Typer(
    name="observer",
    help="BETS API 응답 수집 및 변화를 확인하는 CLI 도구",
    no_args_is_help=True,
)
KST = ZoneInfo("Asia/Seoul")


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
    """BETS View API를 한 수집 주기 호출하고 응답을 저장합니다."""

    requested_event_ids = _parse_requested_event_ids_or_exit(event_ids)
    request_batches = build_event_view_request_batches(requested_event_ids)

    # BaseSettings가 실행 시 .env 에서 필수 값을 읽어온다.
    settings = Settings()  # pyright: ignore[reportCallIssue]

    typer.echo(f"수집 대상 경기 ID: {event_ids}")
    typer.echo(f"Event View 요청 배치: {len(request_batches)}개")
    typer.echo("BETS View API를 한 수집 주기 호출합니다.")

    failed_batch_count = 0

    for batch_index, batch_event_ids in enumerate(request_batches, start=1):
        typer.echo("")
        typer.echo(f"[배치 {batch_index}/{len(request_batches)}]")
        typer.echo(f"요청 이벤트 ID: {', '.join(batch_event_ids)}")

        try:
            result = capture_event_view(
                base_url=settings.bets_api_base_url,
                token=settings.bets_api_token.get_secret_value(),
                requested_event_ids=batch_event_ids,
            )
        except httpx.RequestError:
            typer.echo("API 서버에 연결하지 못했습니다.", err=True)
            failed_batch_count += 1
            continue
        except OSError:
            typer.echo("파일 저장에 실패했습니다.", err=True)
            failed_batch_count += 1
            continue

        _print_capture_summary(result)
        _print_observation_save_failures(result)

        # HTTP status code : 4xx, 5xx
        if result.response.is_error:
            typer.echo("API가 오류 응답을 반환했습니다.", err=True)
            typer.echo(result.response.text)
            failed_batch_count += 1
            continue

        try:
            response_data = result.response.json()
        except ValueError:
            typer.echo("응답이 JSON 형식이 아닙니다.", err=True)
            typer.echo(result.response.text)
            failed_batch_count += 1
            continue

        formatted_json = json.dumps(
            response_data,
            ensure_ascii=False,
            indent=2,
        )
        typer.echo(formatted_json)

    if failed_batch_count:
        typer.echo(
            f"전체 {len(request_batches)}개 배치 중 "
            f"{failed_batch_count}개 수집에 실패했습니다.",
            err=True,
        )
        raise typer.Exit(code=1)


@app.command("collect-odds")
def collect_odds(
    event_ids: str = typer.Option(
        ...,
        "--event-ids",
        "-e",
        help="쉼표로 구분한 Event Odds 수집 대상 외부 API 경기 ID",
    ),
) -> None:
    """이벤트별 누적 배당률을 조회하고 일간 최신 Snapshot을 저장합니다."""

    requested_event_ids = _parse_odds_event_ids_or_exit(event_ids)
    try:
        settings = Settings()  # pyright: ignore[reportCallIssue]
    except ValidationError as error:
        typer.echo(f"API 설정을 읽지 못했습니다. {error}", err=True)
        raise typer.Exit(code=2) from None

    typer.echo(f"수집 대상 경기: {len(requested_event_ids)}개")
    typer.echo(
        "요청 배당 마켓: " + ",".join(str(market) for market in DEFAULT_ODDS_MARKETS)
    )
    typer.echo("BETS Event Odds API를 이벤트별로 호출합니다.")

    try:
        result = collect_event_odds(
            base_url=settings.bets_api_base_url,
            token=settings.bets_api_token.get_secret_value(),
            event_ids=requested_event_ids,
        )
    except (OSError, ValueError, ValidationError) as error:
        typer.echo(f"Odds 수집을 처리하지 못했습니다. {error}", err=True)
        raise typer.Exit(code=1) from None

    _print_odds_collection_summary(result)

    if result.status == "failed":
        typer.echo("모든 이벤트의 배당률 수집에 실패했습니다.", err=True)
        raise typer.Exit(code=1)

    if result.status == "partial":
        typer.echo(
            "일부 이벤트의 배당률 수집에 실패했습니다.",
            err=True,
        )


@app.command()
def watch(
    event_ids: str = typer.Option(
        ...,
        "--event-ids",
        "-e",
        help="쉼표로 구분한 수집 대상 외부 API 경기 ID",
    ),
    interval_seconds: int = typer.Option(
        30, "--interval", "-i", min=1, help="수집 주기 간 간격(초)"
    ),
    max_cycles: int | None = typer.Option(
        None,
        "--max-cycles",
        "-c",
        min=1,
        help="최대 수집 주기 횟수. 생략하면 모든 이벤트가 완료될 때까지 수집",
    ),
) -> None:
    """Event View API를 반복 수집하고 응답 구조 변화를 비교·기록합니다."""

    requested_event_ids = _parse_requested_event_ids_or_exit(event_ids)

    settings = Settings()  # pyright: ignore[reportCallIssue]

    max_cycles_description = str(max_cycles) if max_cycles is not None else "제한 없음"

    typer.echo(f"수집 대상 경기 ID: {event_ids}")
    typer.echo(f"호출 간격: {interval_seconds}초")
    typer.echo(f"최대 수집 주기: {max_cycles_description}")
    typer.echo("종료 감지 후 추가 수집: 15분")
    typer.echo("중단하려면 Ctrl+C를 누르세요.")

    _run_event_view_watch(
        settings=settings,
        event_ids=requested_event_ids,
        interval_seconds=interval_seconds,
        max_cycles=max_cycles,
    )


@app.command("discover-upcoming")
def discover_upcoming(
    target_date_value: str = typer.Option(
        ...,
        "--target-date",
        help="BETS Upcoming API에 전달할 UTC 기준 날짜(YYYY-MM-DD)",
    ),
    league_labels: str | None = typer.Option(
        None,
        "--league-labels",
        help="설정에서 선택할 리그 label 목록(쉼표 구분). 생략하면 전체 조회",
    ),
) -> None:
    """설정에서 선택한 종목·리그의 예정 경기를 조회합니다."""

    target_date = _parse_target_date_or_exit(target_date_value)

    try:
        configured_targets = load_upcoming_targets()
    except (OSError, ValueError) as error:
        typer.echo(f"Upcoming 조회 대상 설정을 읽지 못했습니다. {error}", err=True)
        raise typer.Exit(code=2) from None

    try:
        targets = select_upcoming_targets(configured_targets, league_labels)
    except InvalidUpcomingTargetSelectionError as error:
        typer.echo(f"Upcoming 조회 대상을 선택하지 못했습니다. {error}", err=True)
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

    discovery_run = result.run
    failures = [
        discovery.failure
        for discovery in result.league_discoveries
        if discovery.failure is not None
    ]
    event_count = sum(len(discovery.events) for discovery in result.league_discoveries)

    typer.echo(f"Discovery 상태: {discovery_run.status}")
    typer.echo(f"Capture 저장: {len(result.captures)}개")
    typer.echo(f"리그 Discovery 저장: {len(result.league_discoveries)}개")
    typer.echo(f"예정 경기: {event_count}개")
    typer.echo(f"처리 실패: {len(failures)}개")
    typer.echo(f"Run 저장 위치: {result.run_file_path}")

    for failure in failures:
        typer.echo(
            f"[{failure.league_label}] {failure.error_type}: {failure.error_message}",
            err=True,
        )

    if discovery_run.status == "partial":
        typer.echo(
            "일부 조회 또는 응답 분석에 이상이 있습니다. "
            "저장된 Discovery와 CaptureMetadata를 확인하세요.",
            err=True,
        )
    elif discovery_run.status == "failed":
        typer.echo("예정 경기 조회에 모두 실패했습니다.", err=True)
        raise typer.Exit(code=1)


@app.command("upcoming-candidates")
def upcoming_candidates(
    within_minutes: int = typer.Option(
        10,
        "--within-minutes",
        min=1,
        help="현재부터 후보로 조회할 시작 예정 범위(분)",
    ),
    sport_code: str | None = typer.Option(
        None,
        "--sport-code",
        help="조회할 내부 종목 코드. 생략하면 전체 종목",
    ),
    league_labels: str | None = typer.Option(
        None,
        "--league-labels",
        help="조회할 리그 label 목록(쉼표 구분). 생략하면 전체 리그",
    ),
) -> None:
    """저장된 Discovery에서 곧 시작하는 경기 후보를 조회합니다."""

    try:
        normalized_sport_code = normalize_candidate_sport_code(sport_code)
        normalized_league_labels = parse_candidate_league_labels(league_labels)
    except InvalidUpcomingCandidateFilterError as error:
        typer.echo(f"후보 조회 필터가 올바르지 않습니다. {error}", err=True)
        raise typer.Exit(code=2) from None

    try:
        discovery_paths = find_league_upcoming_discovery_paths()
        latest_discoveries = resolve_latest_league_discoveries(discovery_paths)
    except OSError as error:
        typer.echo(f"Discovery 파일 탐색에 실패했습니다. {error}", err=True)
        raise typer.Exit(code=1) from None

    _print_upcoming_discovery_warnings(latest_discoveries)

    typer.echo(f"저장된 리그 Discovery: {len(discovery_paths)}개")
    typer.echo(f"사용 가능한 최신 Discovery: {len(latest_discoveries.selected)}개")
    if not latest_discoveries.selected:
        typer.echo("사용 가능한 리그 Discovery가 없습니다.", err=True)
        raise typer.Exit(code=1)

    now = _utc_now()
    try:
        selection = select_upcoming_candidates(
            latest_discoveries.selected,
            now=now,
            within_minutes=within_minutes,
            sport_code=normalized_sport_code,
            league_labels=normalized_league_labels,
        )
    except ValueError as error:
        typer.echo(f"예정 경기 후보를 계산하지 못했습니다. {error}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"기준 시각(UTC): {now.isoformat()}")
    typer.echo(f"기준 시각(KST): {now.astimezone(KST).isoformat()}")
    typer.echo(f"조회 범위: 현재부터 {within_minutes}분 이내")
    typer.echo(f"후보 경기: {len(selection.candidates)}개")

    if selection.duplicate_event_ids:
        typer.echo(
            "중복된 이벤트 ID는 최신 Discovery의 값으로 한 번만 표시합니다: "
            + ", ".join(selection.duplicate_event_ids),
            err=True,
        )

    for index, candidate in enumerate(selection.candidates, start=1):
        _print_upcoming_candidate(index=index, candidate=candidate, now=now)


@app.command("watch-upcoming")
def watch_upcoming(
    within_minutes: int = typer.Option(
        10,
        "--within-minutes",
        min=1,
        help="현재부터 수집 대상으로 선택할 시작 예정 범위(분)",
    ),
    sport_code: str | None = typer.Option(
        None,
        "--sport-code",
        help="수집할 내부 종목 코드. 생략하면 전체 종목",
    ),
    league_labels: str | None = typer.Option(
        None,
        "--league-labels",
        help="수집할 리그 label 목록(쉼표 구분). 생략하면 전체 리그",
    ),
    interval_seconds: int = typer.Option(
        30,
        "--interval",
        "-i",
        min=1,
        help="전체 후보 수집 주기 간 간격(초)",
    ),
    max_cycles: int | None = typer.Option(
        None,
        "--max-cycles",
        "-c",
        min=1,
        help="최대 수집 주기 횟수. 생략하면 모든 이벤트가 완료될 때까지 수집",
    ),
) -> None:
    """곧 시작하는 저장된 Upcoming 후보를 Event View로 반복 수집합니다."""

    try:
        normalized_sport_code = normalize_candidate_sport_code(sport_code)
        normalized_league_labels = parse_candidate_league_labels(league_labels)
    except InvalidUpcomingCandidateFilterError as error:
        typer.echo(f"후보 조회 필터가 올바르지 않습니다. {error}", err=True)
        raise typer.Exit(code=2) from None

    try:
        discovery_paths = find_league_upcoming_discovery_paths()
        latest_discoveries = resolve_latest_league_discoveries(discovery_paths)
    except OSError as error:
        typer.echo(f"Discovery 파일 탐색에 실패했습니다. {error}", err=True)
        raise typer.Exit(code=1) from None

    _print_upcoming_discovery_warnings(latest_discoveries)

    typer.echo(f"저장된 리그 Discovery: {len(discovery_paths)}개")
    typer.echo(f"사용 가능한 최신 Discovery: {len(latest_discoveries.selected)}개")
    if not latest_discoveries.selected:
        typer.echo("사용 가능한 리그 Discovery가 없습니다.", err=True)
        raise typer.Exit(code=1)

    now = _utc_now()
    try:
        selection = select_upcoming_candidates(
            latest_discoveries.selected,
            now=now,
            within_minutes=within_minutes,
            sport_code=normalized_sport_code,
            league_labels=normalized_league_labels,
        )
    except ValueError as error:
        typer.echo(f"예정 경기 후보를 계산하지 못했습니다. {error}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"기준 시각(UTC): {now.isoformat()}")
    typer.echo(f"기준 시각(KST): {now.astimezone(KST).isoformat()}")
    typer.echo(f"수집 범위: 현재부터 {within_minutes}분 이내")
    typer.echo(f"수집 후보 경기: {len(selection.candidates)}개")

    if selection.duplicate_event_ids:
        typer.echo(
            "중복된 이벤트 ID는 최신 Discovery의 값으로 한 번만 수집합니다: "
            + ", ".join(selection.duplicate_event_ids),
            err=True,
        )

    if not selection.candidates:
        typer.echo("현재 수집할 예정 경기 후보가 없습니다.")
        return

    for index, candidate in enumerate(selection.candidates, start=1):
        _print_upcoming_candidate(index=index, candidate=candidate, now=now)

    event_ids = [candidate.event.event_id for candidate in selection.candidates]
    request_batches = build_event_view_request_batches(event_ids)
    typer.echo("")
    typer.echo(f"Event View 요청 배치: {len(request_batches)}개")
    for batch_index, requested_event_ids in enumerate(request_batches, start=1):
        typer.echo(f"  배치 {batch_index}: {', '.join(requested_event_ids)}")

    try:
        settings = Settings()  # pyright: ignore[reportCallIssue]
    except ValidationError as error:
        typer.echo(f"API 설정을 읽지 못했습니다. {error}", err=True)
        raise typer.Exit(code=2) from None

    max_cycles_description = str(max_cycles) if max_cycles is not None else "제한 없음"
    typer.echo(f"수집 주기 간격: {interval_seconds}초")
    typer.echo(f"최대 수집 주기: {max_cycles_description}")
    typer.echo("종료 감지 후 추가 수집: 15분")
    typer.echo("중단하려면 Ctrl+C를 누르세요.")

    _run_event_view_watch(
        settings=settings,
        event_ids=event_ids,
        interval_seconds=interval_seconds,
        max_cycles=max_cycles,
    )


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
        tracked_fields_config = load_tracked_fields_config()
        upcoming_targets = load_upcoming_targets()
        league_definitions = [
            LeagueDefinition(
                sport_code=target.sport_code,
                league_id=target.league_id,
                label=target.league_label,
            )
            for target in upcoming_targets
        ]
        analysis = analyze_event_view_report(
            metadata_file_paths=find_capture_metadata_paths(),
            observation_file_paths=find_event_observation_paths(),
            sport_code_by_id=sport_code_by_id,
            tracked_field_paths_by_sport_code=(
                tracked_fields_config.paths_by_sport_code
            ),
            league_definitions=league_definitions,
        )
        generated_at = datetime.now(UTC)

        report_output_paths: list[tuple[str, Path]] = [
            (
                "endpoint",
                build_report_output_path(
                    generated_at=generated_at,
                    report_name="endpoint",
                ),
            )
        ]
        sport_report_paths: dict[str | None, Path] = {}
        for summary in analysis.sport_observation_summaries:
            sport_code = summary.sport_code
            sport_name = sport_code if sport_code is not None else "unclassified"
            report_name = f"sport_{sport_name}"
            output_path = build_report_output_path(
                generated_at=generated_at,
                report_name=report_name,
            )
            sport_report_paths[sport_code] = output_path
            report_output_paths.append((report_name, output_path))

        league_report_paths: dict[tuple[str, str | None], Path] = {}
        for summary in analysis.league_observation_summaries:
            if summary.observation_count == 0:
                continue

            report_name = f"league_{summary.sport_code}_{summary.label}"
            output_path = build_league_report_output_path(
                generated_at=generated_at,
                sport_code=summary.sport_code,
                league_id=summary.league_id,
                league_label=summary.label,
            )
            league_report_paths[(summary.sport_code, summary.league_id)] = output_path
            report_output_paths.append((report_name, output_path))

        output_paths = [output_path for _, output_path in report_output_paths]

        # 중복 여부 검증
        if len(output_paths) != len(set(output_paths)):
            raise ValueError(
                "보고서 이름을 안전한 파일명으로 변환한 결과가 중복됩니다."
            )

        # 기등록 여부 검증
        existing_paths = [path for path in output_paths if path.exists()]
        if existing_paths:
            raise FileExistsError(f"보고서 파일이 이미 존재합니다: {existing_paths[0]}")

        rendered_reports: list[tuple[str, str]] = [
            (
                "endpoint",
                render_endpoint_report_markdown(
                    analysis=analysis,
                    generated_at=generated_at,
                ),
            )
        ]
        for summary in analysis.sport_observation_summaries:
            sport_code = summary.sport_code
            sport_name = sport_code if sport_code is not None else "unclassified"
            links_by_league_id: dict[str | None, str] = {}
            if sport_code is not None:
                sport_report_directory = sport_report_paths[sport_code].parent
                links_by_league_id = {
                    league_id: path.relative_to(sport_report_directory).as_posix()
                    for (league_sport_code, league_id), path in (
                        league_report_paths.items()
                    )
                    if league_sport_code == sport_code
                }

            rendered_reports.append(
                (
                    f"sport_{sport_name}",
                    render_sport_report_markdown(
                        analysis=analysis,
                        sport_code=sport_code,
                        generated_at=generated_at,
                        league_report_links_by_id=links_by_league_id,
                    ),
                )
            )

        for summary in analysis.league_observation_summaries:
            if summary.observation_count == 0:
                continue
            rendered_reports.append(
                (
                    f"league_{summary.sport_code}_{summary.label}",
                    render_league_report_markdown(
                        analysis=analysis,
                        sport_code=summary.sport_code,
                        league_id=summary.league_id,
                        generated_at=generated_at,
                    ),
                )
            )

        saved_reports: list[tuple[str, Path]] = []
        for (report_name, content), (output_name, output_path) in zip(
            rendered_reports,
            report_output_paths,
            strict=True,
        ):
            if report_name != output_name:
                raise ValueError("보고서 내용과 저장 경로의 순서가 일치하지 않습니다.")
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


@app.command("inspect-field")
def inspect_field(
    sport_code: str = typer.Option(
        ...,
        "--sport-code",
        help="분석할 내부 종목 코드",
    ),
    field_path: str = typer.Option(
        ...,
        "--path",
        help="분석할 객체 경로($.field.child 형식)",
    ),
    event_id: str | None = typer.Option(
        None,
        "--event-id",
        "-e",
        help="분석할 외부 API 경기 ID. 생략하면 해당 종목의 전체 경기",
    ),
) -> None:
    """저장된 Event View 자료에서 특정 필드의 값 변화를 분석합니다."""

    normalized_sport_code = sport_code.strip().lower()
    normalized_event_id = event_id.strip() if event_id is not None else None

    try:
        validate_field_path(field_path)
        if not normalized_sport_code:
            raise ValueError("종목 코드가 비어 있습니다.")
        if normalized_event_id == "":
            raise ValueError("이벤트 ID가 비어 있습니다.")

        sport_code_by_id = load_sport_codes_by_id()
        if normalized_sport_code not in sport_code_by_id.values():
            raise ValueError(
                f"설정에 등록되지 않은 종목 코드입니다: {normalized_sport_code!r}"
            )
    except InvalidFieldPathError as error:
        typer.echo(f"필드 경로가 올바르지 않습니다. {error}", err=True)
        raise typer.Exit(code=2) from None
    except (OSError, ValueError) as error:
        typer.echo(f"필드 분석 조건을 준비하지 못했습니다. {error}", err=True)
        raise typer.Exit(code=2) from None

    try:
        observation_file_paths = (
            find_event_observation_paths()
            if normalized_event_id is None
            else find_event_observation_paths_for_event(normalized_event_id)
        )
        resolution = resolve_observed_events(
            observation_file_paths=observation_file_paths,
            sport_code_by_id=sport_code_by_id,
        )
        analysis = analyze_field_inspection(
            observed_events=resolution.observed_events,
            resolution_failures=resolution.failures,
            sport_code=normalized_sport_code,
            path=field_path,
            event_id=normalized_event_id,
        )
        if analysis.input_observation_count == 0:
            filter_description = (
                f"종목 {normalized_sport_code!r}의 이벤트 {normalized_event_id!r}"
                if normalized_event_id is not None
                else f"종목 {normalized_sport_code!r}"
            )
            raise ValueError(
                f"{filter_description}에 해당하는 EventObservation이 없습니다."
            )

        generated_at = datetime.now(UTC)
        content = render_field_inspection_markdown(
            analysis=analysis,
            generated_at=generated_at,
        )
        output_path = build_field_report_output_path(
            generated_at=generated_at,
            sport_code=normalized_sport_code,
            field_path=field_path,
        )
        saved_path = save_report_text(content=content, output_path=output_path)
    except (OSError, ValueError, TemplateError) as error:
        typer.echo(f"필드 분석 보고서 생성에 실패했습니다. {error}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"입력 Observation: {analysis.input_observation_count}개")
    typer.echo(f"분석 Observation: {analysis.analyzed_observation_count}개")
    typer.echo(f"분석 범위 이벤트: {analysis.input_event_count}개")
    typer.echo(f"필드 관측 이벤트: {analysis.observed_event_count}개")
    typer.echo(f"미관측으로 생략한 이벤트: {analysis.unobserved_event_count}개")
    typer.echo(f"필드 분석 보고서 저장 위치: {saved_path}")

    if analysis.field_failures or analysis.resolution_failures:
        typer.echo(
            "일부 Observation을 분석하지 못했습니다. "
            f"필드 값 제외 {len(analysis.field_failures)}건, "
            f"EventObservation 해석 실패 {len(analysis.resolution_failures)}건. "
            "자세한 내용은 보고서를 확인하세요.",
            err=True,
        )


@app.command("inspect-timeline")
def inspect_timeline(
    event_id: str = typer.Option(
        ...,
        "--event-id",
        "-e",
        help="분석할 외부 API 경기 ID",
    ),
) -> None:
    """저장된 Event View 자료에서 이벤트의 설정 필드 타임라인을 분석합니다."""

    normalized_event_id = event_id.strip()
    try:
        if not normalized_event_id:
            raise ValueError("이벤트 ID가 비어 있습니다.")
        sport_code_by_id = load_sport_codes_by_id()
        timeline_config = load_timeline_fields_config()
    except (OSError, ValueError) as error:
        typer.echo(f"타임라인 분석 조건을 준비하지 못했습니다. {error}", err=True)
        raise typer.Exit(code=2) from None

    try:
        resolution = resolve_observed_events(
            observation_file_paths=find_event_observation_paths_for_event(
                normalized_event_id
            ),
            sport_code_by_id=sport_code_by_id,
        )
        analysis = analyze_event_timeline(
            observed_events=resolution.observed_events,
            resolution_failures=resolution.failures,
            event_id=normalized_event_id,
            paths_by_sport_code=timeline_config.paths_by_sport_code,
        )
        generated_at = datetime.now(UTC)
        content = render_event_timeline_markdown(
            analysis=analysis,
            generated_at=generated_at,
        )
        output_path = build_timeline_report_output_path(
            generated_at=generated_at,
            sport_code=analysis.sport_code,
            event_id=analysis.event_id,
        )
        saved_path = save_report_text(content=content, output_path=output_path)
    except (OSError, ValueError, TemplateError) as error:
        typer.echo(f"타임라인 분석 보고서 생성에 실패했습니다. {error}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"분석 이벤트: {analysis.event_id}")
    typer.echo(f"추론 종목: {analysis.sport_code}")
    typer.echo(f"입력 Observation: {analysis.input_observation_count}개")
    typer.echo(f"분석 Observation: {analysis.analyzed_observation_count}개")
    typer.echo(f"변화 감지 Observation: {analysis.changed_observation_count}개")
    typer.echo(f"타임라인 보고서 저장 위치: {saved_path}")

    if analysis.failed_observation_count or analysis.resolution_failures:
        typer.echo(
            "일부 Observation을 분석하지 못했습니다. "
            f"필드 값 분석 실패 {analysis.failed_observation_count}건, "
            f"EventObservation 해석 실패 {len(analysis.resolution_failures)}건. "
            "자세한 내용은 보고서를 확인하세요.",
            err=True,
        )


def _run_event_view_watch(
    *,
    settings: Settings,
    event_ids: list[str],
    interval_seconds: int,
    max_cycles: int | None,
) -> None:
    """이벤트별 종료 상태를 관리하며 Event View를 동적 배치로 반복 수집합니다."""

    cycle_count = 0
    attempt_count = 0
    saved_count = 0
    watched_events = {
        event_id: EventWatchState(event_id=event_id) for event_id in event_ids
    }
    completed_event_count = 0

    try:
        while max_cycles is None or cycle_count < max_cycles:
            completed_event_ids = find_completed_event_ids(
                states=list(watched_events.values()),
                now=_utc_now(),
            )
            for event_id in completed_event_ids:
                del watched_events[event_id]
                completed_event_count += 1
                typer.echo(
                    f"경기 ID {event_id}: 종료 감지 후 15분 추가 수집을 완료했습니다."
                )

            if not watched_events:
                typer.echo("모든 이벤트의 종료 후 추가 수집이 완료되었습니다.")
                break

            cycle_count += 1
            request_batches = build_event_view_request_batches(
                list(watched_events.keys())
            )

            for batch_index, requested_event_ids in enumerate(
                request_batches,
                start=1,
            ):
                attempt_count += 1
                typer.echo("")
                if len(request_batches) == 1:
                    typer.echo(f"[📡 {cycle_count}번째 수집 주기]")
                else:
                    typer.echo(
                        f"[📡 {cycle_count}번째 수집 주기 / "
                        f"배치 {batch_index}/{len(request_batches)}]"
                    )
                typer.echo(f"요청 이벤트 ID: {', '.join(requested_event_ids)}")

                result = _capture_event_view_watch_batch(
                    settings=settings,
                    requested_event_ids=requested_event_ids,
                )
                if result is None:
                    continue

                saved_count += 1
                _update_event_watch_states(
                    watched_events=watched_events,
                    result=result,
                )

            if max_cycles is not None and cycle_count >= max_cycles:
                break

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        typer.echo("")
        typer.echo(
            "❌ 반복 수집을 중단했습니다. "
            f"수집 주기: {cycle_count}회 / "
            f"API 호출: {attempt_count}회 / 저장: {saved_count}개 / "
            f"완료 이벤트: {completed_event_count}개"
        )
        return

    typer.echo("")
    typer.echo(
        "✅ 반복 수집을 완료했습니다. "
        f"수집 주기: {cycle_count}회 / "
        f"API 호출: {attempt_count}회 / 저장: {saved_count}개 / "
        f"완료 이벤트: {completed_event_count}개"
    )


def _capture_event_view_watch_batch(
    *,
    settings: Settings,
    requested_event_ids: list[str],
) -> CaptureResult | None:
    """Event View 배치 하나를 수집·비교하고 성공한 Capture를 반환합니다."""

    try:
        result = capture_event_view(
            base_url=settings.bets_api_base_url,
            token=settings.bets_api_token.get_secret_value(),
            requested_event_ids=requested_event_ids,
        )
    except httpx.RequestError:
        typer.echo("API 서버에 연결하지 못했습니다.", err=True)
        return None
    except OSError:
        typer.echo("파일 저장에 실패했습니다.", err=True)
        return None

    _print_capture_summary(result)
    _print_observation_save_failures(result)

    if result.response.is_error:
        typer.echo("API가 오류 응답을 반환했습니다.", err=True)
        return result

    for observation in result.event_observations:
        _compare_and_save_structure_change(observation)

    return result


def _update_event_watch_states(
    *,
    watched_events: dict[str, EventWatchState],
    result: CaptureResult,
) -> None:
    """성공한 Capture에서 요청 대상 이벤트의 time_status를 상태에 반영합니다."""

    if result.response.is_error:
        return

    if result.metadata.response_analysis_status != "completed":
        return

    try:
        response_json = result.response.json()
    except ValueError:
        return

    for observation in result.event_observations:
        state = watched_events.get(observation.event_id)
        if state is None:
            continue

        try:
            event_data = extract_observed_event(
                observation=observation,
                response_json=response_json,
            )
        except InvalidEventObservationReferenceError as error:
            typer.echo(
                f"경기 ID {observation.event_id}의 종료 상태를 확인하지 못했습니다. "
                f"{error}",
                err=True,
            )
            continue

        transition = apply_event_time_status(
            state=state,
            time_status=event_data.get("time_status"),
            observed_at=result.metadata.captured_at,
        )
        if transition is None:
            continue

        if transition.kind == "finish_detected":
            assert state.finished_detected_at is not None
            collection_deadline = (
                state.finished_detected_at + POST_FINISH_COLLECTION_PERIOD
            )
            typer.echo(
                f"경기 ID {state.event_id}: 종료를 감지했습니다. "
                f"{collection_deadline.isoformat()}까지 추가 수집합니다."
            )
            continue

        typer.echo(
            f"경기 ID {state.event_id}: time_status={transition.time_status}을 "
            "관측하여 종료 감지를 취소했습니다."
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


def _print_odds_collection_summary(result: OddsCollectionResult) -> None:
    """Event Odds 명령의 전체 상태와 이벤트별 결과를 출력합니다."""

    captured_count = sum(
        event_result.status == "captured" for event_result in result.event_results
    )
    failed_count = len(result.event_results) - captured_count

    typer.echo(f"Odds 수집 상태: {result.status}")
    typer.echo(f"Snapshot 저장: {captured_count}개")
    typer.echo(f"처리 실패: {failed_count}개")

    for event_result in result.event_results:
        if event_result.status == "captured":
            typer.echo(
                f"[{event_result.event_id}] captured / "
                f"원문: {event_result.raw_file_path} / "
                f"메타데이터: {event_result.metadata_file_path}"
            )
            continue

        typer.echo(
            f"[{event_result.event_id}] {event_result.status} / "
            f"{event_result.error_type}: {event_result.error_message}",
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


def _parse_odds_event_ids_or_exit(value: str) -> list[str]:
    try:
        return parse_odds_event_ids(value)
    except InvalidOddsEventIdsError as error:
        typer.echo(
            f"이벤트 ID 입력이 올바르지 않습니다. {error}",
            err=True,
        )
        raise typer.Exit(code=2) from None


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


def _print_upcoming_discovery_warnings(
    latest_discoveries: LatestLeagueDiscoveries,
) -> None:
    for failure in latest_discoveries.load_failures:
        typer.echo(
            "Discovery 파일을 읽지 못했습니다: "
            f"{failure.file_path} ({failure.error_type}: {failure.error_message})",
            err=True,
        )

    for unavailable in latest_discoveries.unavailable:
        latest_attempt = unavailable.latest_attempt
        discovery = latest_attempt.discovery
        target = discovery.target
        failure = discovery.failure
        failure_description = (
            f"{failure.error_type}: {failure.error_message}"
            if failure is not None
            else discovery.status
        )
        typer.echo(
            "사용 가능한 결과가 없는 리그입니다: "
            f"{target.sport_code}/{target.league_label}, "
            f"target_date={discovery.target_date.isoformat()} "
            f"({failure_description})",
            err=True,
        )

    for fallback in latest_discoveries.fallbacks:
        latest = fallback.latest_failed
        selected = fallback.selected
        target = selected.discovery.target
        typer.echo(
            "최신 시도가 실패하여 이전 Discovery를 사용합니다: "
            f"{target.sport_code}/{target.league_label}, "
            f"target_date={selected.discovery.target_date.isoformat()}, "
            f"latest={latest.file_path}, selected={selected.file_path}",
            err=True,
        )

    for selected in latest_discoveries.selected:
        if selected.discovery.status != "partial":
            continue
        target = selected.discovery.target
        typer.echo(
            "응답 이슈가 있는 partial Discovery를 사용합니다: "
            f"{target.sport_code}/{target.league_label}, "
            f"target_date={selected.discovery.target_date.isoformat()}, "
            f"file={selected.file_path}",
            err=True,
        )


def _print_upcoming_candidate(
    *,
    index: int,
    candidate: UpcomingCandidate,
    now: datetime,
) -> None:
    event = candidate.event
    league_name = event.league.name or "이름 없음"
    home_name = event.home.name or "이름 없음"
    away_name = event.away.name or "이름 없음"
    remaining_time = _format_remaining_time(
        scheduled_at=event.scheduled_at_utc,
        now=now,
    )

    typer.echo("")
    typer.echo(f"[{index}] 이벤트 ID: {event.event_id}")
    typer.echo(
        f"  종목/리그: {event.sport_code} / {candidate.league_label} ({league_name})"
    )
    typer.echo(f"  대진: {home_name} vs {away_name}")
    typer.echo(f"  시작 예정(KST): {event.scheduled_at_kst.isoformat()}")
    typer.echo(f"  시작 예정(UTC): {event.scheduled_at_utc.isoformat()}")
    typer.echo(f"  남은 시간: {remaining_time}")
    typer.echo(
        "  Discovery: "
        f"{candidate.discovery_status} / "
        f"{candidate.discovery_completed_at.isoformat()}"
    )
    typer.echo(f"  Discovery 파일: {candidate.discovery_file_path}")


def _format_remaining_time(*, scheduled_at: datetime, now: datetime) -> str:
    remaining_seconds = max(0, int((scheduled_at - now).total_seconds()))
    minutes, seconds = divmod(remaining_seconds, 60)
    return f"{minutes}분 {seconds}초"


def _utc_now() -> datetime:
    return datetime.now(UTC)


if __name__ == "__main__":
    app()
