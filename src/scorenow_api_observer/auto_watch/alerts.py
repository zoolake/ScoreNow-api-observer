from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scorenow_api_observer.auto_watch.exceptions import AutoWatchExceptionRecord
from scorenow_api_observer.auto_watch.match_alerts import MatchAlerts
from scorenow_api_observer.auto_watch.models import AutoWatchActiveEvent
from scorenow_api_observer.auto_watch.status import KST
from scorenow_api_observer.bets_api_client import EVENT_VIEW_ENDPOINT
from scorenow_api_observer.discord_alert_state import DiscordAlertState
from scorenow_api_observer.event_view.models import CaptureMetadata
from scorenow_api_observer.event_view.storage import (
    find_event_observation_paths_for_event,
    load_capture_metadata,
    load_event_observation,
)

NON_RETRYABLE_AUTO_WATCH_STATUS_CODES = frozenset({401, 402, 403, 429})
CONSECUTIVE_FAILURE_CYCLES = 3
CONSECUTIVE_MISSING_CYCLES = 3
MISSING_EVENTS_PER_RESPONSE = 2
PROCESS_INTERRUPTION_KEY = "auto-watch:interruption"


def alert_time(when: datetime) -> str:
    return f"{when.astimezone(KST):%Y-%m-%d %H:%M:%S} KST"


@dataclass
class MissingEvent:
    last_success_at: datetime | None
    last_missing_cycle: int = 0
    consecutive_cycles: int = 0
    notified: bool = False


class AutoWatchAlerts:
    def __init__(self, delivery: DiscordAlertState, *, started_at: datetime):
        self.delivery = delivery
        self.matches = MatchAlerts(delivery)
        self.started_at = started_at
        self._failure_cycles = 0
        self._missing: dict[str, MissingEvent] = {}
        self._last_success: dict[str, datetime] = {}

    def stopped(self, reason: str, *, now: datetime) -> None:
        self.delivery.notify(
            PROCESS_INTERRUPTION_KEY,
            "❌ Auto-watch 수집 중단",
            f"- 발생 시각 {alert_time(now)}\n- 중단 사유 {reason}",
            episode=self.started_at.isoformat(),
        )

    def finish_cycle(
        self,
        *,
        now: datetime,
        transient_failure: str | None,
        normal_collection: bool,
        active_event_ids: set[str],
    ) -> None:
        self.matches.keep_active(active_event_ids)
        self._missing = {
            event_id: state
            for event_id, state in self._missing.items()
            if event_id in active_event_ids
        }
        self._last_success = {
            event_id: when
            for event_id, when in self._last_success.items()
            if event_id in active_event_ids
        }
        if transient_failure is not None:
            self._failure_cycles += 1
            if self._failure_cycles >= CONSECUTIVE_FAILURE_CYCLES:
                self.delivery.notify(
                    "auto-watch:event-view-failures",
                    "⚠️ Event View 수집 반복 실패",
                    f"- 확인 시각 {alert_time(now)}\n- 엔드포인트 {EVENT_VIEW_ENDPOINT}"
                    f"\n- 연속 {self._failure_cycles}주기 실패 · {transient_failure}",
                )
            return

        self._failure_cycles = 0
        if normal_collection:
            self.delivery.notify(
                "auto-watch:event-view-failures",
                "ℹ️ Event View 수집 복구",
                f"- 정상 수집 확인 {alert_time(now)}\n- 엔드포인트 {EVENT_VIEW_ENDPOINT}",
                episode=None,
            )
            self.delivery.notify(
                PROCESS_INTERRUPTION_KEY,
                "ℹ️ Auto-watch 수집 복구",
                f"- 정상 수집 확인 {alert_time(now)}",
                episode=None,
            )

    def response(
        self,
        metadata: CaptureMetadata,
        *,
        cycle: int,
        events: dict[str, AutoWatchActiveEvent],
    ) -> None:
        if not 200 <= metadata.http_status_code < 300:
            return
        for event_id in set(metadata.returned_event_ids) & events.keys():
            self._last_success[event_id] = metadata.captured_at
            self._missing.pop(event_id, None)

        missing_ids = [
            issue.event_id
            for issue in metadata.response_issues
            if issue.code == "missing_requested_event"
            and issue.event_id in events
            and issue.event_id is not None
        ]
        to_notify: list[tuple[str, MissingEvent]] = []
        for event_id in missing_ids:
            state = self._missing.get(event_id)
            if state is None:
                last_success = self._last_success.get(event_id)
                if last_success is None:
                    last_success = _read_last_success(events[event_id])
                state = self._missing[event_id] = MissingEvent(last_success)
            if state.last_missing_cycle != cycle:
                state.consecutive_cycles = (
                    state.consecutive_cycles + 1
                    if state.last_missing_cycle == cycle - 1
                    else 1
                )
                state.last_missing_cycle = cycle
            if not state.notified and (
                len(missing_ids) >= MISSING_EVENTS_PER_RESPONSE
                or state.consecutive_cycles >= CONSECUTIVE_MISSING_CYCLES
            ):
                to_notify.append((event_id, state))
        if not to_notify:
            return

        lines = [f"- 확인 시각 {alert_time(metadata.captured_at)}"]
        details = (
            missing_ids
            if len(missing_ids) >= MISSING_EVENTS_PER_RESPONSE
            else [event_id for event_id, _ in to_notify]
        )
        for event_id in details:
            state = self._missing[event_id]
            last_success = (
                alert_time(state.last_success_at)
                if state.last_success_at
                else "기록 없음"
            )
            lines.append(f"- 경기 {event_id} · 마지막 정상 응답 {last_success}")
        if (
            self.delivery.sender("⚠️ Event View 응답에서 경기 누락", "\n".join(lines))
            is not None
        ):
            for _, state in to_notify:
                state.notified = True

    def exception_saved(self, record: AutoWatchExceptionRecord) -> None:
        status = record.stop_time_status
        self.delivery.notify(
            f"exception:{record.event_id}:{record.stopped_at.isoformat()}",
            "⚠️ 경기 수집 예외 종료",
            f"- 경기 {record.event_id}\n- 종료 시각 {alert_time(record.stopped_at)}\n"
            f"- 관찰 상한에 도달 · time_status={status if status is not None else '미확인'}",
        )


def _read_last_success(event: AutoWatchActiveEvent) -> datetime | None:
    path = event.last_capture_metadata_path
    if path is not None:
        try:
            capture = load_capture_metadata(Path(path))
            if (
                200 <= capture.http_status_code < 300
                and event.event_id in capture.returned_event_ids
            ):
                return capture.captured_at
        except OSError, ValueError, KeyError, TypeError:
            pass
    try:
        paths = find_event_observation_paths_for_event(event.event_id)
    except OSError, ValueError:
        return None
    for observation_path in reversed(paths):
        try:
            observation = load_event_observation(observation_path)
            capture = load_capture_metadata(
                Path(observation.capture_metadata_file_path)
            )
        except OSError, ValueError, KeyError, TypeError:
            continue
        if (
            200 <= capture.http_status_code < 300
            and event.event_id in capture.returned_event_ids
        ):
            return capture.captured_at
    return None
