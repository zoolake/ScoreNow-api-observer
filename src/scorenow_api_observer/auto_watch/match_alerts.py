from datetime import datetime, timedelta

from scorenow_api_observer.auto_watch.models import AutoWatchActiveEvent
from scorenow_api_observer.auto_watch.status import KST
from scorenow_api_observer.discord_alert_state import DiscordAlertState
from scorenow_api_observer.event_view.watching import normalize_time_status

UNSCHEDULED_STATUS_PERIOD = timedelta(minutes=30)
FOOTBALL_PERIODS = {2: "연장 전반", 3: "연장 후반", 4: "승부차기"}


class MatchAlerts:
    def __init__(self, delivery: DiscordAlertState):
        self.delivery = delivery
        self._last_status: dict[str, int] = {}
        self._unscheduled: dict[str, tuple[datetime, int]] = {}

    def keep_active(self, event_ids: set[str]) -> None:
        self._last_status = {
            event_id: status
            for event_id, status in self._last_status.items()
            if event_id in event_ids
        }
        self._unscheduled = {
            event_id: observation
            for event_id, observation in self._unscheduled.items()
            if event_id in event_ids
        }

    def observe(
        self,
        event: AutoWatchActiveEvent,
        data: dict[str, object],
        *,
        observed_at: datetime,
        cycle: int,
    ) -> None:
        status = normalize_time_status(data.get("time_status"))
        prefix = f"match:{event.event_id}"
        summary = f"- 경기 {event.event_id}\n- 관측 시각 {observed_at.astimezone(KST):%Y-%m-%d %H:%M:%S} KST"

        if status != 2:
            self._unscheduled.pop(event.event_id, None)
        if status is not None:
            self._observe_status(event, status, observed_at, cycle, prefix, summary)

        if event.sport_code == "football":
            period = normalize_time_status(_object_field(data.get("timer"), "md"))
            if period is not None and period in FOOTBALL_PERIODS:
                kind = "penalties" if period == 4 else "extra-time"
                self.delivery.notify(
                    f"{prefix}:{kind}",
                    f"ℹ️ 축구 {FOOTBALL_PERIODS[period]} 최초 관측",
                    f"{summary}\n- timer.md={period}",
                )
        if event.sport_code == "baseball" and status == 1:
            inning = _first_extra_inning(data)
            if inning is not None:
                self.delivery.notify(
                    f"{prefix}:extra-innings",
                    "ℹ️ 야구 연장 이닝 최초 관측",
                    f"{summary}\n- {inning}회 점수 확인",
                )

    def _observe_status(
        self,
        event: AutoWatchActiveEvent,
        status: int,
        observed_at: datetime,
        cycle: int,
        prefix: str,
        summary: str,
    ) -> None:
        previous = self._last_status.get(event.event_id)
        self._last_status[event.event_id] = status
        status_key = f"{prefix}:status"
        if status in (0, 1, 3):
            if previous != status and (previous is None or previous not in (0, 1, 3)):
                self.delivery.clear(status_key)
        elif status == 2:
            start, previous_cycle = self._unscheduled.get(
                event.event_id, (observed_at, cycle)
            )
            if previous not in (None, 2):
                self.delivery.clear(status_key)
            if previous_cycle < cycle - 1:
                start = observed_at
            self._unscheduled[event.event_id] = (start, cycle)
            if (
                observed_at - max(start, event.scheduled_at_utc)
                >= UNSCHEDULED_STATUS_PERIOD
            ):
                self.delivery.notify(
                    status_key,
                    "⚠️ 경기 시간 미정 상태 지속",
                    f"{summary}\n- time_status=2 · 예정 시각 이후 30분 이상",
                    episode="2",
                )
        else:
            self.delivery.notify(
                status_key,
                "⚠️ 특이 경기 상태 관측",
                f"{summary}\n- time_status={status}",
                episode=str(status),
            )

        if status == 1 and (
            previous == 3 or (previous is None and event.last_time_status == 3)
        ):
            ended_at = event.finished_detected_at or observed_at
            self.delivery.notify(
                f"{prefix}:resumed",
                "⚠️ 종료 경기에서 경기 중 상태 관측",
                f"{summary}\n- time_status 3 → 1",
                episode=ended_at.isoformat(),
            )


def _object_field(value: object, key: str) -> object:
    return value.get(key) if isinstance(value, dict) else None


def _first_extra_inning(data: dict[str, object]) -> int | None:
    regular = normalize_time_status(_object_field(data.get("extra"), "numberofperiods"))
    scores = data.get("scores")
    if regular is None or regular < 1 or not isinstance(scores, dict):
        return None
    innings: list[int] = []
    for key, score in scores.items():
        inning = normalize_time_status(key)
        if inning is None or inning <= regular:
            continue
        for side in ("home", "away"):
            points = normalize_time_status(_object_field(score, side))
            if points is not None and points >= 0:
                innings.append(inning)
                break
    return min(innings, default=None)
