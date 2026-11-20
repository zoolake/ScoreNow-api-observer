import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from scorenow_api_observer import cli
from scorenow_api_observer.auto_watch.config import load_auto_watch_config
from scorenow_api_observer.auto_watch.models import AutoWatchActiveEvent, AutoWatchState
from scorenow_api_observer.auto_watch.state import (
    load_auto_watch_state,
    save_auto_watch_state,
)
from scorenow_api_observer.bets_api_request_log import BetsApiRequestRecord
from scorenow_api_observer.discord_webhook import DiscordWebhook
from scorenow_api_observer.event_view import collector as event_view_collector
from scorenow_api_observer.settings import Settings
from scorenow_api_observer.upcoming import discovery as upcoming_discovery
from scorenow_api_observer.upcoming.models import LeagueUpcomingDiscovery
from scorenow_api_observer.upcoming.targets import UpcomingTarget


class _FakeSecret:
    def get_secret_value(self) -> str:
        return "test-token"


class _FakeSettings:
    bets_api_base_url = "https://example.test"
    bets_api_token = _FakeSecret()


def _upcoming_event(
    event_id: str,
    *,
    scheduled_at: datetime,
) -> dict[str, object]:
    return {
        "id": event_id,
        "sport_id": "16",
        "time": str(int(scheduled_at.timestamp())),
        "time_status": "0",
        "league": {"id": "349", "name": "KBO", "cc": "kr"},
        "home": {"id": f"{event_id}-home", "name": "Home"},
        "away": {"id": f"{event_id}-away", "name": "Away"},
    }


def _response(
    *,
    endpoint: str,
    body: dict[str, object],
) -> httpx.Response:
    response = httpx.Response(
        200,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", f"https://example.test{endpoint}"),
    )
    response.elapsed = timedelta(milliseconds=1)
    return response


def test_auto_discovery_files_feed_running_auto_watch_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auto_watch_config = load_auto_watch_config()
    runner = CliRunner()
    current_time = datetime(2026, 11, 18, 0, 0, tzinfo=UTC)
    scheduled_a = current_time + timedelta(minutes=5)
    scheduled_b = current_time + timedelta(minutes=6)
    target = UpcomingTarget("16", "baseball", "349", "kbo", True)
    upcoming_call_count = 0
    discovery_clock_tick = 0
    captured_batches: list[list[str]] = []
    second_discovery_exit_codes: list[int] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(cli, "load_upcoming_targets", lambda: [target])
    monkeypatch.setattr(cli, "_utc_now", lambda: current_time)

    def discovery_now() -> datetime:
        nonlocal discovery_clock_tick
        value = current_time + timedelta(microseconds=discovery_clock_tick)
        discovery_clock_tick += 1
        return value

    monkeypatch.setattr(upcoming_discovery, "_utc_now", discovery_now)

    def get_upcoming_events(**kwargs: object) -> httpx.Response:
        nonlocal upcoming_call_count
        target_date = kwargs["target_date"]
        assert isinstance(target_date, date)
        discovery_generation = upcoming_call_count // 2
        upcoming_call_count += 1
        events: list[dict[str, object]] = []
        if target_date == current_time.date():
            events.append(_upcoming_event("A", scheduled_at=scheduled_a))
            if discovery_generation == 1:
                events.append(_upcoming_event("B", scheduled_at=scheduled_b))
        return _response(
            endpoint="/v3/events/upcoming",
            body={"results": events, "pager": {"total": len(events)}},
        )

    monkeypatch.setattr(
        upcoming_discovery,
        "get_upcoming_events",
        get_upcoming_events,
    )

    def get_event_view(**kwargs: object) -> httpx.Response:
        requested_event_ids = list(kwargs["requested_event_ids"])  # type: ignore[arg-type]
        captured_batches.append(requested_event_ids)
        return _response(
            endpoint="/v1/event/view",
            body={
                "success": 1,
                "results": [
                    {"id": event_id, "time_status": "1"}
                    for event_id in requested_event_ids
                ],
            },
        )

    monkeypatch.setattr(event_view_collector, "get_event_view", get_event_view)

    first_discovery = runner.invoke(cli.app, ["discover-auto-watch"])
    assert first_discovery.exit_code == 0, first_discovery.output

    state = AutoWatchState(updated_at=current_time, active_events=[])

    def save_second_discovery_and_advance(seconds: float) -> None:
        nonlocal current_time
        current_time += timedelta(seconds=seconds)
        second_discovery = runner.invoke(cli.app, ["discover-auto-watch"])
        second_discovery_exit_codes.append(second_discovery.exit_code)

    monkeypatch.setattr(cli.time, "sleep", save_second_discovery_and_advance)

    completed = cli._run_auto_watch(
        settings=cast(Settings, _FakeSettings()),
        state=state,
        within_minutes=10,
        interval_seconds=1,
        candidate_check_interval_seconds=1,
        max_cycles=2,
        auto_watch_config=auto_watch_config,
    )

    assert completed
    assert second_discovery_exit_codes == [0]
    assert captured_batches == [["A"], ["A", "B"]]
    assert [event.event_id for event in state.active_events] == ["A", "B"]

    discovery_paths = list(
        Path("data/discoveries/events-upcoming").glob(
            "*/leagues/baseball/349-kbo/*_discovery.json"
        )
    )
    discoveries = [
        LeagueUpcomingDiscovery.model_validate_json(path.read_text(encoding="utf-8"))
        for path in discovery_paths
    ]
    assert len(discoveries) == 4
    assert all(discovery.status == "completed" for discovery in discoveries)
    assert len(list(Path("data/raw/events-upcoming").rglob("*.json"))) == 4
    assert len(list(Path("data/metadata/events-upcoming").rglob("*.json"))) == 4

    saved_state = load_auto_watch_state(Path("data/state/auto-watch/state.json"))
    assert saved_state is not None
    assert [event.event_id for event in saved_state.active_events] == ["A", "B"]

    request_records = [
        BetsApiRequestRecord.model_validate_json(path.read_text(encoding="utf-8"))
        for path in Path("data/metrics/bets-api-requests").rglob("*.json")
    ]
    assert Counter(record.endpoint for record in request_records) == {
        "/v3/events/upcoming": 4,
        "/v1/event/view": 2,
    }


def test_collection_alerts_and_scheduled_daily_report_share_local_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured_policies = Path("config/auto_watch.yaml").read_text(encoding="utf-8")
    now = datetime(2026, 11, 19, 4, 15, tzinfo=UTC)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_utc_now", lambda: now)
    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(
        cli,
        "load_upcoming_targets",
        lambda: [UpcomingTarget("1", "football", "94", "premier-league", True)],
    )
    Path("config").mkdir()
    Path("config/auto_watch.yaml").write_text(
        configured_policies.replace("soccer_per_hour: 3600", "soccer_per_hour: 1"),
        encoding="utf-8",
    )
    save_auto_watch_state(
        AutoWatchState(
            updated_at=now,
            active_events=[
                AutoWatchActiveEvent(
                    event_id="A",
                    sport_code="football",
                    league_id="94",
                    league_label="premier-league",
                    scheduled_at_utc=now,
                    added_at=now,
                )
            ],
        )
    )

    class CaptureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(event_view_collector, "datetime", CaptureClock)
    bets_calls = 0

    def get_event_view(**kwargs):
        nonlocal bets_calls
        bets_calls += 1
        assert kwargs["requested_event_ids"] == ["A"]
        (request_path,) = Path("data/metrics/bets-api-requests").rglob("*.json")
        record = BetsApiRequestRecord.model_validate_json(request_path.read_bytes())
        assert record.outcome == "started"
        assert "test-token" not in request_path.read_text(encoding="utf-8")
        return _response(
            endpoint="/v1/event/view",
            body={
                "success": 1,
                "results": [{"id": "A", "time_status": "1", "timer": {"md": "3"}}],
            },
        )

    messages = []

    def transport(request):
        messages.append(request)
        return httpx.Response(200, json={"id": str(len(messages))})

    webhook = DiscordWebhook(
        SecretStr("https://discord.example/api/webhooks/123/private"),
        httpx.MockTransport(transport),
    )
    monkeypatch.setattr(cli, "load_discord_webhook", lambda: webhook)
    monkeypatch.setattr(event_view_collector, "get_event_view", get_event_view)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["auto-watch", "--max-cycles", "1"])
    assert result.exit_code == 0, result.output
    assert len(messages) == 1
    assert "연장 후반" in messages[0].content.decode()
    (request_path,) = Path("data/metrics/bets-api-requests").rglob("*.json")
    record = BetsApiRequestRecord.model_validate_json(request_path.read_bytes())
    assert record.outcome == "completed"
    assert record.requested_at == now

    result = runner.invoke(cli.app, ["check-operations-alerts"])
    assert result.exit_code == 0, result.output
    assert len(messages) == 3
    assert "축구 API 요청 한도 주의" in messages[1].content.decode()
    assert "축구 API 요청 한도 위험" in messages[2].content.decode()

    now = datetime(2026, 11, 20, 0, tzinfo=UTC)
    result = runner.invoke(cli.app, ["publish-daily-report"])
    assert result.exit_code == 0, result.output
    assert len(messages) == 4
    path = Path("reports/daily-operations/2026-11-19.md")
    assert path.read_bytes() in messages[-1].content
    assert "Event View 1회" in path.read_text(encoding="utf-8")
    assert "test-token" not in path.read_text(encoding="utf-8")
    assert bets_calls == 1
