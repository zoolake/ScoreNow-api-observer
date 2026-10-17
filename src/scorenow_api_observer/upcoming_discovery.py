from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import httpx

from scorenow_api_observer.bets_api_client import (
    UPCOMING_EVENTS_ENDPOINT,
    get_upcoming_events,
)
from scorenow_api_observer.upcoming_models import (
    DiscoveredUpcomingEvent,
    UpcomingCaptureMetadata,
    UpcomingDiscovery,
    UpcomingDiscoveryFailure,
    UpcomingDiscoveryTarget,
    UpcomingRequestQuery,
)
from scorenow_api_observer.upcoming_response import (
    InvalidUpcomingResponseShapeError,
    ObservableUpcomingEvent,
    analyze_upcoming_response,
)
from scorenow_api_observer.upcoming_storage import (
    UPCOMING_DISCOVERY_DIRECTORY,
    UPCOMING_METADATA_DIRECTORY,
    UPCOMING_RAW_DATA_DIRECTORY,
    save_upcoming_capture_metadata,
    save_upcoming_discovery,
    save_upcoming_raw_response,
)
from scorenow_api_observer.upcoming_targets import UpcomingTarget

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
    """Upcoming Discovery 실행 결과와 저장된 통합 파일 경로입니다."""

    discovery: UpcomingDiscovery
    discovery_file_path: Path
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
    """설정된 모든 종목·리그의 Upcoming 응답을 수집해 하나로 통합합니다."""

    if not targets:
        raise ValueError("Upcoming 조회 대상은 한 개 이상이어야 합니다.")

    clock = now or _utc_now
    started_at = _require_aware_datetime(clock())
    discovery_run_id = _build_discovery_run_id(started_at)
    requested_targets = [_to_discovery_target(target) for target in targets]
    captures: list[UpcomingCaptureResult] = []
    failures: list[UpcomingDiscoveryFailure] = []
    capture_metadata_file_paths: list[str] = []
    events_by_id: dict[str, DiscoveredUpcomingEvent] = {}
    completed_target_count = 0
    has_response_issues = False

    for target_index, target in enumerate(targets):
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
            failures.append(
                _failure(
                    target,
                    error_type=type(error).__name__,
                    error_message="API 서버에 연결하지 못했습니다.",
                )
            )
            continue
        except OSError as error:
            failures.append(
                _failure(
                    target,
                    error_type=type(error).__name__,
                    error_message=f"Capture 파일 저장에 실패했습니다: {error}",
                )
            )
            continue

        captures.append(capture)
        capture_metadata_file_paths.append(str(capture.metadata_file_path))

        if capture.response.is_error:
            failures.append(
                _failure(
                    target,
                    error_type="HttpStatusError",
                    error_message=(
                        f"API가 HTTP {capture.response.status_code} 오류를 반환했습니다."
                    ),
                )
            )
            if capture.response.status_code in FATAL_HTTP_STATUS_CODES:
                _append_skipped_target_failures(
                    failures=failures,
                    targets=targets[target_index + 1 :],
                    status_code=capture.response.status_code,
                )
                break
            continue

        if capture.metadata.response_analysis_status != "completed":
            failures.append(
                _failure(
                    target,
                    error_type="ResponseAnalysisError",
                    error_message=(
                        "Upcoming 응답을 분석하지 못했습니다: "
                        f"{capture.metadata.response_analysis_status}"
                    ),
                )
            )
            continue

        completed_target_count += 1
        if capture.metadata.response_issues:
            has_response_issues = True

        for observable_event in capture.observable_events:
            events_by_id.setdefault(
                observable_event.event_id,
                _to_discovered_event(
                    observable_event=observable_event,
                    metadata_file_path=capture.metadata_file_path,
                ),
            )

    completed_at = _require_aware_datetime(clock())
    discovery = UpcomingDiscovery(
        discovery_run_id=discovery_run_id,
        status=_determine_discovery_status(
            completed_target_count=completed_target_count,
            has_failures=bool(failures),
            has_response_issues=has_response_issues,
        ),
        started_at=started_at,
        completed_at=completed_at,
        target_date=target_date,
        requested_targets=requested_targets,
        capture_metadata_file_paths=capture_metadata_file_paths,
        events=sorted(
            events_by_id.values(),
            key=lambda event: (event.scheduled_at_utc, event.event_id),
        ),
        failures=failures,
    )
    discovery_file_path = save_upcoming_discovery(
        discovery,
        base_directory=discovery_base_directory,
    )

    return UpcomingDiscoveryResult(
        discovery=discovery,
        discovery_file_path=discovery_file_path,
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


def _append_skipped_target_failures(
    *,
    failures: list[UpcomingDiscoveryFailure],
    targets: list[UpcomingTarget],
    status_code: int,
) -> None:
    for target in targets:
        failures.append(
            _failure(
                target,
                error_type="SkippedTargetError",
                error_message=(
                    f"HTTP {status_code} 오류로 남은 API 호출을 중단하여 조회하지 "
                    "않았습니다."
                ),
            )
        )


def _determine_discovery_status(
    *,
    completed_target_count: int,
    has_failures: bool,
    has_response_issues: bool,
) -> Literal["completed", "partial", "failed"]:
    if completed_target_count == 0:
        return "failed"
    if has_failures or has_response_issues:
        return "partial"
    return "completed"


def _response_elapsed_ms(response: httpx.Response) -> float:
    try:
        elapsed_seconds = response.elapsed.total_seconds()
    except RuntimeError:
        return 0.0
    return round(elapsed_seconds * 1000, 2)
