from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner

from scorenow_api_observer import cli
from scorenow_api_observer.auto_watch.exceptions import (
    AutoWatchExceptionRecord,
    save_auto_watch_exception_record,
)
from scorenow_api_observer.auto_watch.heartbeat import (
    new_auto_watch_heartbeat,
    save_auto_watch_heartbeat,
)
from scorenow_api_observer.auto_watch.models import (
    AutoWatchActiveEvent,
    AutoWatchState,
)
from scorenow_api_observer.auto_watch.state import save_auto_watch_state
from scorenow_api_observer.auto_watch.status import (
    build_auto_watch_status_report,
    render_auto_watch_status,
)
from scorenow_api_observer.bets_api_request_log import (
    BetsApiRequestRecord,
    EventOddsRequestDetails,
    EventViewRequestDetails,
    RateLimitSnapshot,
    RequestedEvent,
    UpcomingRequestDetails,
    classify_request_category,
    classify_sport_codes,
)
from scorenow_api_observer.event_view.request_log import (
    EventViewApiRequestRecord as LegacyEventViewApiRequestRecord,
)
from scorenow_api_observer.event_view.request_log import (
    RequestedEvent as LegacyRequestedEvent,
)

KST = ZoneInfo("Asia/Seoul")
CONFIG_PATH = Path("config/auto_watch.yaml")


def _save_request_record(
    base_directory: Path,
    *,
    request_id: str,
    requested_at: datetime,
    sport_codes: list[str | None],
    http_status_code: int = 200,
    rate_limit: RateLimitSnapshot | None = None,
) -> Path:
    requested_events = [
        RequestedEvent(event_id=f"{request_id}-{index}", sport_code=sport_code)
        for index, sport_code in enumerate(sport_codes)
    ]
    record = BetsApiRequestRecord(
        request_id=request_id,
        requested_at=requested_at,
        completed_at=requested_at + timedelta(seconds=1),
        endpoint="/v1/event/view",
        request_category=classify_request_category(requested_events),
        request=EventViewRequestDetails(requested_events=requested_events),
        outcome="completed",
        http_status_code=http_status_code,
        rate_limit=rate_limit,
    )
    output_path = (
        base_directory / requested_at.date().isoformat() / f"{request_id}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def _save_upcoming_request_record(
    base_directory: Path,
    *,
    request_id: str,
    requested_at: datetime,
    sport_code: str,
) -> Path:
    record = BetsApiRequestRecord(
        request_id=request_id,
        requested_at=requested_at,
        completed_at=requested_at + timedelta(seconds=1),
        endpoint="/v3/events/upcoming",
        request_category=classify_sport_codes([sport_code]),
        request=UpcomingRequestDetails(
            sport_id="1" if sport_code == "football" else "16",
            sport_code=sport_code,
            league_id="league",
            league_label="league-label",
            target_date=requested_at.date(),
        ),
        outcome="completed",
        http_status_code=200,
    )
    output_path = (
        base_directory / requested_at.date().isoformat() / f"{request_id}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def _save_odds_request_record(
    base_directory: Path,
    *,
    request_id: str,
    requested_at: datetime,
    sport_code: str | None,
) -> Path:
    record = BetsApiRequestRecord(
        request_id=request_id,
        requested_at=requested_at,
        completed_at=requested_at + timedelta(seconds=1),
        endpoint="/v2/event/odds",
        request_category=classify_sport_codes([sport_code]),
        request=EventOddsRequestDetails(
            event_id=f"event-{request_id}",
            sport_code=sport_code,
            odds_markets=[1, 2, 3],
        ),
        outcome="completed",
        http_status_code=200,
    )
    output_path = (
        base_directory / requested_at.date().isoformat() / f"{request_id}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def _exception_record(
    *, event_id: str, stopped_at: datetime
) -> AutoWatchExceptionRecord:
    return AutoWatchExceptionRecord(
        event_id=event_id,
        sport_code="baseball",
        league_id="349",
        league_label="kbo",
        scheduled_at_utc=stopped_at - timedelta(hours=3),
        scheduled_at_kst=(stopped_at - timedelta(hours=3)).astimezone(KST),
        observation_started_at=stopped_at - timedelta(hours=2),
        stopped_at=stopped_at,
        stop_time_status=10,
        last_capture_metadata_path=None,
    )


def test_status_counts_current_hour_and_valid_headers_by_category(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 18, 0, 10, tzinfo=UTC)
    window_end = datetime(2026, 11, 18, 1, tzinfo=UTC)
    request_directory = tmp_path / "requests"
    _save_request_record(
        request_directory,
        request_id="daily-baseball",
        requested_at=datetime(2026, 11, 17, 15, 5, tzinfo=UTC),
        sport_codes=["baseball"],
    )
    _save_request_record(
        request_directory,
        request_id="previous-hour-football",
        requested_at=datetime(2026, 11, 17, 23, 50, tzinfo=UTC),
        sport_codes=["football"],
    )
    _save_request_record(
        request_directory,
        request_id="current-football",
        requested_at=datetime(2026, 11, 18, 0, 0, tzinfo=UTC),
        sport_codes=["football"],
        rate_limit=RateLimitSnapshot(
            limit=3600,
            remaining=3500,
            reset_at=window_end,
        ),
    )
    _save_request_record(
        request_directory,
        request_id="current-football-latest",
        requested_at=datetime(2026, 11, 18, 0, 1, tzinfo=UTC),
        sport_codes=["football"],
        rate_limit=RateLimitSnapshot(
            limit=3600,
            remaining=3499,
            reset_at=window_end,
        ),
    )
    _save_request_record(
        request_directory,
        request_id="current-baseball-expired-header",
        requested_at=datetime(2026, 11, 18, 0, 2, tzinfo=UTC),
        sport_codes=["baseball"],
        rate_limit=RateLimitSnapshot(
            limit=3600,
            remaining=1111,
            reset_at=datetime(2026, 11, 18, 0, 0, tzinfo=UTC),
        ),
    )
    _save_request_record(
        request_directory,
        request_id="current-mixed",
        requested_at=datetime(2026, 11, 18, 0, 5, tzinfo=UTC),
        sport_codes=["football", "baseball"],
        rate_limit=RateLimitSnapshot(
            limit=3600,
            remaining=3490,
            reset_at=window_end,
        ),
    )
    _save_request_record(
        request_directory,
        request_id="current-unknown",
        requested_at=datetime(2026, 11, 18, 0, 9, tzinfo=UTC),
        sport_codes=[None],
        rate_limit=RateLimitSnapshot(
            limit=3600,
            remaining=3480,
            reset_at=window_end,
        ),
    )
    _save_upcoming_request_record(
        request_directory,
        request_id="current-upcoming-football",
        requested_at=datetime(2026, 11, 18, 0, 3, tzinfo=UTC),
        sport_code="football",
    )
    _save_odds_request_record(
        request_directory,
        request_id="current-odds-baseball",
        requested_at=datetime(2026, 11, 18, 0, 4, tzinfo=UTC),
        sport_code="baseball",
    )

    report = build_auto_watch_status_report(
        now=now,
        target_date_kst=date(2026, 11, 18),
        config_path=CONFIG_PATH,
        state_path=tmp_path / "missing-state.json",
        heartbeat_path=tmp_path / "missing-heartbeat.json",
        request_base_directory=request_directory,
        legacy_event_view_request_base_directory=tmp_path / "legacy-requests",
        exception_base_directory=tmp_path / "exceptions",
    )

    assert report.requests.window_start == datetime(2026, 11, 18, 0, tzinfo=UTC)
    assert report.requests.window_end == window_end
    assert len(report.requests.current_window_records) == 7
    assert len(report.requests.daily_records) == 9
    assert report.requests.current_window_category_counts() == {
        "football_only": 3,
        "baseball_only": 2,
        "mixed": 1,
        "unknown": 1,
    }
    assert report.requests.current_window_endpoint_counts() == {
        "/v1/event/view": 5,
        "/v3/events/upcoming": 1,
        "/v2/event/odds": 1,
    }
    assert set(report.requests.valid_rate_limit_records) == {
        "football_only",
        "mixed",
        "unknown",
    }
    output = render_auto_watch_status(report)
    assert "KST: 2026-11-18 09:00:00 ~ 2026-11-18 10:00:00" in output
    assert "UTC: 2026-11-18 00:00:00 ~ 2026-11-18 01:00:00" in output
    assert "Soccer API: 5 / 3,600회" in output
    assert "Baseball API: 4 / 3,600회" in output
    assert "Event View: 5회" in output
    assert "Upcoming: 1회" in output
    assert "Event Odds: 1회" in output
    assert "남은 요청: 3,499회" in output
    assert "남은 요청: 3,500회" not in output
    assert "남은 요청: 3,490회" in output
    assert "남은 요청: 3,480회" in output
    assert "남은 요청: 1,111회" not in output
    assert "야구 전용 응답" not in output
    assert "2026-11-18 KST 누적 요청" in output
    assert "전체 요청 시도: 9회" in output


def test_status_uses_start_inclusive_end_exclusive_hour_boundary(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 18, 1, 0, tzinfo=UTC)
    request_directory = tmp_path / "requests"
    _save_request_record(
        request_directory,
        request_id="previous-window",
        requested_at=datetime(2026, 11, 18, 0, 59, 59, tzinfo=UTC),
        sport_codes=["football"],
    )
    _save_request_record(
        request_directory,
        request_id="current-window-start",
        requested_at=now,
        sport_codes=["baseball"],
    )
    _save_request_record(
        request_directory,
        request_id="future-current-window",
        requested_at=now + timedelta(seconds=1),
        sport_codes=["baseball"],
    )

    report = build_auto_watch_status_report(
        now=now,
        target_date_kst=date(2026, 11, 18),
        config_path=CONFIG_PATH,
        state_path=tmp_path / "missing-state.json",
        heartbeat_path=tmp_path / "missing-heartbeat.json",
        request_base_directory=request_directory,
        legacy_event_view_request_base_directory=tmp_path / "legacy-requests",
        exception_base_directory=tmp_path / "exceptions",
    )

    assert [record.request_id for record in report.requests.current_window_records] == [
        "current-window-start"
    ]
    assert report.requests.window_start == now
    assert report.requests.window_end == now + timedelta(hours=1)


def test_status_includes_legacy_event_view_request_records(tmp_path: Path) -> None:
    now = datetime(2026, 11, 18, 1, 10, tzinfo=UTC)
    legacy_directory = tmp_path / "legacy-requests"
    record = LegacyEventViewApiRequestRecord(
        request_id="legacy-event-view",
        requested_at=now - timedelta(minutes=5),
        completed_at=now - timedelta(minutes=5) + timedelta(seconds=1),
        request_category="football_only",
        requested_events=[
            LegacyRequestedEvent(event_id="legacy-event", sport_code="football")
        ],
        outcome="completed",
        http_status_code=200,
    )
    output_path = (
        legacy_directory
        / record.requested_at.date().isoformat()
        / "legacy-event-view.json"
    )
    output_path.parent.mkdir(parents=True)
    output_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

    report = build_auto_watch_status_report(
        now=now,
        target_date_kst=date(2026, 11, 18),
        config_path=CONFIG_PATH,
        state_path=tmp_path / "missing-state.json",
        heartbeat_path=tmp_path / "missing-heartbeat.json",
        request_base_directory=tmp_path / "requests",
        legacy_event_view_request_base_directory=legacy_directory,
        exception_base_directory=tmp_path / "exceptions",
    )

    assert [item.request_id for item in report.requests.current_window_records] == [
        "legacy-event-view"
    ]
    assert report.requests.current_window_endpoint_counts()["/v1/event/view"] == 1


def test_status_keeps_valid_results_when_one_file_is_damaged(tmp_path: Path) -> None:
    now = datetime(2026, 11, 18, 0, 10, tzinfo=UTC)
    request_directory = tmp_path / "requests"
    _save_request_record(
        request_directory,
        request_id="valid",
        requested_at=now - timedelta(minutes=5),
        sport_codes=["football"],
    )
    damaged_path = request_directory / "2026-11-17" / "damaged.json"
    damaged_path.parent.mkdir(parents=True, exist_ok=True)
    damaged_path.write_text("{not-json", encoding="utf-8")

    report = build_auto_watch_status_report(
        now=now,
        target_date_kst=date(2026, 11, 18),
        config_path=CONFIG_PATH,
        state_path=tmp_path / "missing-state.json",
        heartbeat_path=tmp_path / "missing-heartbeat.json",
        request_base_directory=request_directory,
        legacy_event_view_request_base_directory=tmp_path / "legacy-requests",
        exception_base_directory=tmp_path / "exceptions",
    )

    assert len(report.requests.current_window_records) == 1
    assert len(report.failures) == 1
    output = render_auto_watch_status(report)
    assert "전체 요청 시도: 1회" in output
    assert "일부 파일을 읽지 못했지만 나머지 자료로 상태를 표시했습니다" in output
    assert str(damaged_path) in output


def test_status_aggregates_all_exceptions_but_limits_details(tmp_path: Path) -> None:
    now = datetime(2026, 11, 18, 2, 0, tzinfo=UTC)
    exception_directory = tmp_path / "exceptions"
    for index in range(12):
        save_auto_watch_exception_record(
            _exception_record(
                event_id=f"event-{index:02d}",
                stopped_at=datetime(2026, 11, 17, 15, tzinfo=UTC)
                + timedelta(minutes=index),
            ),
            base_directory=exception_directory,
        )

    report = build_auto_watch_status_report(
        now=now,
        target_date_kst=date(2026, 11, 18),
        config_path=CONFIG_PATH,
        state_path=tmp_path / "missing-state.json",
        heartbeat_path=tmp_path / "missing-heartbeat.json",
        request_base_directory=tmp_path / "requests",
        legacy_event_view_request_base_directory=tmp_path / "legacy-requests",
        exception_base_directory=exception_directory,
    )

    assert len(report.exceptions) == 12
    output = render_auto_watch_status(report)
    assert "전체 예외: 12개" in output
    assert "time_status=10 일시 정지: 12개" in output
    assert "전체 12개 중 10개 표시" in output
    assert output.count("  • 경기 ID event-") == 10


def test_status_explains_pending_exception_save_without_api_call(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 18, 2, 0, tzinfo=UTC)
    state_path = tmp_path / "state.json"
    save_auto_watch_state(
        AutoWatchState(
            updated_at=now,
            active_events=[
                AutoWatchActiveEvent(
                    event_id="pending",
                    sport_code="baseball",
                    league_id="349",
                    league_label="kbo",
                    scheduled_at_utc=now - timedelta(hours=3),
                    added_at=now - timedelta(hours=4),
                    last_time_status=10,
                    status_policy_group="temporarily_stopped",
                    status_policy_started_at=now - timedelta(hours=2),
                    stop_decided_at=now - timedelta(minutes=1),
                )
            ],
        ),
        state_path,
    )
    heartbeat_path = tmp_path / "heartbeat.json"
    save_auto_watch_heartbeat(
        new_auto_watch_heartbeat(
            now=now - timedelta(seconds=30),
            interval_seconds=300,
            process_id=1234,
        ),
        heartbeat_path,
    )

    report = build_auto_watch_status_report(
        now=now,
        target_date_kst=date(2026, 11, 18),
        config_path=CONFIG_PATH,
        state_path=state_path,
        heartbeat_path=heartbeat_path,
        request_base_directory=tmp_path / "requests",
        legacy_event_view_request_base_directory=tmp_path / "legacy-requests",
        exception_base_directory=tmp_path / "exceptions",
    )

    output = render_auto_watch_status(report)
    assert "상태: 정상 실행 중" in output
    assert "예외 파일 저장을 재시도하는 경기가 1개" in output
    assert "추가 API 호출: 하지 않음" in output
    assert "현재 작업: 예외 JSON 저장 재시도" in output


def test_auto_watch_status_cli_reads_local_files_without_api_settings(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_text = CONFIG_PATH.read_text(encoding="utf-8")
    config_path = tmp_path / "config" / "auto_watch.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(config_text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def fail_if_settings_are_loaded():
        raise AssertionError("auto-watch-status must not load API settings")

    monkeypatch.setattr(cli, "Settings", fail_if_settings_are_loaded)

    result = CliRunner().invoke(
        cli.app,
        ["auto-watch-status", "--date", "2026-11-18"],
    )

    assert result.exit_code == 0
    assert "Auto-watch 현재 상태" in result.output
    assert "2026-11-18 KST 누적 요청" in result.output
