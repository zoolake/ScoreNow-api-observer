from datetime import UTC, date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from scorenow_api_observer.upcoming.auto_discovery import (
    build_auto_watch_discovery_plan,
    find_fatal_http_status_code,
)
from scorenow_api_observer.upcoming.discovery import UpcomingDiscoveryResult
from scorenow_api_observer.upcoming.targets import UpcomingTarget


def test_plan_selects_enabled_leagues_for_utc_today_and_tomorrow() -> None:
    now = datetime(2026, 11, 18, 23, 50, tzinfo=UTC)
    enabled = UpcomingTarget("16", "baseball", "349", "kbo", True)
    disabled = UpcomingTarget("16", "baseball", "225", "mlb", False)

    plan = build_auto_watch_discovery_plan(
        now=now,
        configured_targets=[disabled, enabled],
    )

    assert plan.planned_at == now
    assert plan.target_dates == (date(2026, 11, 18), date(2026, 11, 19))
    assert plan.targets == (enabled,)
    assert plan.expected_request_count == 2


def test_plan_converts_aware_time_to_utc_before_selecting_dates() -> None:
    kst = timezone(timedelta(hours=9))

    plan = build_auto_watch_discovery_plan(
        now=datetime(2026, 11, 19, 0, 30, tzinfo=kst),
        configured_targets=[],
    )

    assert plan.planned_at == datetime(2026, 11, 18, 15, 30, tzinfo=UTC)
    assert plan.target_dates == (date(2026, 11, 18), date(2026, 11, 19))
    assert plan.expected_request_count == 0


def test_plan_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="시간대 정보"):
        build_auto_watch_discovery_plan(
            now=datetime(2026, 11, 18),  # noqa: DTZ001
            configured_targets=[],
        )


@pytest.mark.parametrize("status_code", [401, 402, 403, 429])
def test_find_fatal_status_uses_captured_http_response(status_code: int) -> None:
    result = cast(
        UpcomingDiscoveryResult,
        SimpleNamespace(
            captures=[SimpleNamespace(response=httpx.Response(status_code))]
        ),
    )

    assert find_fatal_http_status_code(result) == status_code


def test_find_fatal_status_ignores_retryable_server_error() -> None:
    result = cast(
        UpcomingDiscoveryResult,
        SimpleNamespace(captures=[SimpleNamespace(response=httpx.Response(502))]),
    )

    assert find_fatal_http_status_code(result) is None
