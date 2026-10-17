from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import SecretStr
from typer.testing import CliRunner

from scorenow_api_observer import cli
from scorenow_api_observer.upcoming_models import (
    UpcomingDiscovery,
    UpcomingDiscoveryFailure,
)
from scorenow_api_observer.upcoming_targets import UpcomingTarget


class _FakeSettings:
    bets_api_base_url = "https://example.test"
    bets_api_token = SecretStr("test-token")


def _result(status: Literal["completed", "partial", "failed"]):
    failure = UpcomingDiscoveryFailure(
        sport_id="16",
        league_id="349",
        league_label="kbo",
        error_type="ConnectError",
        error_message="API 서버에 연결하지 못했습니다.",
    )
    discovery = UpcomingDiscovery(
        discovery_run_id="2026-10-17T00-00-00_KST",
        status=status,
        started_at=datetime(2026, 10, 16, 15, 0, tzinfo=UTC),
        completed_at=datetime(2026, 10, 16, 15, 1, tzinfo=UTC),
        target_date=date(2026, 10, 16),
        requested_targets=[],
        capture_metadata_file_paths=[],
        events=[],
        failures=[] if status == "completed" else [failure],
    )
    return SimpleNamespace(
        discovery=discovery,
        discovery_file_path=Path("data/discoveries/result.json"),
        captures=[] if status == "failed" else [object()],
    )


def test_discover_upcoming_rejects_invalid_target_date() -> None:
    result = CliRunner().invoke(
        cli.app,
        ["discover-upcoming", "--target-date", "20261016"],
    )

    assert result.exit_code == 2
    assert "YYYY-MM-DD" in result.output


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
