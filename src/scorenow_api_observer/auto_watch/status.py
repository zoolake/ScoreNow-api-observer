from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from scorenow_api_observer.auto_watch.config import (
    AUTO_WATCH_CONFIG_PATH,
    AutoWatchCollectionMode,
    AutoWatchConfig,
    load_auto_watch_config,
)
from scorenow_api_observer.auto_watch.exceptions import (
    AUTO_WATCH_EXCEPTION_DIRECTORY,
    AutoWatchExceptionRecord,
)
from scorenow_api_observer.auto_watch.heartbeat import (
    AUTO_WATCH_HEARTBEAT_PATH,
    AutoWatchHeartbeat,
    heartbeat_stale_after_seconds,
    load_auto_watch_heartbeat,
)
from scorenow_api_observer.auto_watch.models import AutoWatchActiveEvent, AutoWatchState
from scorenow_api_observer.auto_watch.policy import auto_watch_collection_deadline
from scorenow_api_observer.auto_watch.state import (
    AUTO_WATCH_STATE_PATH,
    load_auto_watch_state,
)
from scorenow_api_observer.bets_api_request_log import (
    BETS_API_REQUEST_LOG_DIRECTORY,
    BetsApiEndpoint,
    BetsApiRequestRecord,
    RequestCategory,
)
from scorenow_api_observer.event_view.request_log import (
    EVENT_VIEW_REQUEST_LOG_DIRECTORY,
    EventViewApiRequestRecord,
)

KST = ZoneInfo("Asia/Seoul")
REQUEST_CATEGORIES: tuple[RequestCategory, ...] = (
    "football_only",
    "baseball_only",
    "mixed",
    "unknown",
)
API_ENDPOINTS: tuple[BetsApiEndpoint, ...] = (
    "/v1/event/view",
    "/v3/events/upcoming",
    "/v2/event/odds",
)
ApiRequestRecord = BetsApiRequestRecord | EventViewApiRequestRecord
Sport = Literal["football", "baseball"]


@dataclass(frozen=True)
class StatusReadFailure:
    area: str
    file_path: Path
    error_message: str


@dataclass(frozen=True)
class StoredAutoWatchException:
    record: AutoWatchExceptionRecord
    file_path: Path


@dataclass(frozen=True)
class AutoWatchRequestStatus:
    window_start: datetime
    window_end: datetime
    current_window_records: list[ApiRequestRecord]
    daily_records: list[ApiRequestRecord]
    valid_rate_limit_records: dict[RequestCategory, ApiRequestRecord]

    def current_window_category_counts(self) -> dict[RequestCategory, int]:
        counts = Counter(
            record.request_category for record in self.current_window_records
        )
        return {category: counts[category] for category in REQUEST_CATEGORIES}

    def daily_category_counts(self) -> dict[RequestCategory, int]:
        counts = Counter(record.request_category for record in self.daily_records)
        return {category: counts[category] for category in REQUEST_CATEGORIES}

    def current_window_endpoint_counts(self) -> dict[BetsApiEndpoint, int]:
        counts = Counter(record.endpoint for record in self.current_window_records)
        return {endpoint: counts[endpoint] for endpoint in API_ENDPOINTS}

    def daily_endpoint_counts(self) -> dict[BetsApiEndpoint, int]:
        counts = Counter(record.endpoint for record in self.daily_records)
        return {endpoint: counts[endpoint] for endpoint in API_ENDPOINTS}


@dataclass(frozen=True)
class AutoWatchStatusReport:
    checked_at: datetime
    target_date_kst: date
    config: AutoWatchConfig | None
    state: AutoWatchState | None
    heartbeat: AutoWatchHeartbeat | None
    requests: AutoWatchRequestStatus
    exceptions: list[StoredAutoWatchException]
    recent_exception_limit: int
    show_all_exceptions: bool
    failures: list[StatusReadFailure]


def build_auto_watch_status_report(
    *,
    now: datetime,
    target_date_kst: date,
    recent_exception_limit: int = 10,
    show_all_exceptions: bool = False,
    config_path: Path = AUTO_WATCH_CONFIG_PATH,
    state_path: Path = AUTO_WATCH_STATE_PATH,
    heartbeat_path: Path = AUTO_WATCH_HEARTBEAT_PATH,
    request_base_directory: Path = BETS_API_REQUEST_LOG_DIRECTORY,
    legacy_event_view_request_base_directory: Path = EVENT_VIEW_REQUEST_LOG_DIRECTORY,
    exception_base_directory: Path = AUTO_WATCH_EXCEPTION_DIRECTORY,
) -> AutoWatchStatusReport:
    """로컬 파일만 읽어 Auto-watch 상태 보고서 자료를 만듭니다."""

    if recent_exception_limit < 1:
        raise ValueError("최근 예외 표시 개수는 1 이상이어야 합니다.")
    normalized_now = _as_utc(now)
    failures: list[StatusReadFailure] = []

    config = _load_optional_component(
        area="상태 정책",
        file_path=config_path,
        loader=lambda: load_auto_watch_config(config_path),
        failures=failures,
        missing_is_failure=True,
    )
    state = _load_optional_component(
        area="활성 경기 상태",
        file_path=state_path,
        loader=lambda: load_auto_watch_state(state_path),
        failures=failures,
        missing_is_failure=False,
    )
    heartbeat = _load_optional_component(
        area="실행 상태",
        file_path=heartbeat_path,
        loader=lambda: load_auto_watch_heartbeat(heartbeat_path),
        failures=failures,
        missing_is_failure=False,
    )

    day_start_utc, day_end_utc = kst_day_utc_window(target_date_kst)
    window_start_utc, window_end_utc = current_hour_window(normalized_now)
    request_records = load_request_records(
        windows=((day_start_utc, day_end_utc), (window_start_utc, window_end_utc)),
        request_base_directory=request_base_directory,
        legacy_base_directory=legacy_event_view_request_base_directory,
        failures=failures,
    )
    daily_records = [
        record
        for record in request_records
        if day_start_utc <= record.requested_at < day_end_utc
    ]
    current_window_records = [
        record
        for record in request_records
        if (
            window_start_utc <= record.requested_at < window_end_utc
            and record.requested_at <= normalized_now
        )
    ]
    valid_rate_limit_records = latest_valid_rate_limit_records(
        current_window_records,
        window_end=window_end_utc,
    )

    exceptions = load_exceptions_for_window(
        start=day_start_utc,
        end=day_end_utc,
        base_directory=exception_base_directory,
        failures=failures,
    )

    return AutoWatchStatusReport(
        checked_at=normalized_now,
        target_date_kst=target_date_kst,
        config=config,
        state=state,
        heartbeat=heartbeat,
        requests=AutoWatchRequestStatus(
            window_start=window_start_utc,
            window_end=window_end_utc,
            current_window_records=sorted(
                current_window_records,
                key=lambda record: record.requested_at,
            ),
            daily_records=sorted(
                daily_records,
                key=lambda record: record.requested_at,
            ),
            valid_rate_limit_records=valid_rate_limit_records,
        ),
        exceptions=exceptions,
        recent_exception_limit=recent_exception_limit,
        show_all_exceptions=show_all_exceptions,
        failures=failures,
    )


def render_auto_watch_status(report: AutoWatchStatusReport) -> str:
    """Auto-watch 상태 자료를 여러 줄의 사용자용 한국어로 렌더링합니다."""

    lines = [
        "📊 Auto-watch 현재 상태",
        "",
        "[상태 확인 시각]",
        f"  • KST: {_format_datetime(report.checked_at, KST)}",
        f"  • UTC: {_format_datetime(report.checked_at, UTC)}",
    ]
    _render_heartbeat(lines, report)
    _render_active_events(lines, report)
    _render_request_status(lines, report)
    _render_exception_status(lines, report)
    _render_failures(lines, report.failures)
    return "\n".join(lines) + "\n"


def _render_heartbeat(lines: list[str], report: AutoWatchStatusReport) -> None:
    lines.extend(["", "[실행 상태]"])
    heartbeat = report.heartbeat
    if heartbeat is None:
        lines.append("  • 실행 상태 기록이 없습니다.")
        return

    if heartbeat.status == "running":
        age_seconds = (report.checked_at - heartbeat.last_cycle_at).total_seconds()
        stale_after_seconds = heartbeat_stale_after_seconds(heartbeat.interval_seconds)
        if age_seconds <= stale_after_seconds:
            lines.append("  • 상태: 정상 실행 중")
        else:
            lines.append("  ⚠️ 상태: 최근 처리 주기가 늦어 확인이 필요합니다.")
        lines.append(
            f"  • 마지막 처리 주기: {_format_datetime(heartbeat.last_cycle_at, KST)} "
            f"({_format_duration(max(0, int(age_seconds)))} 전)"
        )
    elif heartbeat.status == "failed":
        lines.append("  ❌ 상태: 오류로 중단됨")
        lines.append(f"  • 중단 내용: {heartbeat.failure_message}")
    else:
        lines.append("  • 상태: 정상 중단됨")

    lines.extend(
        [
            f"  • 시작 시각: {_format_datetime(heartbeat.process_started_at, KST)}",
            f"  • 수집 간격: {heartbeat.interval_seconds}초",
            f"  • 프로세스 ID: {heartbeat.process_id}",
        ]
    )
    if heartbeat.stopped_at is not None:
        lines.append(f"  • 중단 시각: {_format_datetime(heartbeat.stopped_at, KST)}")


def _render_active_events(lines: list[str], report: AutoWatchStatusReport) -> None:
    lines.extend(["", "[활성 경기]"])
    state = report.state
    if state is None:
        lines.append("  • 저장된 활성 경기 상태가 없습니다.")
        return

    collecting_events = [
        event for event in state.active_events if event.stop_decided_at is None
    ]
    pending_events = [
        event for event in state.active_events if event.stop_decided_at is not None
    ]
    if not collecting_events:
        lines.append("  • 현재 수집 중인 경기가 없습니다.")
    else:
        lines.append(f"  • 현재 수집 중: {len(collecting_events)}개")
        for index, event in enumerate(collecting_events, start=1):
            _render_active_event(lines, index=index, event=event, report=report)

    if not pending_events:
        return
    lines.extend(
        [
            "",
            "[주의 필요]",
            (
                f"  ⚠️ 예외 파일 저장을 재시도하는 경기가 "
                f"{len(pending_events)}개 있습니다."
            ),
        ]
    )
    for event in pending_events:
        lines.extend(
            [
                f"  • 경기 ID: {event.event_id}",
                f"    중단 상태: time_status={_format_time_status(event.last_time_status)}",
                "    추가 API 호출: 하지 않음",
                "    현재 작업: 예외 JSON 저장 재시도",
            ]
        )
        if event.stop_decided_at is not None:
            lines.append(
                "    중단 결정 시각: " + _format_datetime(event.stop_decided_at, KST)
            )


def _render_active_event(
    lines: list[str],
    *,
    index: int,
    event: AutoWatchActiveEvent,
    report: AutoWatchStatusReport,
) -> None:
    mode = (
        report.config.classify_time_status(event.last_time_status)
        if report.config is not None
        else None
    )
    lines.extend(
        [
            "",
            f"  {index}. 경기 ID {event.event_id}",
            f"     • 종목/리그: {event.sport_code} / {event.league_label}",
            (
                "     • 예정 시각: "
                f"{_format_datetime(event.scheduled_at_utc, KST)} KST / "
                f"{_format_datetime(event.scheduled_at_utc, UTC)} UTC"
            ),
            "     • 현재 상태: "
            f"time_status={_format_time_status(event.last_time_status)}"
            + (f" / {_mode_label(mode)}" if mode is not None else ""),
        ]
    )
    deadline = (
        auto_watch_collection_deadline(event=event, config=report.config)
        if report.config is not None
        else None
    )
    if deadline is None:
        lines.append("     • 수집 종료 예정: 없음")
    else:
        remaining_seconds = int((deadline - report.checked_at).total_seconds())
        remaining_text = (
            _format_duration(remaining_seconds) + " 남음"
            if remaining_seconds >= 0
            else _format_duration(abs(remaining_seconds)) + " 경과"
        )
        lines.append(
            f"     • 수집 종료 예정: {_format_datetime(deadline, KST)} KST "
            f"({remaining_text})"
        )
    if event.last_capture_metadata_path is not None:
        lines.append(
            f"     • 마지막 CaptureMetadata: {event.last_capture_metadata_path}"
        )


def _render_request_status(lines: list[str], report: AutoWatchStatusReport) -> None:
    current_counts = report.requests.current_window_category_counts()
    current_endpoint_counts = report.requests.current_window_endpoint_counts()
    current_total = len(report.requests.current_window_records)
    sport_counts = sport_request_counts(report.requests.current_window_records)
    lines.extend(
        [
            "",
            "[현재 BETS API 요청 제한 구간]",
            (
                "  • KST: "
                f"{_format_datetime(report.requests.window_start, KST)} ~ "
                f"{_format_datetime(report.requests.window_end, KST)}"
            ),
            (
                "  • UTC: "
                f"{_format_datetime(report.requests.window_start, UTC)} ~ "
                f"{_format_datetime(report.requests.window_end, UTC)}"
            ),
            "",
            "[현재 구간 BETS API 요청]",
            f"  • 전체 요청 시도: {current_total}회",
            (f"  • Event View: {current_endpoint_counts['/v1/event/view']}회"),
            (f"  • Upcoming: {current_endpoint_counts['/v3/events/upcoming']}회"),
            (f"  • Event Odds: {current_endpoint_counts['/v2/event/odds']}회"),
            "",
            "[현재 구간 종목 분류]",
            f"  • 축구 전용: {current_counts['football_only']}회",
            f"  • 야구 전용: {current_counts['baseball_only']}회",
            f"  • 축구·야구 혼합: {current_counts['mixed']}회",
            f"  • 종목 분류 불가: {current_counts['unknown']}회",
        ]
    )
    if report.config is not None:
        limits = report.config.request_limits
        lines.extend(
            [
                "",
                "[현재 구간 요청 한도 — 로컬 기록 기준]",
                _format_limit_line(
                    label="Soccer API",
                    count=sport_counts["football"],
                    limit=limits.soccer_per_hour,
                    warning_percent=limits.warning_percent,
                    danger_percent=limits.danger_percent,
                ),
                _format_limit_line(
                    label="Baseball API",
                    count=sport_counts["baseball"],
                    limit=limits.baseball_per_hour,
                    warning_percent=limits.warning_percent,
                    danger_percent=limits.danger_percent,
                ),
                "  ℹ️ 혼합·종목 불명 요청은 안전하게 양쪽에 포함했습니다.",
                "  ℹ️ 현재 저장소에 기록된 요청만 포함한 값입니다.",
            ]
        )

    completed_count = sum(
        record.outcome == "completed"
        for record in report.requests.current_window_records
    )
    request_error_count = sum(
        record.outcome == "request_error"
        for record in report.requests.current_window_records
    )
    started_count = sum(
        record.outcome == "started" for record in report.requests.current_window_records
    )
    too_many_requests_count = sum(
        record.http_status_code == 429
        for record in report.requests.current_window_records
    )
    lines.extend(
        [
            "",
            "[현재 구간 요청 결과]",
            f"  • HTTP 응답 완료: {completed_count}회",
            f"  • 연결 실패: {request_error_count}회",
            f"  • 완료 정보가 없는 요청: {started_count}회",
            f"  • HTTP 429: {too_many_requests_count}회",
        ]
    )

    _render_rate_limit_records(lines, report)

    daily_counts = report.requests.daily_category_counts()
    daily_endpoint_counts = report.requests.daily_endpoint_counts()
    lines.extend(
        [
            "",
            f"[{report.target_date_kst.isoformat()} KST 누적 요청]",
            f"  • 전체 요청 시도: {len(report.requests.daily_records)}회",
            f"  • Event View: {daily_endpoint_counts['/v1/event/view']}회",
            f"  • Upcoming: {daily_endpoint_counts['/v3/events/upcoming']}회",
            f"  • Event Odds: {daily_endpoint_counts['/v2/event/odds']}회",
            "",
            f"[{report.target_date_kst.isoformat()} KST 누적 종목 분류]",
            f"  • 축구 전용: {daily_counts['football_only']}회",
            f"  • 야구 전용: {daily_counts['baseball_only']}회",
            f"  • 혼합: {daily_counts['mixed']}회",
            f"  • 분류 불가: {daily_counts['unknown']}회",
        ]
    )


def _render_rate_limit_records(
    lines: list[str],
    report: AutoWatchStatusReport,
) -> None:
    lines.extend(["", "[BETS API 응답 기준 현재 구간 요청 한도]"])
    records = report.requests.valid_rate_limit_records
    if not records:
        lines.append("  • 현재 구간 종료 시각과 일치하는 X-RateLimit 응답이 없습니다.")
        return

    for category in REQUEST_CATEGORIES:
        record = records.get(category)
        if record is None or record.rate_limit is None:
            continue
        rate_limit = record.rate_limit
        lines.append(
            "  • "
            f"{_request_category_label(category)} / "
            f"{_endpoint_label(record.endpoint)} 응답"
        )
        if rate_limit.limit is not None:
            lines.append(f"    시간당 한도: {rate_limit.limit:,}회")
        if rate_limit.remaining is not None:
            lines.append(f"    남은 요청: {rate_limit.remaining:,}회")
        lines.extend(
            [
                (
                    "    제한 초기화: "
                    f"{_format_datetime(report.requests.window_end, KST)} KST / "
                    f"{_format_datetime(report.requests.window_end, UTC)} UTC"
                ),
                (
                    "    응답 확인 시각: "
                    f"{_format_datetime(request_completion_time(record), KST)} KST"
                ),
            ]
        )

    if "mixed" in records or "unknown" in records:
        lines.append(
            "  ℹ️ 혼합·종목 불명 응답의 잔여량은 특정 종목의 공식 값으로 "
            "합치지 않습니다."
        )


def _render_exception_status(lines: list[str], report: AutoWatchStatusReport) -> None:
    counts = Counter(item.record.stop_time_status for item in report.exceptions)
    lines.extend(
        [
            "",
            f"[{report.target_date_kst.isoformat()} KST Auto-watch 예외]",
            f"  • 전체 예외: {len(report.exceptions)}개",
        ]
    )
    for time_status, count in sorted(
        counts.items(),
        key=lambda item: (item[0] is None, item[0] if item[0] is not None else 0),
    ):
        lines.append(
            "  • time_status="
            f"{_format_time_status(time_status)} {_time_status_label(time_status)}: "
            f"{count}개"
        )
    if not report.exceptions:
        lines.append("  • 저장된 예외가 없습니다.")
        return

    displayed = (
        report.exceptions
        if report.show_all_exceptions
        else report.exceptions[: report.recent_exception_limit]
    )
    lines.extend(
        [
            "",
            f"[최근 예외 — 전체 {len(report.exceptions)}개 중 {len(displayed)}개 표시]",
        ]
    )
    for item in displayed:
        record = item.record
        lines.extend(
            [
                (
                    f"  • 경기 ID {record.event_id} / "
                    f"time_status={_format_time_status(record.stop_time_status)} "
                    f"{_time_status_label(record.stop_time_status)}"
                ),
                f"    중단 시각: {_format_datetime(record.stopped_at, KST)} KST",
                f"    파일: {item.file_path}",
            ]
        )


def _render_failures(lines: list[str], failures: list[StatusReadFailure]) -> None:
    if not failures:
        return
    lines.extend(
        [
            "",
            f"[읽기 경고 — {len(failures)}개]",
            "  ⚠️ 일부 파일을 읽지 못했지만 나머지 자료로 상태를 표시했습니다.",
        ]
    )
    for failure in failures:
        lines.extend(
            [
                f"  • {failure.area}: {failure.file_path}",
                f"    원인: {failure.error_message}",
            ]
        )


def _load_optional_component[T](
    *,
    area: str,
    file_path: Path,
    loader: Callable[[], T | None],
    failures: list[StatusReadFailure],
    missing_is_failure: bool,
) -> T | None:
    if not file_path.exists() and not missing_is_failure:
        return None
    try:
        return loader()
    except (OSError, ValueError, ValidationError) as error:
        failures.append(
            StatusReadFailure(
                area=area,
                file_path=file_path,
                error_message=str(error),
            )
        )
        return None


def sport_request_counts(records: list[ApiRequestRecord]) -> dict[Sport, int]:
    counts = Counter(record.request_category for record in records)
    shared = counts["mixed"] + counts["unknown"]
    return {
        "football": counts["football_only"] + shared,
        "baseball": counts["baseball_only"] + shared,
    }


def load_request_records(
    *,
    windows: tuple[tuple[datetime, datetime], ...],
    failures: list[StatusReadFailure],
    request_base_directory: Path = BETS_API_REQUEST_LOG_DIRECTORY,
    legacy_base_directory: Path = EVENT_VIEW_REQUEST_LOG_DIRECTORY,
) -> list[ApiRequestRecord]:
    common_paths = _find_request_paths(
        base_directory=request_base_directory, windows=windows, failures=failures
    )
    legacy_paths = _find_request_paths(
        base_directory=legacy_base_directory, windows=windows, failures=failures
    )
    return [
        *_load_bets_api_request_records(common_paths, failures=failures),
        *_load_legacy_event_view_request_records(legacy_paths, failures=failures),
    ]


def load_exceptions_for_window(
    *,
    start: datetime,
    end: datetime,
    failures: list[StatusReadFailure],
    base_directory: Path = AUTO_WATCH_EXCEPTION_DIRECTORY,
) -> list[StoredAutoWatchException]:
    paths = _find_exception_paths(
        base_directory=base_directory, start=start, end=end, failures=failures
    )
    return sorted(
        (
            item
            for item in _load_exceptions(paths, failures=failures)
            if start <= item.record.stopped_at < end
        ),
        key=lambda item: item.record.stopped_at,
        reverse=True,
    )


def _list_record_paths(
    directory: Path,
    failures: list[StatusReadFailure],
    *,
    pattern: str = "*.json",
) -> list[Path]:
    try:
        return sorted(path for path in directory.iterdir() if path.match(pattern))
    except FileNotFoundError:
        return []
    except OSError as error:
        failures.append(StatusReadFailure("기록 디렉터리", directory, str(error)))
        return []


def _find_request_paths(
    *,
    base_directory: Path,
    windows: tuple[tuple[datetime, datetime], ...],
    failures: list[StatusReadFailure],
) -> list[Path]:
    target_dates = {
        target_date
        for start, end in windows
        for target_date in _utc_dates_for_window(start, end)
    }
    return [
        path
        for target_date in sorted(target_dates)
        for path in _list_record_paths(
            base_directory / target_date.isoformat(), failures
        )
    ]


def _load_bets_api_request_records(
    file_paths: list[Path],
    *,
    failures: list[StatusReadFailure],
) -> list[BetsApiRequestRecord]:
    records: list[BetsApiRequestRecord] = []
    for file_path in file_paths:
        try:
            records.append(
                BetsApiRequestRecord.model_validate_json(
                    file_path.read_text(encoding="utf-8")
                )
            )
        except (OSError, ValueError, ValidationError) as error:
            failures.append(
                StatusReadFailure(
                    area="BETS API 요청 기록",
                    file_path=file_path,
                    error_message=str(error),
                )
            )
    return records


def _load_legacy_event_view_request_records(
    file_paths: list[Path],
    *,
    failures: list[StatusReadFailure],
) -> list[EventViewApiRequestRecord]:
    records: list[EventViewApiRequestRecord] = []
    for file_path in file_paths:
        try:
            records.append(
                EventViewApiRequestRecord.model_validate_json(
                    file_path.read_text(encoding="utf-8")
                )
            )
        except (OSError, ValueError, ValidationError) as error:
            failures.append(
                StatusReadFailure(
                    area="기존 Event View 요청 기록",
                    file_path=file_path,
                    error_message=str(error),
                )
            )
    return records


def _find_exception_paths(
    *,
    base_directory: Path,
    start: datetime,
    end: datetime,
    failures: list[StatusReadFailure],
) -> list[Path]:
    return [
        path
        for directory in _list_record_paths(
            base_directory, failures, pattern="time-status-*"
        )
        for target_date in _utc_dates_for_window(start, end)
        for path in _list_record_paths(directory / target_date.isoformat(), failures)
    ]


def _load_exceptions(
    file_paths: list[Path],
    *,
    failures: list[StatusReadFailure],
) -> list[StoredAutoWatchException]:
    records: list[StoredAutoWatchException] = []
    for file_path in file_paths:
        try:
            record = AutoWatchExceptionRecord.model_validate_json(
                file_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ValidationError) as error:
            failures.append(
                StatusReadFailure(
                    area="Auto-watch 예외 기록",
                    file_path=file_path,
                    error_message=str(error),
                )
            )
            continue
        records.append(StoredAutoWatchException(record=record, file_path=file_path))
    return records


def kst_day_utc_window(target_date: date) -> tuple[datetime, datetime]:
    start_kst = datetime.combine(target_date, time.min, tzinfo=KST)
    end_kst = start_kst + timedelta(days=1)
    return start_kst.astimezone(UTC), end_kst.astimezone(UTC)


def current_hour_window(now: datetime) -> tuple[datetime, datetime]:
    normalized_now = _as_utc(now)
    window_start = normalized_now.replace(minute=0, second=0, microsecond=0)
    return window_start, window_start + timedelta(hours=1)


def latest_valid_rate_limit_records(
    records: list[ApiRequestRecord],
    *,
    window_end: datetime,
) -> dict[RequestCategory, ApiRequestRecord]:
    latest_by_category: dict[RequestCategory, ApiRequestRecord] = {}
    for record in records:
        rate_limit = record.rate_limit
        if rate_limit is None or rate_limit.reset_at != window_end:
            continue
        previous = latest_by_category.get(record.request_category)
        if previous is None or request_completion_time(
            record
        ) > request_completion_time(previous):
            latest_by_category[record.request_category] = record
    return latest_by_category


def request_completion_time(record: ApiRequestRecord) -> datetime:
    return record.completed_at or record.requested_at


def _utc_dates_for_window(start: datetime, end: datetime) -> tuple[date, ...]:
    normalized_start = _as_utc(start)
    normalized_end = _as_utc(end)
    inclusive_end = normalized_end - timedelta(microseconds=1)
    day_count = (inclusive_end.date() - normalized_start.date()).days
    return tuple(
        normalized_start.date() + timedelta(days=offset)
        for offset in range(day_count + 1)
    )


def _format_limit_line(
    *,
    label: str,
    count: int,
    limit: int,
    warning_percent: int,
    danger_percent: int,
) -> str:
    percent = count / limit * 100
    if percent >= 100:
        marker = "❌"
    elif percent >= danger_percent:
        marker = "🚨"
    elif percent >= warning_percent:
        marker = "⚠️"
    else:
        marker = "•"
    return f"  {marker} {label}: {count:,} / {limit:,}회 ({percent:.1f}%)"


def _format_datetime(value: datetime, timezone: tzinfo) -> str:
    return value.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")


def _format_duration(total_seconds: int) -> str:
    total_seconds = max(0, total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}시간")
    if minutes:
        parts.append(f"{minutes}분")
    if not parts or seconds:
        parts.append(f"{seconds}초")
    return " ".join(parts)


def _format_time_status(time_status: int | None) -> str:
    return str(time_status) if time_status is not None else "unknown"


def _mode_label(mode: AutoWatchCollectionMode) -> str:
    return {
        "inplay": "경기 중",
        "ended": "정상 종료 후 추가 수집 중",
        "waiting_to_start": "경기 시작 대기 중",
        "temporarily_stopped": "일시 중단 상태 관찰 중",
        "closing": "종료성 상태 추가 수집 중",
        "unknown": "알 수 없는 상태 관찰 중",
    }[mode]


def _time_status_label(time_status: int | None) -> str:
    return {
        None: "알 수 없음",
        0: "시작 전",
        1: "경기 중",
        2: "시간 미정",
        3: "종료",
        4: "연기",
        5: "취소",
        6: "부전승",
        7: "경기 중단",
        8: "경기 포기",
        9: "기권",
        10: "일시 정지",
        11: "협회 결정",
        12: "실격",
        99: "삭제",
    }.get(time_status, "문서에 없는 상태")


def _request_category_label(category: RequestCategory) -> str:
    return {
        "football_only": "축구 전용",
        "baseball_only": "야구 전용",
        "mixed": "축구·야구 혼합",
        "unknown": "종목 분류 불가",
    }[category]


def _endpoint_label(endpoint: str) -> str:
    return {
        "/v1/event/view": "Event View",
        "/v3/events/upcoming": "Upcoming",
        "/v2/event/odds": "Event Odds",
    }.get(endpoint, endpoint)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Auto-watch 상태 확인 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)
