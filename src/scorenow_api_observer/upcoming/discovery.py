from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from scorenow_api_observer.bets_api_client import (
    UPCOMING_EVENTS_ENDPOINT,
    get_upcoming_events,
)
from scorenow_api_observer.upcoming.models import (
    DiscoveredUpcomingEvent,
    LeagueUpcomingDiscovery,
    UpcomingCaptureMetadata,
    UpcomingDiscoveryFailure,
    UpcomingDiscoveryRun,
    UpcomingDiscoveryStatus,
    UpcomingDiscoveryTarget,
    UpcomingRequestQuery,
)
from scorenow_api_observer.upcoming.response import (
    InvalidUpcomingResponseShapeError,
    ObservableUpcomingEvent,
    analyze_upcoming_response,
)
from scorenow_api_observer.upcoming.storage import (
    UPCOMING_DISCOVERY_DIRECTORY,
    UPCOMING_METADATA_DIRECTORY,
    UPCOMING_RAW_DATA_DIRECTORY,
    save_league_upcoming_discovery,
    save_upcoming_capture_metadata,
    save_upcoming_discovery_run,
    save_upcoming_raw_response,
)
from scorenow_api_observer.upcoming.targets import UpcomingTarget

KST = ZoneInfo("Asia/Seoul")
FATAL_HTTP_STATUS_CODES = frozenset({401, 402, 403, 429})


@dataclass(frozen=True)
class UpcomingCaptureResult:
    """한 번의 Upcoming 호출에서 저장한 Capture와 분석 결과입니다."""

    response: httpx.Response
    metadata: UpcomingCaptureMetadata
    metadata_file_path: Path
    observable_events: list[ObservableUpcomingEvent]


@dataclass(frozen=True)
class UpcomingDiscoveryResult:
    """한 번의 실행 기록과 저장된 리그별 Discovery 결과입니다."""

    run: UpcomingDiscoveryRun
    run_file_path: Path
    league_discoveries: list[LeagueUpcomingDiscovery]
    league_discovery_file_paths: list[Path]
    captures: list[UpcomingCaptureResult]


def discover_upcoming_events(
    *,
    base_url: str,
    token: str,
    target_date: date,
    targets: list[UpcomingTarget],
    now: Callable[[], datetime] | None = None,
    raw_base_directory: Path = UPCOMING_RAW_DATA_DIRECTORY,
    metadata_base_directory: Path = UPCOMING_METADATA_DIRECTORY,
    discovery_base_directory: Path = UPCOMING_DISCOVERY_DIRECTORY,
) -> UpcomingDiscoveryResult:
    """선택된 종목·리그를 조회하고 리그별 결과와 실행 기록을 저장합니다."""

    if not targets:
        raise ValueError("Upcoming 조회 대상은 한 개 이상이어야 합니다.")

    clock = now or _utc_now
    started_at = _require_aware_datetime(clock())
    discovery_run_id = _build_discovery_run_id(started_at)
    league_discoveries: list[LeagueUpcomingDiscovery] = []
    league_discovery_file_paths: list[Path] = []
    captures: list[UpcomingCaptureResult] = []

    for target_index, target in enumerate(targets):
        fatal_status_code: int | None = None
        try:
            capture = capture_upcoming_target(
                base_url=base_url,
                token=token,
                target_date=target_date,
                target=target,
                discovery_run_id=discovery_run_id,
                now=clock,
                raw_base_directory=raw_base_directory,
                metadata_base_directory=metadata_base_directory,
            )
        except httpx.RequestError as error:
            discovery = _failed_league_discovery(
                discovery_run_id=discovery_run_id,
                target_date=target_date,
                target=target,
                completed_at=_require_aware_datetime(clock()),
                capture_metadata_file_path=None,
                error_type=type(error).__name__,
                error_message="API 서버에 연결하지 못했습니다.",
            )
        except OSError as error:
            discovery = _failed_league_discovery(
                discovery_run_id=discovery_run_id,
                target_date=target_date,
                target=target,
                completed_at=_require_aware_datetime(clock()),
                capture_metadata_file_path=None,
                error_type=type(error).__name__,
                error_message=f"Capture 파일 저장에 실패했습니다: {error}",
            )
        else:
            captures.append(capture)
            if (
                capture.response.is_error
                and capture.response.status_code in FATAL_HTTP_STATUS_CODES
            ):
                fatal_status_code = capture.response.status_code
            discovery = _discovery_from_capture(
                discovery_run_id=discovery_run_id,
                target_date=target_date,
                target=target,
                capture=capture,
            )

        discovery_file_path = save_league_upcoming_discovery(
            discovery,
            base_directory=discovery_base_directory,
        )
        league_discoveries.append(discovery)
        league_discovery_file_paths.append(discovery_file_path)

        if fatal_status_code is not None:
            for skipped_target in targets[target_index + 1 :]:
                skipped_discovery = _failed_league_discovery(
                    discovery_run_id=discovery_run_id,
                    target_date=target_date,
                    target=skipped_target,
                    completed_at=discovery.completed_at,
                    capture_metadata_file_path=None,
                    error_type="SkippedTargetError",
                    error_message=(
                        f"HTTP {fatal_status_code} 오류로 남은 API 호출을 "
                        "중단하여 조회하지 않았습니다."
                    ),
                )
                skipped_file_path = save_league_upcoming_discovery(
                    skipped_discovery,
                    base_directory=discovery_base_directory,
                )
                league_discoveries.append(skipped_discovery)
                league_discovery_file_paths.append(skipped_file_path)
            break

    completed_at = _require_aware_datetime(clock())
    run = UpcomingDiscoveryRun(
        discovery_run_id=discovery_run_id,
        status=_determine_discovery_status(league_discoveries),
        started_at=started_at,
        completed_at=completed_at,
        target_date=target_date,
        requested_targets=[_to_discovery_target(target) for target in targets],
        league_discovery_file_paths=[
            str(file_path) for file_path in league_discovery_file_paths
        ],
    )
    run_file_path = save_upcoming_discovery_run(
        run,
        base_directory=discovery_base_directory,
    )

    return UpcomingDiscoveryResult(
        run=run,
        run_file_path=run_file_path,
        league_discoveries=league_discoveries,
        league_discovery_file_paths=league_discovery_file_paths,
        captures=captures,
    )


def capture_upcoming_target(
    *,
    base_url: str,
    token: str,
    target_date: date,
    target: UpcomingTarget,
    discovery_run_id: str,
    now: Callable[[], datetime] | None = None,
    raw_base_directory: Path = UPCOMING_RAW_DATA_DIRECTORY,
    metadata_base_directory: Path = UPCOMING_METADATA_DIRECTORY,
) -> UpcomingCaptureResult:
    """하나의 종목·리그를 조회하고 원문과 CaptureMetadata를 저장합니다."""

    response = get_upcoming_events(
        base_url=base_url,
        token=token,
        sport_id=target.sport_id,
        league_id=target.league_id,
        target_date=target_date,
    )
    clock = now or _utc_now
    captured_at = _require_aware_datetime(clock())
    raw_file_path = save_upcoming_raw_response(
        response_body=response.content,
        captured_at=captured_at,
        league_label=target.league_label,
        base_directory=raw_base_directory,
    )

    try:
        response_json = response.json()
    except ValueError:
        response_analysis_status = "invalid_json"
        returned_event_ids = []
        response_issues = []
        observable_events = []
    else:
        try:
            analysis = analyze_upcoming_response(
                response_json=response_json,
                requested_sport_id=target.sport_id,
                requested_league_id=target.league_id,
                sport_code=target.sport_code,
            )
        except InvalidUpcomingResponseShapeError:
            response_analysis_status = "invalid_response_shape"
            returned_event_ids = []
            response_issues = []
            observable_events = []
        else:
            response_analysis_status = "completed"
            returned_event_ids = analysis.returned_event_ids
            response_issues = analysis.issues
            observable_events = analysis.observable_events

    metadata = UpcomingCaptureMetadata(
        discovery_run_id=discovery_run_id,
        captured_at=captured_at,
        provider="betsapi",
        endpoint=UPCOMING_EVENTS_ENDPOINT,
        http_method="GET",
        query=UpcomingRequestQuery(
            sport_id=target.sport_id,
            league_id=target.league_id,
            day=target_date.strftime("%Y%m%d"),
        ),
        response_analysis_status=response_analysis_status,
        returned_event_ids=returned_event_ids,
        response_issues=response_issues,
        http_status_code=response.status_code,
        elapsed_ms=_response_elapsed_ms(response),
        response_size_bytes=len(response.content),
        content_type=response.headers.get("content-type"),
        raw_file_path=str(raw_file_path),
    )
    metadata_file_path = save_upcoming_capture_metadata(
        metadata,
        base_directory=metadata_base_directory,
    )

    return UpcomingCaptureResult(
        response=response,
        metadata=metadata,
        metadata_file_path=metadata_file_path,
        observable_events=observable_events,
    )


def _discovery_from_capture(
    *,
    discovery_run_id: str,
    target_date: date,
    target: UpcomingTarget,
    capture: UpcomingCaptureResult,
) -> LeagueUpcomingDiscovery:
    if capture.response.is_error:
        return _failed_league_discovery(
            discovery_run_id=discovery_run_id,
            target_date=target_date,
            target=target,
            completed_at=capture.metadata.captured_at,
            capture_metadata_file_path=str(capture.metadata_file_path),
            error_type="HttpStatusError",
            error_message=(
                f"API가 HTTP {capture.response.status_code} 오류를 반환했습니다."
            ),
        )

    if capture.metadata.response_analysis_status != "completed":
        return _failed_league_discovery(
            discovery_run_id=discovery_run_id,
            target_date=target_date,
            target=target,
            completed_at=capture.metadata.captured_at,
            capture_metadata_file_path=str(capture.metadata_file_path),
            error_type="ResponseAnalysisError",
            error_message=(
                "Upcoming 응답을 분석하지 못했습니다: "
                f"{capture.metadata.response_analysis_status}"
            ),
        )

    events = [
        _to_discovered_event(
            observable_event=observable_event,
            metadata_file_path=capture.metadata_file_path,
        )
        for observable_event in capture.observable_events
    ]
    return LeagueUpcomingDiscovery(
        discovery_run_id=discovery_run_id,
        status="partial" if capture.metadata.response_issues else "completed",
        completed_at=capture.metadata.captured_at,
        target_date=target_date,
        target=_to_discovery_target(target),
        capture_metadata_file_path=str(capture.metadata_file_path),
        events=sorted(
            events,
            key=lambda event: (event.scheduled_at_utc, event.event_id),
        ),
        failure=None,
    )


def _failed_league_discovery(
    *,
    discovery_run_id: str,
    target_date: date,
    target: UpcomingTarget,
    completed_at: datetime,
    capture_metadata_file_path: str | None,
    error_type: str,
    error_message: str,
) -> LeagueUpcomingDiscovery:
    return LeagueUpcomingDiscovery(
        discovery_run_id=discovery_run_id,
        status="failed",
        completed_at=completed_at,
        target_date=target_date,
        target=_to_discovery_target(target),
        capture_metadata_file_path=capture_metadata_file_path,
        events=[],
        failure=_failure(
            target,
            error_type=error_type,
            error_message=error_message,
        ),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Discovery 실행 시각에는 시간대 정보가 필요합니다.")
    return value


def _build_discovery_run_id(started_at: datetime) -> str:
    return started_at.astimezone(KST).strftime("%Y-%m-%dT%H-%M-%S_KST")


def _to_discovery_target(target: UpcomingTarget) -> UpcomingDiscoveryTarget:
    return UpcomingDiscoveryTarget(
        sport_id=target.sport_id,
        sport_code=target.sport_code,
        league_id=target.league_id,
        league_label=target.league_label,
    )


def _to_discovered_event(
    *,
    observable_event: ObservableUpcomingEvent,
    metadata_file_path: Path,
) -> DiscoveredUpcomingEvent:
    return DiscoveredUpcomingEvent(
        event_id=observable_event.event_id,
        sport_id=observable_event.sport_id,
        sport_code=observable_event.sport_code,
        time_status=observable_event.time_status,
        scheduled_at_utc=observable_event.scheduled_at_utc,
        scheduled_at_kst=observable_event.scheduled_at_kst,
        league=observable_event.league,
        home=observable_event.home,
        away=observable_event.away,
        source_capture_metadata_file_path=str(metadata_file_path),
        result_index=observable_event.result_index,
    )


def _failure(
    target: UpcomingTarget,
    *,
    error_type: str,
    error_message: str,
) -> UpcomingDiscoveryFailure:
    return UpcomingDiscoveryFailure(
        sport_id=target.sport_id,
        league_id=target.league_id,
        league_label=target.league_label,
        error_type=error_type,
        error_message=error_message,
    )


def _determine_discovery_status(
    discoveries: list[LeagueUpcomingDiscovery],
) -> UpcomingDiscoveryStatus:
    usable_count = sum(
        discovery.status in ("completed", "partial") for discovery in discoveries
    )
    if usable_count == 0:
        return "failed"
    if any(discovery.status != "completed" for discovery in discoveries):
        return "partial"
    return "completed"


def _response_elapsed_ms(response: httpx.Response) -> float:
    try:
        elapsed_seconds = response.elapsed.total_seconds()
    except RuntimeError:
        return 0.0
    return round(elapsed_seconds * 1000, 2)
