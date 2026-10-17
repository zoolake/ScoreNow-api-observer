from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import SecretStr
from typer.testing import CliRunner

from scorenow_api_observer import cli
from scorenow_api_observer.upcoming.models import (
    LeagueUpcomingDiscovery,
    UpcomingDiscoveryFailure,
    UpcomingDiscoveryRun,
    UpcomingDiscoveryTarget,
)
from scorenow_api_observer.upcoming.targets import UpcomingTarget


class _FakeSettings:
    bets_api_base_url = "https://example.test"
    bets_api_token = SecretStr("test-token")


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
