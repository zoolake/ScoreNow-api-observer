from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

FINISHED_TIME_STATUS = 3
POST_FINISH_COLLECTION_PERIOD = timedelta(minutes=15)


@dataclass
class EventWatchState:
    """반복 수집 중인 이벤트 하나의 종료 감지 상태입니다.

    Attributes:
        event_id: 반복 수집 대상으로 관리하는 외부 API 이벤트 ID입니다.
        finished_detected_at: ``time_status=3``을 최초로 관측한 UTC 시각입니다.
            종료가 취소되었거나 아직 감지되지 않았다면 None입니다.
    """

    event_id: str
    finished_detected_at: datetime | None = None


@dataclass(frozen=True)
class EventWatchTransition:
    """응답의 time_status로 인해 발생한 이벤트 수집 상태 변화입니다."""

    event_id: str
    kind: Literal["finish_detected", "finish_cancelled"]
    time_status: int


def apply_event_time_status(
    *,
    state: EventWatchState,
    time_status: object,
    observed_at: datetime,
) -> EventWatchTransition | None:
    """해석 가능한 time_status를 이벤트 상태에 반영하고 상태 변화를 반환합니다."""

    normalized_time_status = normalize_time_status(time_status)
    if normalized_time_status is None:
        return None

    if normalized_time_status == FINISHED_TIME_STATUS:
        if state.finished_detected_at is not None:
            return None

        state.finished_detected_at = observed_at
        return EventWatchTransition(
            event_id=state.event_id,
            kind="finish_detected",
            time_status=normalized_time_status,
        )

    if state.finished_detected_at is None:
        return None

    state.finished_detected_at = None
    return EventWatchTransition(
        event_id=state.event_id,
        kind="finish_cancelled",
        time_status=normalized_time_status,
    )


def normalize_time_status(value: object) -> int | None:
    """정수 또는 정수 문자열인 time_status를 정수로 정규화합니다."""

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if not isinstance(value, str):
        return None

    stripped_value = value.strip()
    if not stripped_value:
        return None

    try:
        return int(stripped_value)
    except ValueError:
        return None


def find_completed_event_ids(
    *,
    states: list[EventWatchState],
    now: datetime,
    post_finish_collection_period: timedelta = POST_FINISH_COLLECTION_PERIOD,
) -> list[str]:
    """종료 감지 후 추가 수집 기간이 지난 이벤트 ID를 반환합니다."""

    completed_event_ids: list[str] = []

    for state in states:
        if state.finished_detected_at is None:
            continue

        collection_deadline = state.finished_detected_at + post_finish_collection_period
        if now >= collection_deadline:
            completed_event_ids.append(state.event_id)

    return completed_event_ids
