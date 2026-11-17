from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from scorenow_api_observer.upcoming.discovery import (
    FATAL_HTTP_STATUS_CODES,
    UpcomingDiscoveryResult,
)
from scorenow_api_observer.upcoming.targets import (
    UpcomingTarget,
    select_auto_watch_targets,
)


@dataclass(frozen=True)
class AutoWatchDiscoveryPlan:
    """한 번의 자동 Discovery 실행에서 조회할 UTC 날짜와 활성 리그입니다."""

    planned_at: datetime
    target_dates: tuple[date, date]
    targets: tuple[UpcomingTarget, ...]

    @property
    def expected_request_count(self) -> int:
        return len(self.target_dates) * len(self.targets)


def build_auto_watch_discovery_plan(
    *,
    now: datetime,
    configured_targets: list[UpcomingTarget],
) -> AutoWatchDiscoveryPlan:
    """실행 시각을 기준으로 UTC 오늘·내일의 활성 리그 조회 계획을 만듭니다."""

    normalized_now = _as_utc(now)
    today = normalized_now.date()
    return AutoWatchDiscoveryPlan(
        planned_at=normalized_now,
        target_dates=(today, today + timedelta(days=1)),
        targets=tuple(select_auto_watch_targets(configured_targets)),
    )


def find_fatal_http_status_code(result: UpcomingDiscoveryResult) -> int | None:
    """Discovery 결과에서 남은 자동 호출을 중단해야 하는 HTTP 상태를 찾습니다."""

    for capture in result.captures:
        status_code = capture.response.status_code
        if status_code in FATAL_HTTP_STATUS_CODES:
            return status_code
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("자동 Discovery 기준 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)
