from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from scorenow_api_observer.upcoming_models import (
    UpcomingCaptureMetadata,
    UpcomingDiscovery,
    UpcomingRequestQuery,
)
from scorenow_api_observer.upcoming_storage import (
    save_upcoming_capture_metadata,
    save_upcoming_discovery,
    save_upcoming_raw_response,
)


def _metadata(*, captured_at: datetime, raw_file_path: Path) -> UpcomingCaptureMetadata:
    return UpcomingCaptureMetadata(
        discovery_run_id="2026-10-17T01-00-00_KST",
        captured_at=captured_at,
        provider="betsapi",
        endpoint="/v3/events/upcoming",
        http_method="GET",
        query=UpcomingRequestQuery(
            sport_id="16",
            league_id="225",
            day="20261016",
        ),
        response_analysis_status="completed",
        returned_event_ids=[],
        response_issues=[],
        http_status_code=200,
        elapsed_ms=10.0,
        response_size_bytes=2,
        content_type="application/json",
        raw_file_path=str(raw_file_path),
    )


def test_save_upcoming_capture_uses_kst_date_and_readable_file_name(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 10, 16, 16, 55, 15, 999999, tzinfo=UTC)

    raw_path = save_upcoming_raw_response(
        response_body=b"{}",
        captured_at=captured_at,
        league_label="mlb",
        base_directory=tmp_path / "raw",
    )
    metadata = _metadata(captured_at=captured_at, raw_file_path=raw_path)
    metadata_path = save_upcoming_capture_metadata(
        metadata,
        base_directory=tmp_path / "metadata",
    )

    file_name = "mlb_2026-10-17T01-55-15_KST_capture.json"
    assert raw_path == tmp_path / "raw" / "2026-10-17" / file_name
    assert metadata_path == tmp_path / "metadata" / "2026-10-17" / file_name
    assert raw_path.read_bytes() == b"{}"
    assert (
        UpcomingCaptureMetadata.model_validate_json(
            metadata_path.read_text(encoding="utf-8")
        )
        == metadata
    )


def test_save_upcoming_raw_response_does_not_overwrite_existing_file(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    arguments = {
        "captured_at": captured_at,
        "league_label": "kbo",
        "base_directory": tmp_path,
    }
    saved_path = save_upcoming_raw_response(response_body=b"first", **arguments)

    with pytest.raises(FileExistsError):
        save_upcoming_raw_response(response_body=b"second", **arguments)

    assert saved_path.read_bytes() == b"first"


def test_save_upcoming_discovery_uses_utc_target_date_and_run_id(
    tmp_path: Path,
) -> None:
    discovery = UpcomingDiscovery(
        discovery_run_id="2026-10-17T01-00-00_KST",
        status="completed",
        started_at=datetime(2026, 10, 16, 16, 0, tzinfo=UTC),
        completed_at=datetime(2026, 10, 16, 16, 1, tzinfo=UTC),
        target_date=date(2026, 10, 16),
        requested_targets=[],
        capture_metadata_file_paths=[],
        events=[],
        failures=[],
    )

    saved_path = save_upcoming_discovery(discovery, base_directory=tmp_path)

    assert saved_path == (
        tmp_path / "2026-10-16" / "2026-10-17T01-00-00_KST_discovery.json"
    )
    assert UpcomingDiscovery.model_validate_json(saved_path.read_text()) == discovery

    with pytest.raises(FileExistsError):
        save_upcoming_discovery(discovery, base_directory=tmp_path)
