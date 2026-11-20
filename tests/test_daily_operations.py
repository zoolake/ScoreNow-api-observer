from datetime import UTC, date, datetime, timedelta

from scorenow_api_observer.auto_watch.exceptions import (
    AutoWatchExceptionRecord,
    save_auto_watch_exception_record,
)
from scorenow_api_observer.bets_api_request_log import (
    EventOddsRequestDetails,
    EventViewRequestDetails,
    RequestedEvent,
    finish_bets_api_request,
    start_bets_api_request,
)
from scorenow_api_observer.event_view.request_log import (
    RequestedEvent as LegacyRequestedEvent,
)
from scorenow_api_observer.event_view.request_log import (
    start_event_view_api_request,
)
from scorenow_api_observer.reporting.daily_operations import collect_daily_operations


def test_daily_operations_counts_kst_boundaries_and_legacy_records(tmp_path):
    start = datetime(2026, 11, 18, 15, tzinfo=UTC)
    end = start + timedelta(days=1)
    requests = tmp_path / "requests"
    legacy = tmp_path / "legacy"
    exceptions = tmp_path / "exceptions"
    odds = EventOddsRequestDetails(event_id="1", odds_markets=[1])
    for when in (start - timedelta(seconds=1), start, end):
        handle = start_bets_api_request(
            request=odds, requested_at=when, base_directory=requests
        )
        finish_bets_api_request(
            handle=handle,
            completed_at=when + timedelta(seconds=1),
            outcome="completed",
            http_status_code=429,
        )
        save_auto_watch_exception_record(
            AutoWatchExceptionRecord(
                event_id=str(when),
                sport_code="baseball",
                league_id="1",
                league_label="KBO",
                scheduled_at_utc=when,
                scheduled_at_kst=when,
                observation_started_at=when,
                stopped_at=when,
                stop_time_status=0,
                last_capture_metadata_path=None,
            ),
            base_directory=exceptions,
        )

    failed = start_bets_api_request(
        request=EventViewRequestDetails(
            requested_events=[RequestedEvent(event_id="2", sport_code="football")]
        ),
        requested_at=start + timedelta(minutes=5),
        base_directory=requests,
    )
    finish_bets_api_request(
        handle=failed,
        completed_at=start + timedelta(minutes=6),
        outcome="request_error",
        error_type="ConnectError",
    )
    start_event_view_api_request(
        requested_events=[LegacyRequestedEvent(event_id="3", sport_code="baseball")],
        requested_at=start + timedelta(hours=1),
        base_directory=legacy,
    )
    start_event_view_api_request(
        requested_events=[LegacyRequestedEvent(event_id="4", sport_code="baseball")],
        requested_at=start + timedelta(minutes=30),
        base_directory=legacy,
    )

    (requests / start.date().isoformat() / "broken.json").write_text("{")
    (
        exceptions / "time-status-0" / start.date().isoformat() / "broken.json"
    ).write_text("{")
    report = collect_daily_operations(
        date(2026, 11, 19),
        request_base_directory=requests,
        legacy_base_directory=legacy,
        exception_base_directory=exceptions,
    )
    assert report.endpoint_counts == {
        "/v1/event/view": 3,
        "/v2/event/odds": 1,
        "/v3/events/upcoming": 0,
    }
    assert report.http_errors == {429: 1}
    assert report.connection_failures == 1
    assert report.unfinished_requests == 2
    for peak in report.hourly_peaks.values():
        assert peak.count == 2
        assert peak.window_start == start
        assert peak.percent == 200 / peak.limit
    assert report.exception_counts == {0: 1}
    assert report.exceptions[0].record.stopped_at == start
    assert report.exceptions[0].record.league_label == "KBO"
    assert len(report.failures) == 2


def test_publish_command_saves_report_before_send_and_reuses_it(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    import httpx
    from pydantic import SecretStr
    from typer.testing import CliRunner

    from scorenow_api_observer import cli
    from scorenow_api_observer.discord_webhook import DiscordWebhook
    from scorenow_api_observer.reporting.daily_publication import publish_daily_report

    config = Path("config/auto_watch.yaml").resolve()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_utc_now", lambda: datetime(2026, 11, 19, 15, tzinfo=UTC))
    monkeypatch.setattr(
        cli, "Settings", lambda: (_ for _ in ()).throw(AssertionError("BETS 설정 로드"))
    )
    report_path = Path("reports/daily-operations/2026-11-19.md")
    sent_messages = []

    def handler(request):
        saved = report_path.read_bytes()
        assert saved in request.content
        assert b'name="payload_json"' in request.content
        assert b'filename="2026-11-19.md"' in request.content
        sent_messages.append(saved)
        if len(sent_messages) == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=json.dumps({"id": "321"}))

    def collect(target_date):
        assert not sent_messages, "저장된 보고서를 다시 집계함"
        return collect_daily_operations(
            target_date, config_path=config.with_name("missing.yaml")
        )

    def local_publish(target_date, **kwargs):
        return publish_daily_report(target_date, collect=collect, **kwargs)

    webhook = DiscordWebhook(
        SecretStr("https://discord.example/api/webhooks/123/private"),
        httpx.MockTransport(handler),
    )
    monkeypatch.setattr(cli, "load_discord_webhook", lambda: webhook)
    monkeypatch.setattr(cli, "publish_daily_report", local_publish)
    runner = CliRunner()
    assert runner.invoke(cli.app, ["publish-daily-report"]).exit_code == 1
    assert "부분 집계" in report_path.read_text(encoding="utf-8")
    assert not report_path.with_suffix(".published").exists()

    assert (
        runner.invoke(
            cli.app, ["publish-daily-report", "--date", "2026-11-19"]
        ).exit_code
        == 0
    )
    assert report_path.with_suffix(".published").read_text() == "321\n"
    assert len(sent_messages) == 2
    assert sent_messages[0] == sent_messages[1]
    automatic = runner.invoke(cli.app, ["publish-daily-report"])
    assert automatic.exit_code == 0
    assert "이미 발행" in automatic.output
    assert len(sent_messages) == 2
