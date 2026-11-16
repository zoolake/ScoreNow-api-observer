from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scorenow_api_observer.auto_watch.models import (
    AutoWatchActiveEvent,
    AutoWatchState,
)
from scorenow_api_observer.event_view.watching import (
    EventWatchState,
    find_completed_event_ids,
)
from scorenow_api_observer.upcoming.candidates import UpcomingCandidate

AUTO_WATCH_STATE_PATH = Path("data/state/auto-watch/state.json")


def new_auto_watch_state(*, now: datetime) -> AutoWatchState:
    """활성 이벤트가 없는 최초 상태를 만듭니다."""

    return AutoWatchState(updated_at=_as_utc(now), active_events=[])


def load_auto_watch_state(
    file_path: Path = AUTO_WATCH_STATE_PATH,
) -> AutoWatchState | None:
    """저장된 auto-watch 상태를 읽고, 파일이 없으면 None을 반환합니다."""

    if not file_path.exists():
        return None
    state = AutoWatchState.model_validate_json(file_path.read_text(encoding="utf-8"))
    if state.schema_version in (1, 2):
        state = state.model_copy(update={"schema_version": 3})
    return state


def save_auto_watch_state(
    state: AutoWatchState,
    file_path: Path = AUTO_WATCH_STATE_PATH,
) -> Path:
    """auto-watch 상태를 같은 디렉터리 안에서 원자적으로 교체합니다."""

    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = file_path.with_name(f".{file_path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            state.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(file_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return file_path


def add_auto_watch_candidates(
    *,
    state: AutoWatchState,
    candidates: list[UpcomingCandidate],
    now: datetime,
) -> list[str]:
    """아직 활성화되지 않은 후보를 상태에 추가하고 새 이벤트 ID를 반환합니다."""

    normalized_now = _as_utc(now)
    known_event_ids = {event.event_id for event in state.active_events}
    added_event_ids: list[str] = []

    for candidate in candidates:
        event = candidate.event
        if event.event_id in known_event_ids:
            continue

        state.active_events.append(
            AutoWatchActiveEvent(
                event_id=event.event_id,
                sport_code=event.sport_code,
                league_id=event.league.id,
                league_label=candidate.league_label,
                scheduled_at_utc=event.scheduled_at_utc,
                added_at=normalized_now,
            )
        )
        known_event_ids.add(event.event_id)
        added_event_ids.append(event.event_id)

    if added_event_ids:
        state.active_events.sort(
            key=lambda active_event: (
                active_event.scheduled_at_utc,
                active_event.event_id,
            )
        )
        state.updated_at = normalized_now

    return added_event_ids


def remove_completed_auto_watch_events(
    *,
    state: AutoWatchState,
    now: datetime,
) -> list[str]:
    """종료 감지 후 추가 수집 기간이 지난 이벤트를 활성 목록에서 제거합니다."""

    normalized_now = _as_utc(now)
    completed_event_ids = find_completed_event_ids(
        states=build_event_watch_states(state),
        now=normalized_now,
    )
    if not completed_event_ids:
        return []

    completed_event_id_set = set(completed_event_ids)
    state.active_events = [
        event
        for event in state.active_events
        if event.event_id not in completed_event_id_set
    ]
    state.updated_at = normalized_now
    return completed_event_ids


def mark_auto_watch_stop_decisions(
    *,
    state: AutoWatchState,
    event_ids: list[str],
    stopped_at: datetime,
) -> bool:
    """상한에 도달한 이벤트의 중단 결정 시각을 재시작 가능하게 고정합니다."""

    normalized_stopped_at = _as_utc(stopped_at)
    target_event_ids = set(event_ids)
    changed = False
    for event in state.active_events:
        if event.event_id not in target_event_ids or event.stop_decided_at is not None:
            continue
        event.stop_decided_at = normalized_stopped_at
        changed = True

    if changed:
        state.updated_at = normalized_stopped_at
    return changed


def remove_auto_watch_events(
    *,
    state: AutoWatchState,
    event_ids: list[str],
    now: datetime,
) -> None:
    """처리가 끝난 이벤트를 활성 목록에서 제거합니다."""

    event_id_set = set(event_ids)
    if not event_id_set:
        return
    state.active_events = [
        event for event in state.active_events if event.event_id not in event_id_set
    ]
    state.updated_at = _as_utc(now)


def build_event_watch_states(state: AutoWatchState) -> list[EventWatchState]:
    """저장 모델을 기존 Event View 종료 감지 모델로 변환합니다."""

    return [
        EventWatchState(
            event_id=event.event_id,
            finished_detected_at=event.finished_detected_at,
        )
        for event in state.active_events
    ]


def sync_event_watch_states(
    *,
    state: AutoWatchState,
    watch_states: dict[str, EventWatchState],
    now: datetime,
) -> bool:
    """기존 종료 감지 모델의 변경을 저장 모델로 되돌립니다."""

    changed = False
    for event in state.active_events:
        watch_state = watch_states.get(event.event_id)
        if watch_state is None:
            continue
        if event.finished_detected_at == watch_state.finished_detected_at:
            continue
        event.finished_detected_at = watch_state.finished_detected_at
        changed = True

    if changed:
        state.updated_at = _as_utc(now)
    return changed


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("자동 수집 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)
