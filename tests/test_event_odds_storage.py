from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scorenow_api_observer.event_odds import storage
from scorenow_api_observer.event_odds.models import (
    OddsRequestQuery,
    OddsSnapshotMetadata,
)
from scorenow_api_observer.event_odds.storage import (
    save_event_odds_raw_response,
    save_event_odds_snapshot,
    save_event_odds_snapshot_metadata,
)


def _metadata(*, captured_at: datetime, raw_file_path: str) -> OddsSnapshotMetadata:
    return OddsSnapshotMetadata(
        captured_at=captured_at,
        provider="betsapi",
        endpoint="/v2/event/odds",
        http_method="GET",
        query=OddsRequestQuery(event_id="EVENT-A", odds_market="1,2,3"),
        returned_market_keys=["16_1"],
        record_counts_by_market={"16_1": 2},
        http_status_code=200,
        elapsed_ms=10.5,
        response_size_bytes=100,
        content_type="application/json",
        raw_file_path=raw_file_path,
    )


def test_save_raw_response_uses_utc_date_and_overwrites_daily_snapshot(
    tmp_path: Path,
) -> None:
    captured_at_kst = datetime(
        2026,
        10,
        23,
        0,
        30,
        tzinfo=ZoneInfo("Asia/Seoul"),
    )

    first_path = save_event_odds_raw_response(
        response_body=b"first",
        event_id="EVENT-A",
        captured_at=captured_at_kst,
        base_directory=tmp_path,
    )
    second_path = save_event_odds_raw_response(
        response_body=b"second",
        event_id="EVENT-A",
        captured_at=captured_at_kst,
        base_directory=tmp_path,
    )

    assert first_path == tmp_path / "2026-10-22" / "EVENT-A.json"
    assert second_path == first_path
    assert second_path.read_bytes() == b"second"
    assert not list(second_path.parent.glob("*.tmp"))


def test_save_snapshot_metadata_overwrites_daily_event_metadata(
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    first = _metadata(captured_at=captured_at, raw_file_path="raw/EVENT-A.json")
    second = first.model_copy(
        update={
            "record_counts_by_market": {"16_1": 3},
        }
    )

    saved_path = save_event_odds_snapshot_metadata(first, base_directory=tmp_path)
    overwritten_path = save_event_odds_snapshot_metadata(
        second,
        base_directory=tmp_path,
    )

    assert saved_path == tmp_path / "2026-10-22" / "EVENT-A.json"
    assert overwritten_path == saved_path
    assert OddsSnapshotMetadata.model_validate_json(saved_path.read_text()) == second


def test_save_snapshot_restores_previous_raw_when_metadata_save_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured_at = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    raw_directory = tmp_path / "raw"
    metadata_directory = tmp_path / "metadata"
    previous_metadata = _metadata(
        captured_at=captured_at,
        raw_file_path=str(raw_directory / "2026-10-22" / "EVENT-A.json"),
    )
    raw_file_path = save_event_odds_raw_response(
        response_body=b"previous raw",
        event_id="EVENT-A",
        captured_at=captured_at,
        base_directory=raw_directory,
    )
    metadata_file_path = save_event_odds_snapshot_metadata(
        previous_metadata,
        base_directory=metadata_directory,
    )

    def fail_to_save_metadata(*_args: object, **_kwargs: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(
        storage,
        "save_event_odds_snapshot_metadata",
        fail_to_save_metadata,
    )

    with pytest.raises(OSError, match="disk full"):
        save_event_odds_snapshot(
            response_body=b"new raw",
            metadata=previous_metadata.model_copy(
                update={"record_counts_by_market": {"16_1": 3}}
            ),
            raw_base_directory=raw_directory,
            metadata_base_directory=metadata_directory,
        )

    assert raw_file_path.read_bytes() == b"previous raw"
    assert (
        OddsSnapshotMetadata.model_validate_json(metadata_file_path.read_text())
        == previous_metadata
    )
