from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from scorenow_api_observer.auto_watch.config import (
    AutoWatchCollectionMode,
    AutoWatchConfig,
)
from scorenow_api_observer.auto_watch.models import (
    AutoWatchActiveEvent,
    AutoWatchState,
)
from scorenow_api_observer.event_view.watching import normalize_time_status


@dataclass(frozen=True)
class AutoWatchStatusUpdate:
    """한 응답의 time_status를 활성 이벤트에 반영한 결과입니다."""

    event_id: str
    time_status: int | None
    previous_mode: AutoWatchCollectionMode | None
    current_mode: AutoWatchCollectionMode
    deadline: datetime | None
    changed: bool

    @property
    def mode_changed(self) -> bool:
        return self.previous_mode != self.current_mode


@dataclass(frozen=True)
class AutoWatchStopCandidate:
    """현재 주기에서 수집을 중단해야 하는 이벤트입니다."""

    event_id: str
    stopped_at: datetime
    stop_time_status: int | None
    requires_exception_record: bool


def apply_auto_watch_time_status(
    *,
    event: AutoWatchActiveEvent,
    time_status: object,
    observed_at: datetime,
    capture_metadata_file_path: str,
    config: AutoWatchConfig,
) -> AutoWatchStatusUpdate:
    """관측 상태를 재시작 가능한 Auto-watch 이벤트 상태에 반영합니다."""

    normalized_observed_at = _as_utc(observed_at)
    normalized_time_status = normalize_time_status(time_status)
    previous_mode = _current_mode(event, config)
    before = (
        event.finished_detected_at,
        event.last_time_status,
        event.status_policy_group,
        event.status_policy_started_at,
        event.last_capture_metadata_path,
    )

    current_mode = config.classify_time_status(normalized_time_status)
    event.last_time_status = normalized_time_status
    event.last_capture_metadata_path = capture_metadata_file_path

    if current_mode == "inplay":
        event.finished_detected_at = None
        event.status_policy_group = None
        event.status_policy_started_at = None
    elif current_mode == "ended":
        if event.finished_detected_at is None:
            event.finished_detected_at = normalized_observed_at
        event.status_policy_group = None
        event.status_policy_started_at = None
    else:
        event.finished_detected_at = None
        if event.status_policy_group != current_mode:
            event.status_policy_group = current_mode
            event.status_policy_started_at = normalized_observed_at

    after = (
        event.finished_detected_at,
        event.last_time_status,
        event.status_policy_group,
        event.status_policy_started_at,
        event.last_capture_metadata_path,
    )
    return AutoWatchStatusUpdate(
        event_id=event.event_id,
        time_status=normalized_time_status,
        previous_mode=previous_mode,
        current_mode=current_mode,
        deadline=auto_watch_collection_deadline(event=event, config=config),
        changed=before != after,
    )


def auto_watch_collection_deadline(
    *,
    event: AutoWatchActiveEvent,
    config: AutoWatchConfig,
) -> datetime | None:
    """현재 상태가 계속될 때 해당 이벤트의 수집 종료 시각을 반환합니다."""

    if event.finished_detected_at is not None:
        return event.finished_detected_at + timedelta(
            minutes=config.ended.followup_minutes
        )

    group = event.status_policy_group
    started_at = event.status_policy_started_at
    if group is None or started_at is None:
        return None
    if group == "waiting_to_start":
        return event.scheduled_at_utc + timedelta(
            minutes=(
                config.status_policies.waiting_to_start.max_minutes_after_scheduled_at
            )
        )
    if group == "temporarily_stopped":
        return started_at + timedelta(
            minutes=(config.status_policies.temporarily_stopped.max_continuous_minutes)
        )
    if group == "closing":
        return started_at + timedelta(
            minutes=config.status_policies.closing.followup_minutes
        )
    return started_at + timedelta(
        minutes=config.status_policies.unknown.max_continuous_minutes
    )


def find_due_auto_watch_events(
    *,
    state: AutoWatchState,
    now: datetime,
    config: AutoWatchConfig,
) -> list[AutoWatchStopCandidate]:
    """정상 종료 또는 상태별 관찰 상한에 도달한 이벤트를 반환합니다."""

    normalized_now = _as_utc(now)
    due_events: list[AutoWatchStopCandidate] = []
    for event in state.active_events:
        deadline = auto_watch_collection_deadline(event=event, config=config)
        if event.stop_decided_at is None and (
            deadline is None or normalized_now < deadline
        ):
            continue

        due_events.append(
            AutoWatchStopCandidate(
                event_id=event.event_id,
                stopped_at=event.stop_decided_at or normalized_now,
                stop_time_status=event.last_time_status,
                requires_exception_record=event.finished_detected_at is None,
            )
        )
    return due_events


def _current_mode(
    event: AutoWatchActiveEvent,
    config: AutoWatchConfig,
) -> AutoWatchCollectionMode | None:
    if event.finished_detected_at is not None:
        return "ended"
    if event.status_policy_group is not None:
        return event.status_policy_group
    if event.last_time_status is None:
        return None
    return config.classify_time_status(event.last_time_status)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Auto-watch 정책 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)
