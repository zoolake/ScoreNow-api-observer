from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import SecretStr, ValidationError
from typer.testing import CliRunner

from scorenow_api_observer import cli
from scorenow_api_observer.event_odds.collector import (
    OddsCollectionEventResult,
    OddsCollectionResult,
    OddsCollectionStatus,
)
from scorenow_api_observer.upcoming.candidates import (
    LatestLeagueDiscoveries,
    LoadedLeagueDiscovery,
)
from scorenow_api_observer.upcoming.models import (
    DiscoveredUpcomingEvent,
    LeagueUpcomingDiscovery,
    UpcomingDiscoveryTarget,
    UpcomingLeague,
    UpcomingParticipant,
)


class _FakeSettings:
    bets_api_base_url = "https://example.test"
    bets_api_token = SecretStr("test-token")


KST = ZoneInfo("Asia/Seoul")


def _result(
    *, statuses: list[Literal["captured", "request_failed"]]
) -> OddsCollectionResult:
    event_results = []
    for index, status in enumerate(statuses):
        event_id = chr(ord("A") + index)
        if status == "captured":
            event_results.append(
                OddsCollectionEventResult(
                    event_id=event_id,
                    status="captured",
                    http_status_code=200,
                    raw_file_path=f"raw/{event_id}.json",
                    metadata_file_path=f"metadata/{event_id}.json",
                )
            )
        else:
            event_results.append(
                OddsCollectionEventResult(
                    event_id=event_id,
                    status="request_failed",
                    error_type="ConnectError",
                    error_message="API 서버에 연결하지 못했습니다.",
                )
            )

    captured_count = sum(result.status == "captured" for result in event_results)
    if captured_count == len(event_results):
        collection_status: OddsCollectionStatus = "completed"
    elif captured_count == 0:
        collection_status = "failed"
    else:
        collection_status = "partial"

    return OddsCollectionResult(
        status=collection_status,
        event_results=event_results,
        snapshots=[],
    )


def _upcoming_discovery(
    *,
    completed_at: datetime,
    events: list[DiscoveredUpcomingEvent],
) -> LeagueUpcomingDiscovery:
    return LeagueUpcomingDiscovery(
        discovery_run_id="2026-10-22T09-00-00_KST",
        status="completed",
        completed_at=completed_at,
        target_date=date(2026, 10, 22),
        target=UpcomingDiscoveryTarget(
            sport_id="16",
            sport_code="baseball",
            league_id="225",
            league_label="mlb",
        ),
        capture_metadata_file_path="metadata.json",
        events=events,
        failure=None,
    )


def _upcoming_event(
    *,
    event_id: str,
    scheduled_at: datetime,
    time_status: str | None,
) -> DiscoveredUpcomingEvent:
    return DiscoveredUpcomingEvent(
        event_id=event_id,
        sport_id="16",
        sport_code="baseball",
        time_status=time_status,
        scheduled_at_utc=scheduled_at,
        scheduled_at_kst=scheduled_at.astimezone(KST),
        league=UpcomingLeague(id="225", name="MLB", country_code="us"),
        home=UpcomingParticipant(id="H", name="Home"),
        away=UpcomingParticipant(id="A", name="Away"),
        source_capture_metadata_file_path="metadata.json",
        result_index=0,
    )


def _latest_discoveries(
    selected: list[LoadedLeagueDiscovery],
) -> LatestLeagueDiscoveries:
    return LatestLeagueDiscoveries(
        selected=selected,
        fallbacks=[],
        unavailable=[],
        load_failures=[],
    )


def test_collect_odds_normalizes_event_ids(monkeypatch) -> None:
    received_event_ids: list[str] = []
    monkeypatch.setattr(cli, "Settings", _FakeSettings)

    def collect_event_odds(**kwargs: object) -> OddsCollectionResult:
        received_event_ids.extend(kwargs["event_ids"])  # type: ignore[arg-type]
        return _result(statuses=["captured", "captured"])

    monkeypatch.setattr(cli, "collect_event_odds", collect_event_odds)

    result = CliRunner().invoke(
        cli.app,
        ["collect-odds", "--event-ids", " B, A, B "],
    )

    assert result.exit_code == 0
    assert received_event_ids == ["A", "B"]
    assert "Odds 수집 상태: completed" in result.output
    assert "Snapshot 저장: 2개" in result.output


def test_collect_odds_partial_result_warns_and_exits_zero(monkeypatch) -> None:
    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(
        cli,
        "collect_event_odds",
        lambda **_kwargs: _result(statuses=["captured", "request_failed"]),
    )

    result = CliRunner().invoke(
        cli.app,
        ["collect-odds", "--event-ids", "A,B"],
    )

    assert result.exit_code == 0
    assert "Odds 수집 상태: partial" in result.output
    assert "일부 이벤트의 배당률 수집에 실패했습니다." in result.output


def test_collect_odds_failed_result_exits_one(monkeypatch) -> None:
    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(
        cli,
        "collect_event_odds",
        lambda **_kwargs: _result(statuses=["request_failed"]),
    )

    result = CliRunner().invoke(
        cli.app,
        ["collect-odds", "--event-ids", "A"],
    )

    assert result.exit_code == 1
    assert "모든 이벤트의 배당률 수집에 실패했습니다." in result.output


def test_collect_odds_rejects_invalid_event_ids_before_loading_settings(
    monkeypatch,
) -> None:
    settings_loaded = False

    def load_settings() -> _FakeSettings:
        nonlocal settings_loaded
        settings_loaded = True
        return _FakeSettings()

    monkeypatch.setattr(cli, "Settings", load_settings)

    result = CliRunner().invoke(
        cli.app,
        ["collect-odds", "--event-ids", "A,,B"],
    )

    assert result.exit_code == 2
    assert not settings_loaded
    assert "이벤트 ID 입력이 올바르지 않습니다." in result.output


def test_collect_odds_settings_error_exits_two(monkeypatch) -> None:
    def fail_to_load_settings() -> _FakeSettings:
        raise ValidationError.from_exception_data("Settings", [])

    monkeypatch.setattr(cli, "Settings", fail_to_load_settings)

    result = CliRunner().invoke(
        cli.app,
        ["collect-odds", "--event-ids", "A"],
    )

    assert result.exit_code == 2
    assert "API 설정을 읽지 못했습니다." in result.output


def test_collect_upcoming_odds_collects_candidates_selected_by_schedule(
    monkeypatch,
) -> None:
    now = datetime(2026, 10, 22, 0, tzinfo=UTC)
    path = Path("data/discoveries/mlb.json")
    discovery = _upcoming_discovery(
        completed_at=now - timedelta(minutes=1),
        events=[
            _upcoming_event(
                event_id="EVENT-A",
                scheduled_at=now + timedelta(minutes=3),
                time_status="1",
            ),
            _upcoming_event(
                event_id="EVENT-B",
                scheduled_at=now + timedelta(minutes=5),
                time_status=None,
            ),
        ],
    )
    loaded = LoadedLeagueDiscovery(file_path=path, discovery=discovery)
    received_event_ids: list[str] = []

    monkeypatch.setattr(
        cli,
        "find_league_upcoming_discovery_paths",
        lambda: [path],
    )
    monkeypatch.setattr(
        cli,
        "resolve_latest_league_discoveries",
        lambda _paths: _latest_discoveries([loaded]),
    )
    monkeypatch.setattr(cli, "_utc_now", lambda: now)
    monkeypatch.setattr(cli, "Settings", _FakeSettings)

    def collect_event_odds(**kwargs: object) -> OddsCollectionResult:
        received_event_ids.extend(kwargs["event_ids"])  # type: ignore[arg-type]
        return _result(statuses=["captured", "captured"])

    monkeypatch.setattr(cli, "collect_event_odds", collect_event_odds)

    result = CliRunner().invoke(
        cli.app,
        [
            "collect-upcoming-odds",
            "--within-minutes",
            "10",
            "--sport-code",
            "baseball",
            "--league-labels",
            "mlb",
        ],
    )

    assert result.exit_code == 0
    assert received_event_ids == ["EVENT-A", "EVENT-B"]
    assert "Odds 수집 후보 경기: 2개" in result.output
    assert "Odds 수집 상태: completed" in result.output
    assert "Snapshot 저장: 2개" in result.output


def test_collect_upcoming_odds_returns_without_settings_when_no_candidate(
    monkeypatch,
) -> None:
    now = datetime(2026, 10, 22, 0, tzinfo=UTC)
    path = Path("data/discoveries/mlb.json")
    discovery = _upcoming_discovery(
        completed_at=now - timedelta(minutes=1),
        events=[
            _upcoming_event(
                event_id="EVENT-LATER",
                scheduled_at=now + timedelta(minutes=30),
                time_status="0",
            )
        ],
    )
    loaded = LoadedLeagueDiscovery(file_path=path, discovery=discovery)

    def fail_to_load_settings() -> _FakeSettings:
        raise AssertionError("후보가 없으면 API 설정을 읽으면 안 됩니다.")

    monkeypatch.setattr(
        cli,
        "find_league_upcoming_discovery_paths",
        lambda: [path],
    )
    monkeypatch.setattr(
        cli,
        "resolve_latest_league_discoveries",
        lambda _paths: _latest_discoveries([loaded]),
    )
    monkeypatch.setattr(cli, "_utc_now", lambda: now)
    monkeypatch.setattr(cli, "Settings", fail_to_load_settings)

    result = CliRunner().invoke(cli.app, ["collect-upcoming-odds"])

    assert result.exit_code == 0
    assert "Odds 수집 후보 경기: 0개" in result.output
    assert "현재 Odds를 수집할 예정 경기 후보가 없습니다." in result.output


def test_collect_upcoming_odds_exits_one_without_usable_discovery(
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "find_league_upcoming_discovery_paths", list)
    monkeypatch.setattr(
        cli,
        "resolve_latest_league_discoveries",
        lambda _paths: _latest_discoveries([]),
    )

    result = CliRunner().invoke(cli.app, ["collect-upcoming-odds"])

    assert result.exit_code == 1
    assert "사용 가능한 리그 Discovery가 없습니다." in result.output


def test_collect_upcoming_odds_rejects_empty_league_label_filter() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["collect-upcoming-odds", "--league-labels", "mlb,"],
    )

    assert result.exit_code == 2
    assert "후보 조회 필터가 올바르지 않습니다." in result.output
