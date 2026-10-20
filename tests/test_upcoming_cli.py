from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr
from typer.testing import CliRunner

from scorenow_api_observer import cli
from scorenow_api_observer.upcoming.candidates import (
    LatestLeagueDiscoveries,
    LeagueDiscoveryFallback,
    LoadedLeagueDiscovery,
)
from scorenow_api_observer.upcoming.models import (
    DiscoveredUpcomingEvent,
    LeagueUpcomingDiscovery,
    UpcomingDiscoveryFailure,
    UpcomingDiscoveryRun,
    UpcomingDiscoveryTarget,
    UpcomingLeague,
    UpcomingParticipant,
)
from scorenow_api_observer.upcoming.targets import UpcomingTarget


class _FakeSettings:
    bets_api_base_url = "https://example.test"
    bets_api_token = SecretStr("test-token")


KST = ZoneInfo("Asia/Seoul")


def _discovery_target(league_id: str, label: str) -> UpcomingDiscoveryTarget:
    return UpcomingDiscoveryTarget(
        sport_id="16",
        sport_code="baseball",
        league_id=league_id,
        league_label=label,
    )


def _completed_discovery() -> LeagueUpcomingDiscovery:
    return LeagueUpcomingDiscovery(
        discovery_run_id="2026-10-17T00-00-00_KST",
        status="completed",
        completed_at=datetime(2026, 10, 16, 15, 1, tzinfo=UTC),
        target_date=date(2026, 10, 16),
        target=_discovery_target("225", "mlb"),
        capture_metadata_file_path="data/metadata/mlb.json",
        events=[],
        failure=None,
    )


def _failed_discovery() -> LeagueUpcomingDiscovery:
    failure = UpcomingDiscoveryFailure(
        sport_id="16",
        league_id="349",
        league_label="kbo",
        error_type="ConnectError",
        error_message="API 서버에 연결하지 못했습니다.",
    )
    return LeagueUpcomingDiscovery(
        discovery_run_id="2026-10-17T00-00-00_KST",
        status="failed",
        completed_at=datetime(2026, 10, 16, 15, 1, tzinfo=UTC),
        target_date=date(2026, 10, 16),
        target=_discovery_target("349", "kbo"),
        capture_metadata_file_path=None,
        events=[],
        failure=failure,
    )


def _result(status: Literal["completed", "partial", "failed"]):
    if status == "completed":
        league_discoveries = [_completed_discovery()]
    elif status == "partial":
        league_discoveries = [_completed_discovery(), _failed_discovery()]
    else:
        league_discoveries = [_failed_discovery()]

    discovery_run = UpcomingDiscoveryRun(
        discovery_run_id="2026-10-17T00-00-00_KST",
        status=status,
        started_at=datetime(2026, 10, 16, 15, 0, tzinfo=UTC),
        completed_at=datetime(2026, 10, 16, 15, 1, tzinfo=UTC),
        target_date=date(2026, 10, 16),
        requested_targets=[item.target for item in league_discoveries],
        league_discovery_file_paths=[
            f"data/discoveries/{item.target.league_label}.json"
            for item in league_discoveries
        ],
    )
    return SimpleNamespace(
        run=discovery_run,
        run_file_path=Path("data/discoveries/run.json"),
        league_discoveries=league_discoveries,
        captures=[] if status == "failed" else [object()],
    )


def test_discover_upcoming_rejects_invalid_target_date() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["discover-upcoming", "--target-date", "20261016"],
    )

    assert result.exit_code == 2
    assert "YYYY-MM-DD" in result.output


def test_discover_upcoming_selects_requested_league_labels(monkeypatch) -> None:
    targets = [
        UpcomingTarget("16", "baseball", "225", "mlb"),
        UpcomingTarget("16", "baseball", "349", "kbo"),
    ]
    received_targets: list[UpcomingTarget] = []

    monkeypatch.setattr(cli, "load_upcoming_targets", lambda: targets)
    monkeypatch.setattr(cli, "Settings", _FakeSettings)

    def discover(**kwargs):
        received_targets.extend(kwargs["targets"])
        return _result("completed")

    monkeypatch.setattr(cli, "discover_upcoming_events", discover)

    result = CliRunner().invoke(
        cli.app,
        [
            "discover-upcoming",
            "--target-date",
            "2026-10-16",
            "--league-labels",
            "kbo,kbo",
        ],
    )

    assert result.exit_code == 0
    assert received_targets == [targets[1]]
    assert "조회 대상 종목·리그: 1개" in result.output


def test_discover_upcoming_rejects_unknown_league_label(monkeypatch) -> None:
    target = UpcomingTarget("16", "baseball", "225", "mlb")
    monkeypatch.setattr(cli, "load_upcoming_targets", lambda: [target])

    result = CliRunner().invoke(
        cli.app,
        [
            "discover-upcoming",
            "--target-date",
            "2026-10-16",
            "--league-labels",
            "unknown",
        ],
    )

    assert result.exit_code == 2
    assert "설정에 등록되지 않은 리그 label" in result.output


def test_discover_upcoming_partial_result_exits_with_zero(monkeypatch) -> None:
    target = UpcomingTarget("16", "baseball", "225", "mlb")
    monkeypatch.setattr(cli, "load_upcoming_targets", lambda: [target])
    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(
        cli,
        "discover_upcoming_events",
        lambda **_kwargs: _result("partial"),
    )

    result = CliRunner().invoke(
        cli.app,
        ["discover-upcoming", "--target-date", "2026-10-16"],
    )

    assert result.exit_code == 0
    assert "Discovery 상태: partial" in result.output
    assert "처리 실패: 1개" in result.output
    assert "일부 조회 또는 응답 분석에 이상이 있습니다." in result.output


def test_discover_upcoming_failed_result_exits_with_one(monkeypatch) -> None:
    target = UpcomingTarget("16", "baseball", "225", "mlb")
    monkeypatch.setattr(cli, "load_upcoming_targets", lambda: [target])
    monkeypatch.setattr(cli, "Settings", _FakeSettings)
    monkeypatch.setattr(
        cli,
        "discover_upcoming_events",
        lambda **_kwargs: _result("failed"),
    )

    result = CliRunner().invoke(
        cli.app,
        ["discover-upcoming", "--target-date", "2026-10-16"],
    )

    assert result.exit_code == 1
    assert "Discovery 상태: failed" in result.output
    assert "예정 경기 조회에 모두 실패했습니다." in result.output


def test_discover_upcoming_config_error_exits_with_two(monkeypatch) -> None:
    def fail_to_load_targets() -> list[UpcomingTarget]:
        raise ValueError("invalid target config")

    monkeypatch.setattr(cli, "load_upcoming_targets", fail_to_load_targets)

    result = CliRunner().invoke(
        cli.app,
        ["discover-upcoming", "--target-date", "2026-10-16"],
    )

    assert result.exit_code == 2
    assert "Upcoming 조회 대상 설정을 읽지 못했습니다." in result.output


def _candidate_discovery(
    *,
    completed_at: datetime,
    event_id: str | None = "EVENT-A",
) -> LeagueUpcomingDiscovery:
    events = []
    if event_id is not None:
        scheduled_at = datetime(2026, 10, 18, 1, 5, tzinfo=UTC)
        events.append(
            DiscoveredUpcomingEvent(
                event_id=event_id,
                sport_id="16",
                sport_code="baseball",
                time_status="0",
                scheduled_at_utc=scheduled_at,
                scheduled_at_kst=scheduled_at.astimezone(KST),
                league=UpcomingLeague(
                    id="225",
                    name="MLB",
                    country_code="us",
                ),
                home=UpcomingParticipant(id="H", name="Home"),
                away=UpcomingParticipant(id="A", name="Away"),
                source_capture_metadata_file_path="metadata.json",
                result_index=0,
            )
        )

    return LeagueUpcomingDiscovery(
        discovery_run_id="2026-10-18T10-00-00_KST",
        status="completed",
        completed_at=completed_at,
        target_date=date(2026, 10, 18),
        target=_discovery_target("225", "mlb"),
        capture_metadata_file_path="metadata.json",
        events=events,
        failure=None,
    )


def _candidate_event(
    *,
    event_id: str,
    scheduled_at: datetime,
) -> DiscoveredUpcomingEvent:
    return DiscoveredUpcomingEvent(
        event_id=event_id,
        sport_id="16",
        sport_code="baseball",
        time_status="0",
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
    *,
    fallbacks: list[LeagueDiscoveryFallback] | None = None,
) -> LatestLeagueDiscoveries:
    return LatestLeagueDiscoveries(
        selected=selected,
        fallbacks=fallbacks or [],
        unavailable=[],
        load_failures=[],
    )


def test_upcoming_candidates_prints_events_from_saved_discoveries(monkeypatch) -> None:
    now = datetime(2026, 10, 18, 1, tzinfo=UTC)
    path = Path("data/discoveries/mlb.json")
    loaded = LoadedLeagueDiscovery(
        file_path=path,
        discovery=_candidate_discovery(completed_at=now - timedelta(minutes=1)),
    )
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

    result = CliRunner().invoke(
        cli.app,
        [
            "upcoming-candidates",
            "--within-minutes",
            "10",
            "--sport-code",
            "baseball",
            "--league-labels",
            "mlb",
        ],
    )

    assert result.exit_code == 0
    assert "후보 경기: 1개" in result.output
    assert "이벤트 ID: EVENT-A" in result.output
    assert "Home vs Away" in result.output
    assert "남은 시간: 5분 0초" in result.output
    assert "BETS Upcoming API를 호출합니다" not in result.output


def test_upcoming_candidates_returns_zero_when_no_event_is_in_window(
    monkeypatch,
) -> None:
    now = datetime(2026, 10, 18, 1, tzinfo=UTC)
    path = Path("data/discoveries/mlb.json")
    loaded = LoadedLeagueDiscovery(
        file_path=path,
        discovery=_candidate_discovery(
            completed_at=now - timedelta(minutes=1),
            event_id=None,
        ),
    )
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

    result = CliRunner().invoke(cli.app, ["upcoming-candidates"])

    assert result.exit_code == 0
    assert "후보 경기: 0개" in result.output


def test_upcoming_candidates_exits_with_one_without_usable_discovery(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "find_league_upcoming_discovery_paths",
        list,
    )
    monkeypatch.setattr(
        cli,
        "resolve_latest_league_discoveries",
        lambda _paths: _latest_discoveries([]),
    )

    result = CliRunner().invoke(cli.app, ["upcoming-candidates"])

    assert result.exit_code == 1
    assert "사용 가능한 리그 Discovery가 없습니다." in result.output


def test_upcoming_candidates_rejects_empty_league_label_filter() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["upcoming-candidates", "--league-labels", "mlb,"],
    )

    assert result.exit_code == 2
    assert "후보 조회 필터가 올바르지 않습니다." in result.output


def test_watch_upcoming_batches_candidates_and_waits_between_cycles(
    monkeypatch,
) -> None:
    now = datetime(2026, 10, 18, 1, tzinfo=UTC)
    path = Path("data/discoveries/mlb.json")
    event_ids = [f"EVENT-{index:02}" for index in range(11)]
    discovery = _candidate_discovery(
        completed_at=now - timedelta(minutes=1),
        event_id=None,
    ).model_copy(
        update={
            "events": [
                _candidate_event(
                    event_id=event_id,
                    scheduled_at=now + timedelta(minutes=5),
                )
                for event_id in event_ids
            ]
        }
    )
    loaded = LoadedLeagueDiscovery(file_path=path, discovery=discovery)
    captured_batches: list[list[str]] = []
    sleep_calls: list[float] = []

    def capture_event_view(**kwargs):
        captured_batches.append(kwargs["requested_event_ids"])
        return SimpleNamespace(
            response=httpx.Response(200, json={"results": []}),
            raw_file_path=Path("data/raw/capture.json"),
            metadata_file_path=Path("data/metadata/capture.json"),
            metadata=SimpleNamespace(
                response_analysis_status="completed",
                captured_at=now,
            ),
            observation_save_failures=[],
            event_observations=[],
        )

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
    monkeypatch.setattr(cli, "capture_event_view", capture_event_view)
    monkeypatch.setattr(cli.time, "sleep", sleep_calls.append)

    result = CliRunner().invoke(
        cli.app,
        [
            "watch-upcoming",
            "--within-minutes",
            "10",
            "--interval",
            "7",
            "--max-cycles",
            "2",
        ],
    )

    expected_batches = [event_ids[:10], event_ids[10:]]
    assert result.exit_code == 0
    assert captured_batches == [*expected_batches, *expected_batches]
    assert sleep_calls == [7]
    assert "수집 후보 경기: 11개" in result.output
    assert "Event View 요청 배치: 2개" in result.output
    assert "수집 주기: 2회" in result.output
    assert "API 호출: 4회 / 저장: 4개" in result.output


def test_watch_upcoming_returns_without_api_settings_when_no_candidate(
    monkeypatch,
) -> None:
    now = datetime(2026, 10, 18, 1, tzinfo=UTC)
    path = Path("data/discoveries/mlb.json")
    loaded = LoadedLeagueDiscovery(
        file_path=path,
        discovery=_candidate_discovery(
            completed_at=now - timedelta(minutes=1),
            event_id=None,
        ),
    )

    def fail_to_load_settings():
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

    result = CliRunner().invoke(
        cli.app,
        ["watch-upcoming", "--max-cycles", "1"],
    )

    assert result.exit_code == 0
    assert "수집 후보 경기: 0개" in result.output
    assert "현재 수집할 예정 경기 후보가 없습니다." in result.output


def test_watch_upcoming_continues_with_next_batch_after_storage_failure(
    monkeypatch,
) -> None:
    now = datetime(2026, 10, 18, 1, tzinfo=UTC)
    path = Path("data/discoveries/mlb.json")
    event_ids = [f"EVENT-{index:02}" for index in range(11)]
    discovery = _candidate_discovery(
        completed_at=now - timedelta(minutes=1),
        event_id=None,
    ).model_copy(
        update={
            "events": [
                _candidate_event(
                    event_id=event_id,
                    scheduled_at=now + timedelta(minutes=5),
                )
                for event_id in event_ids
            ]
        }
    )
    loaded = LoadedLeagueDiscovery(file_path=path, discovery=discovery)
    captured_batches: list[list[str]] = []

    def capture_event_view(**kwargs):
        requested_event_ids = kwargs["requested_event_ids"]
        captured_batches.append(requested_event_ids)
        if len(captured_batches) == 1:
            raise OSError("disk full")
        return SimpleNamespace(
            response=httpx.Response(200, json={"results": []}),
            raw_file_path=Path("data/raw/capture.json"),
            metadata_file_path=Path("data/metadata/capture.json"),
            metadata=SimpleNamespace(
                response_analysis_status="completed",
                captured_at=now,
            ),
            observation_save_failures=[],
            event_observations=[],
        )

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
    monkeypatch.setattr(cli, "capture_event_view", capture_event_view)

    result = CliRunner().invoke(
        cli.app,
        ["watch-upcoming", "--max-cycles", "1"],
    )

    assert result.exit_code == 0
    assert captured_batches == [event_ids[:10], event_ids[10:]]
    assert "파일 저장에 실패했습니다." in result.output
    assert "API 호출: 2회 / 저장: 1개" in result.output
