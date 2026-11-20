from datetime import UTC, datetime, timedelta

from scorenow_api_observer.auto_watch.alerts import AutoWatchAlerts
from scorenow_api_observer.auto_watch.models import AutoWatchActiveEvent
from scorenow_api_observer.discord_alert_state import DiscordAlertState
from scorenow_api_observer.event_view.models import CaptureMetadata
from scorenow_api_observer.event_view.response import EventViewResponseIssue

START = datetime(2026, 11, 19, 4, tzinfo=UTC)


def event(event_id, sport="football"):
    return AutoWatchActiveEvent(
        event_id=event_id,
        sport_code=sport,
        league_id="1",
        league_label="league",
        scheduled_at_utc=START,
        added_at=START,
    )


def metadata(cycle, requested, missing):
    return CaptureMetadata(
        captured_at=START + timedelta(minutes=cycle),
        endpoint="/v1/event/view",
        provider="betsapi",
        http_method="GET",
        response_analysis_status="completed",
        requested_event_ids=requested,
        returned_event_ids=[
            event_id for event_id in requested if event_id not in missing
        ],
        response_issues=[
            EventViewResponseIssue("missing_requested_event", event_id, [])
            for event_id in missing
        ],
        http_status_code=200,
        elapsed_ms=0,
        response_size_bytes=0,
        content_type=None,
        raw_file_path="raw.json",
    )


def test_single_missing_needs_three_consecutive_cycles_and_resets_when_returned(
    tmp_path,
):
    sent = []

    def send(title, description, **kwargs):
        sent.append((title, description))
        return "123"

    alerts = AutoWatchAlerts(DiscordAlertState(send, tmp_path), started_at=START)
    events = {"A": event("A")}
    alerts.response(metadata(1, ["A"], []), cycle=1, events=events)
    for cycle in (2, 3, 5, 6, 6):
        alerts.response(metadata(cycle, ["A"], ["A"]), cycle=cycle, events=events)
    assert sent == []
    for cycle in (7, 8):
        alerts.response(metadata(cycle, ["A"], ["A"]), cycle=cycle, events=events)
    assert len(sent) == 1
    assert "경기 A" in sent[0][1]
    assert "13:01:00 KST" in sent[0][1]
    alerts.response(metadata(9, ["A"], []), cycle=9, events=events)
    for cycle in (10, 11, 12):
        alerts.response(metadata(cycle, ["A"], ["A"]), cycle=cycle, events=events)
    assert len(sent) == 2
    assert "13:09:00 KST" in sent[1][1]


def test_two_missing_events_alert_immediately_and_repeated_absence_is_deduplicated(
    tmp_path,
):
    sent = []

    def send(title, description, **kwargs):
        sent.append(description)
        return "123"

    alerts = AutoWatchAlerts(DiscordAlertState(send, tmp_path), started_at=START)
    events = {event_id: event(event_id) for event_id in ("A", "B")}
    for cycle in (1, 2, 3):
        alerts.response(
            metadata(cycle, ["A", "B"], ["A", "B"]), cycle=cycle, events=events
        )
    assert len(sent) == 1
    assert "경기 A" in sent[0] and "경기 B" in sent[0]


def test_time_status_two_waits_for_thirty_minutes_after_schedule_and_continuous_observations(
    tmp_path,
):
    sent = []

    def send(title, description, **kwargs):
        sent.append((title, description))
        return "123"

    alerts = AutoWatchAlerts(
        DiscordAlertState(send, tmp_path), started_at=START
    ).matches
    match = event("A")
    match.scheduled_at_utc = START + timedelta(minutes=15)

    def observe(cycle, minutes, status):
        alerts.observe(
            match,
            {"time_status": status},
            observed_at=START + timedelta(minutes=minutes),
            cycle=cycle,
        )

    observe(1, 0, 2)
    observe(2, 44, "2")
    assert not sent
    observe(3, 45, "2")
    observe(4, 46, "2")
    assert len(sent) == 1
    assert "시간 미정" in sent[0][0]

    observe(5, 47, 0)
    observe(6, 48, 2)
    observe(8, 80, 2)
    assert len(sent) == 1
    observe(9, 110, 2)
    assert len(sent) == 2


def test_match_status_transition_and_extra_period_alerts_survive_restart(tmp_path):
    sent = []

    def send(title, description, **kwargs):
        sent.append((title, description))
        return "123"

    def new_alerts():
        return AutoWatchAlerts(
            DiscordAlertState(send, tmp_path), started_at=START
        ).matches

    football = event("A")
    football.last_time_status = 3
    football.finished_detected_at = START
    baseball = event("B", "baseball")
    alerts = new_alerts()
    alerts.observe(
        football,
        {"time_status": "1", "timer": {"md": "3"}},
        observed_at=START,
        cycle=1,
    )
    assert {item[0] for item in sent} == {
        "ℹ️ 축구 연장 후반 최초 관측",
        "⚠️ 종료 경기에서 경기 중 상태 관측",
    }
    assert any("3 → 1" in item[1] for item in sent)
    alerts.observe(football, {"time_status": "7"}, observed_at=START, cycle=2)
    alerts.observe(football, {"time_status": 7}, observed_at=START, cycle=3)
    assert len(sent) == 3

    scores = {"7": {"home": "3"}, "8": {"home": "", "away": None}}
    alerts.observe(
        baseball,
        {"time_status": 1, "extra": {"numberofperiods": "7"}, "scores": scores},
        observed_at=START,
        cycle=3,
    )
    assert len(sent) == 3
    scores["8"]["away"] = 0
    alerts.observe(
        baseball,
        {"time_status": 1, "extra": {"numberofperiods": 7}, "scores": scores},
        observed_at=START,
        cycle=4,
    )
    assert any("8회 점수" in item[1] for item in sent)

    alerts = new_alerts()
    alerts.observe(football, {"time_status": 7}, observed_at=START, cycle=1)
    assert len(sent) == 4
    alerts.observe(
        football,
        {"time_status": 1, "timer": {"md": 2}},
        observed_at=START,
        cycle=2,
    )
    assert len(sent) == 4
    football.last_time_status = 1
    for cycle in (3, 4):
        alerts.observe(
            football,
            {"time_status": 1, "timer": {"md": "4"}},
            observed_at=START,
            cycle=cycle,
        )
    assert sent[-1][0] == "ℹ️ 축구 승부차기 최초 관측"
    assert len(sent) == 5
    scores["10"] = {"home": 2}
    alerts.observe(
        baseball,
        {"time_status": 1, "extra": {"numberofperiods": 7}, "scores": scores},
        observed_at=START,
        cycle=4,
    )
    assert len(sent) == 5
