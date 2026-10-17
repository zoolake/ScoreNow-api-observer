from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from scorenow_api_observer.upcoming.models import (
    LeagueUpcomingDiscovery,
    UpcomingDiscoveryFailure,
    UpcomingDiscoveryRun,
    UpcomingDiscoveryTarget,
)


def _target() -> UpcomingDiscoveryTarget:
    return UpcomingDiscoveryTarget(
        sport_id="16",
        sport_code="baseball",
        league_id="225",
        league_label="mlb",
    )


def _failure() -> UpcomingDiscoveryFailure:
    return UpcomingDiscoveryFailure(
        sport_id="16",
        league_id="225",
        league_label="mlb",
        error_type="ConnectError",
        error_message="API 서버에 연결하지 못했습니다.",
    )


def test_league_discovery_requires_failure_for_failed_status() -> None:
    with pytest.raises(ValidationError, match="실패 내역이 필요"):
        LeagueUpcomingDiscovery(
            discovery_run_id="run",
            status="failed",
            completed_at=datetime(2026, 10, 16, tzinfo=UTC),
            target_date=date(2026, 10, 16),
            target=_target(),
            capture_metadata_file_path=None,
            events=[],
            failure=None,
        )


def test_league_discovery_rejects_failure_on_usable_status() -> None:
    with pytest.raises(ValidationError, match="실패 내역을 둘 수 없습니다"):
        LeagueUpcomingDiscovery(
            discovery_run_id="run",
            status="completed",
            completed_at=datetime(2026, 10, 16, tzinfo=UTC),
            target_date=date(2026, 10, 16),
            target=_target(),
            capture_metadata_file_path="metadata.json",
            events=[],
            failure=_failure(),
        )


def test_discovery_run_requires_one_file_per_requested_target() -> None:
    with pytest.raises(ValidationError, match="요청 대상 수"):
        UpcomingDiscoveryRun(
            discovery_run_id="run",
            status="completed",
            started_at=datetime(2026, 10, 16, tzinfo=UTC),
            completed_at=datetime(2026, 10, 16, tzinfo=UTC),
            target_date=date(2026, 10, 16),
            requested_targets=[_target()],
            league_discovery_file_paths=[],
        )
