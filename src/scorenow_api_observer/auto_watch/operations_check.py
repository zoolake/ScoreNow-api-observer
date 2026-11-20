from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scorenow_api_observer.auto_watch.alerts import (
    NON_RETRYABLE_AUTO_WATCH_STATUS_CODES,
    PROCESS_INTERRUPTION_KEY,
    alert_time,
)
from scorenow_api_observer.auto_watch.config import (
    AUTO_WATCH_CONFIG_PATH,
    AutoWatchRequestLimits,
    load_auto_watch_config,
)
from scorenow_api_observer.auto_watch.heartbeat import (
    AUTO_WATCH_HEARTBEAT_PATH,
    AutoWatchHeartbeat,
    heartbeat_stale_after_seconds,
    load_auto_watch_heartbeat,
)
from scorenow_api_observer.auto_watch.status import (
    ApiRequestRecord,
    Sport,
    StatusReadFailure,
    current_hour_window,
    latest_valid_rate_limit_records,
    load_request_records,
    request_completion_time,
    sport_request_counts,
)
from scorenow_api_observer.bets_api_client import EVENT_VIEW_ENDPOINT
from scorenow_api_observer.bets_api_request_log import (
    BETS_API_REQUEST_LOG_DIRECTORY,
    RequestCategory,
)
from scorenow_api_observer.discord_alert_state import DiscordAlertState
from scorenow_api_observer.event_view.request_log import (
    EVENT_VIEW_REQUEST_LOG_DIRECTORY,
)


@dataclass(frozen=True)
class OperationsCheck:
    sent_count: int
    failures: list[StatusReadFailure]


def check_operations_alerts(
    *,
    now: datetime,
    delivery: DiscordAlertState,
    heartbeat_path: Path = AUTO_WATCH_HEARTBEAT_PATH,
    config_path: Path = AUTO_WATCH_CONFIG_PATH,
    request_base_directory: Path = BETS_API_REQUEST_LOG_DIRECTORY,
    legacy_base_directory: Path = EVENT_VIEW_REQUEST_LOG_DIRECTORY,
) -> OperationsCheck:
    failures: list[StatusReadFailure] = []
    sent_count = 0
    try:
        heartbeat = load_auto_watch_heartbeat(heartbeat_path)
    except (OSError, ValueError) as error:
        failures.append(StatusReadFailure("실행 상태", heartbeat_path, str(error)))
    else:
        if heartbeat is not None:
            sent_count += _check_heartbeat(heartbeat, now=now, delivery=delivery)

    try:
        limits = load_auto_watch_config(config_path).request_limits
    except (OSError, ValueError) as error:
        failures.append(StatusReadFailure("요청 한도 설정", config_path, str(error)))
    else:
        start, end = current_hour_window(now)
        records = [
            record
            for record in load_request_records(
                windows=((start, end),),
                failures=failures,
                request_base_directory=request_base_directory,
                legacy_base_directory=legacy_base_directory,
            )
            if start <= record.requested_at < end and record.requested_at <= now
        ]
        sent_count += _check_request_limits(
            start=start,
            end=end,
            now=now,
            records=records,
            limits=limits,
            delivery=delivery,
        )
    return OperationsCheck(sent_count, failures)


def _check_heartbeat(
    heartbeat: AutoWatchHeartbeat, *, now: datetime, delivery: DiscordAlertState
) -> bool:
    started = heartbeat.process_started_at.isoformat()
    stale_episode = f"{started}/stale"
    last_cycle = f"- 마지막 처리 시각 {alert_time(heartbeat.last_cycle_at)}"
    if heartbeat.status == "failed":
        stopped_at = heartbeat.stopped_at or heartbeat.last_cycle_at
        description = f"{last_cycle}\n- 오류 종료 시각 {alert_time(stopped_at)}"
        for code in NON_RETRYABLE_AUTO_WATCH_STATUS_CODES:
            reason = f"{EVENT_VIEW_ENDPOINT} HTTP {code}"
            if heartbeat.failure_message == reason:
                description += f"\n- 중단 사유 {reason}"
                break
        return delivery.notify(
            PROCESS_INTERRUPTION_KEY,
            "❌ Auto-watch 수집 중단",
            description,
            episode=started,
            can_replace=lambda previous: (
                previous is None or previous.split("/", 1)[0] <= started
            ),
        )
    if heartbeat.status != "running":
        return False

    age = (now - heartbeat.last_cycle_at).total_seconds()
    if age > heartbeat_stale_after_seconds(heartbeat.interval_seconds):
        return delivery.notify(
            PROCESS_INTERRUPTION_KEY,
            "⚠️ Auto-watch 처리 지연",
            f"{last_cycle}\n- 확인 시각 {alert_time(now)}",
            episode=stale_episode,
            can_replace=lambda previous: (
                previous is None or previous.split("/", 1)[0] < started
            ),
        )
    return delivery.notify(
        PROCESS_INTERRUPTION_KEY,
        "ℹ️ Auto-watch 처리 재개",
        last_cycle,
        episode=None,
        can_replace=lambda previous: previous == stale_episode,
    )


def _check_request_limits(
    *,
    start: datetime,
    end: datetime,
    now: datetime,
    records: list[ApiRequestRecord],
    limits: AutoWatchRequestLimits,
    delivery: DiscordAlertState,
) -> int:
    counts = sport_request_counts(records)
    limit_records = latest_valid_rate_limit_records(
        [
            record
            for record in records
            if record.rate_limit is not None
            and record.rate_limit.remaining is not None
            and request_completion_time(record) <= now
        ],
        window_end=end,
    )
    sports: tuple[tuple[Sport, str, int, RequestCategory], ...] = (
        ("football", "축구", limits.soccer_per_hour, "football_only"),
        ("baseball", "야구", limits.baseball_per_hour, "baseball_only"),
    )
    severities = (
        ("warning", "주의", "⚠️", limits.warning_percent),
        ("danger", "위험", "❌", limits.danger_percent),
    )
    episode = start.isoformat()
    sent = 0
    for sport, label, limit, category in sports:
        count = counts[sport]
        for severity, severity_label, icon, percent in severities:
            if 100 * count < percent * limit:
                continue
            description = (
                f"- 구간 {alert_time(start)} ~ {alert_time(end)}\n"
                f"- 로컬 요청 {count:,}/{limit:,}회 ({100 * count / limit:.1f}%)\n"
                f"- {severity_label} 기준 {percent}%"
            )
            rate_record = limit_records.get(category)
            if (
                rate_record is not None
                and rate_record.rate_limit is not None
                and rate_record.rate_limit.remaining is not None
            ):
                description += (
                    f"\n- API 남은 요청 {rate_record.rate_limit.remaining:,}회"
                )
            elif shared := _shared_remaining(limit_records):
                description += f"\n- {shared}"
            sent += delivery.notify(
                f"quota:{sport}:{severity}",
                f"{icon} {label} API 요청 한도 {severity_label}",
                description,
                episode=episode,
                can_replace=lambda previous: previous is None or previous < episode,
            )
    return sent


def _shared_remaining(records: dict[RequestCategory, ApiRequestRecord]) -> str | None:
    labels: tuple[tuple[RequestCategory, str], ...] = (
        ("mixed", "혼합"),
        ("unknown", "종목 분류 불가"),
    )
    candidates = [
        (record, label)
        for category, label in labels
        if (record := records.get(category)) is not None
    ]
    if not candidates:
        return None
    record, label = max(candidates, key=lambda entry: request_completion_time(entry[0]))
    if record.rate_limit is None or record.rate_limit.remaining is None:
        return None
    return f"API 남은 요청 {record.rate_limit.remaining:,}회 ({label} 응답)"
