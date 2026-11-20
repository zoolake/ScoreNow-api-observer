from datetime import UTC, datetime, timedelta
from pathlib import Path

from scorenow_api_observer.auto_watch.alerts import AutoWatchAlerts
from scorenow_api_observer.auto_watch.heartbeat import (
    finish_auto_watch_heartbeat,
    new_auto_watch_heartbeat,
    save_auto_watch_heartbeat,
    touch_auto_watch_heartbeat,
)
from scorenow_api_observer.auto_watch.operations_check import check_operations_alerts
from scorenow_api_observer.bets_api_request_log import (
    EventViewRequestDetails,
    RateLimitSnapshot,
    RequestedEvent,
    finish_bets_api_request,
    start_bets_api_request,
)
from scorenow_api_observer.discord_alert_state import DiscordAlertState

START = datetime(2026, 11, 19, 4, tzinfo=UTC)


def test_check_stale_heartbeat_and_deduplicate_collector_stop(tmp_path):
    messages = []
    heartbeat_path = tmp_path / "heartbeat.json"

    def send(title, description, **kwargs):
        messages.append((title, description))
        return "123"

    def check(now):
        return check_operations_alerts(
            now=now,
            delivery=DiscordAlertState(send, tmp_path / "alerts"),
            heartbeat_path=heartbeat_path,
            request_base_directory=tmp_path / "requests",
            legacy_base_directory=tmp_path / "legacy",
        )

    heartbeat = new_auto_watch_heartbeat(
        now=START, interval_seconds=120, process_id=101
    )
    save_auto_watch_heartbeat(heartbeat, heartbeat_path)
    assert check(START + timedelta(seconds=240)).sent_count == 0
    assert check(START + timedelta(seconds=241)).sent_count == 1
    assert check(START + timedelta(seconds=300)).sent_count == 0
    assert "마지막 처리 시각 2026-11-19 13:00:00 KST" in messages[0][1]
    resumed_at = START + timedelta(seconds=301)
    touch_auto_watch_heartbeat(heartbeat, now=resumed_at)
    save_auto_watch_heartbeat(heartbeat, heartbeat_path)
    assert check(resumed_at).sent_count == 1
    assert "처리 재개" in messages[-1][0]
    assert check(resumed_at).sent_count == 0

    alerts = AutoWatchAlerts(
        DiscordAlertState(send, tmp_path / "alerts"), started_at=START
    )
    alerts.stopped("/v1/event/view HTTP 429", now=resumed_at)
    assert check(resumed_at + timedelta(seconds=300)).sent_count == 0
    finish_auto_watch_heartbeat(
        heartbeat,
        now=resumed_at,
        failed=True,
        failure_message="HTTP 429",
    )
    save_auto_watch_heartbeat(heartbeat, heartbeat_path)
    assert check(resumed_at + timedelta(seconds=360)).sent_count == 0
    assert len(messages) == 3

    restarted = new_auto_watch_heartbeat(
        now=resumed_at, interval_seconds=120, process_id=102
    )
    finish_auto_watch_heartbeat(
        restarted,
        now=resumed_at,
        failed=True,
        failure_message="/v1/event/view HTTP 429",
    )
    save_auto_watch_heartbeat(restarted, heartbeat_path)
    assert check(resumed_at).sent_count == 1
    assert "/v1/event/view HTTP 429" in messages[-1][1]
    assert check(resumed_at).sent_count == 0


def test_check_quota_thresholds_and_rate_limit_reset_each_hour(tmp_path):
    config = tmp_path / "auto_watch.yaml"
    config.write_text(
        Path("config/auto_watch.yaml").read_text().replace("3600", "10"),
        encoding="utf-8",
    )
    requests = tmp_path / "requests"
    request = EventViewRequestDetails(
        requested_events=[RequestedEvent(event_id="A", sport_code="football")]
    )
    messages = []

    def send(title, description, **kwargs):
        messages.append((title, description))
        return "123"

    def record(when, *, remaining=None, reset=None):
        handle = start_bets_api_request(
            request=request,
            requested_at=when,
            base_directory=requests,
        )
        if remaining is not None:
            finish_bets_api_request(
                handle=handle,
                completed_at=when,
                outcome="completed",
                http_status_code=200,
                rate_limit=RateLimitSnapshot(remaining=remaining, reset_at=reset),
            )

    def check(at):
        return check_operations_alerts(
            now=at,
            config_path=config,
            delivery=DiscordAlertState(send, tmp_path / "alerts"),
            heartbeat_path=tmp_path / "heartbeat.json",
            request_base_directory=requests,
            legacy_base_directory=tmp_path / "legacy",
        )

    end = START + timedelta(hours=1)
    now = START + timedelta(minutes=5)
    for _ in range(6):
        record(START)
    record(START, remaining=2, reset=end)
    assert check(now).sent_count == 0
    record(START + timedelta(minutes=1), remaining=123, reset=end + timedelta(hours=1))
    assert check(now).sent_count == 1
    assert "주의" in messages[-1][0]
    assert "8/10회 (80.0%)" in messages[-1][1]
    assert "API 남은 요청 2회" in messages[-1][1]
    assert check(now).sent_count == 0
    record(START + timedelta(minutes=2), remaining=0, reset=end)
    assert check(now).sent_count == 1
    assert "위험" in messages[-1][0]
    assert "9/10회 (90.0%)" in messages[-1][1]
    assert "API 남은 요청 0회" in messages[-1][1]
    assert check(now).sent_count == 0

    assert check(end).sent_count == 0
    for _ in range(9):
        record(end)
    assert check(end).sent_count == 2
    assert "14:00:00 KST" in messages[-1][1]
    assert "남은 요청" not in messages[-1][1]
    assert check(end).sent_count == 0
