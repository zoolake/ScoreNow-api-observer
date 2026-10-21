from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from scorenow_api_observer.event_odds import collector
from scorenow_api_observer.event_odds.collector import collect_event_odds
from scorenow_api_observer.event_odds.models import OddsSnapshotMetadata


def _clock(count: int) -> Callable[[], datetime]:
    start = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    values = iter(start + timedelta(seconds=index) for index in range(count))
    return values.__next__


def _valid_response(*, market_key: str = "16_1") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "success": 1,
            "results": {
                "stats": {},
                "odds": {market_key: [{"id": "ODDS-1", "home_od": "1.90"}]},
            },
        },
        headers={"content-type": "application/json"},
    )


def test_collect_event_odds_saves_each_event_and_returns_completed_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requested_event_ids: list[str] = []

    def get_event_odds(**kwargs: object) -> httpx.Response:
        requested_event_ids.append(str(kwargs["event_id"]))
        return _valid_response()

    monkeypatch.setattr(collector, "get_event_odds", get_event_odds)

    result = collect_event_odds(
        base_url="https://example.test",
        token="secret",
        event_ids=["A", "B"],
        now=_clock(2),
        raw_base_directory=tmp_path / "raw",
        metadata_base_directory=tmp_path / "metadata",
    )

    assert requested_event_ids == ["A", "B"]
    assert result.status == "completed"
    assert [item.status for item in result.event_results] == [
        "captured",
        "captured",
    ]
    assert [snapshot.metadata.query.event_id for snapshot in result.snapshots] == [
        "A",
        "B",
    ]
    assert result.snapshots[0].metadata.returned_market_keys == ["16_1"]
    assert result.snapshots[0].metadata.record_counts_by_market == {"16_1": 1}
    saved_metadata = result.snapshots[0].metadata_file_path.read_text(encoding="utf-8")
    assert "secret" not in saved_metadata


def test_collect_event_odds_continues_after_request_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requested_event_ids: list[str] = []

    def get_event_odds(**kwargs: object) -> httpx.Response:
        event_id = str(kwargs["event_id"])
        requested_event_ids.append(event_id)
        if event_id == "A":
            request = httpx.Request("GET", "https://example.test")
            raise httpx.ConnectError("connection failed", request=request)
        return _valid_response()

    monkeypatch.setattr(collector, "get_event_odds", get_event_odds)

    result = collect_event_odds(
        base_url="https://example.test",
        token="secret",
        event_ids=["A", "B"],
        now=_clock(1),
        raw_base_directory=tmp_path / "raw",
        metadata_base_directory=tmp_path / "metadata",
    )

    assert requested_event_ids == ["A", "B"]
    assert result.status == "partial"
    assert [item.status for item in result.event_results] == [
        "request_failed",
        "captured",
    ]
    assert [snapshot.metadata.query.event_id for snapshot in result.snapshots] == ["B"]


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (httpx.Response(502, text="bad gateway"), "HttpStatusError"),
        (httpx.Response(200, text="not-json"), "JSONDecodeError"),
        (
            httpx.Response(200, json={"success": 0, "results": {"odds": {}}}),
            "InvalidEventOddsResponseShapeError",
        ),
    ],
)
def test_collect_event_odds_does_not_replace_snapshot_for_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    response: httpx.Response,
    error_type: str,
) -> None:
    existing_raw_path = tmp_path / "raw" / "2026-10-22" / "A.json"
    existing_raw_path.parent.mkdir(parents=True)
    existing_raw_path.write_bytes(b"existing snapshot")
    existing_metadata_path = tmp_path / "metadata" / "2026-10-22" / "A.json"
    existing_metadata_path.parent.mkdir(parents=True)
    existing_metadata_path.write_text("existing metadata", encoding="utf-8")
    monkeypatch.setattr(collector, "get_event_odds", lambda **_kwargs: response)

    result = collect_event_odds(
        base_url="https://example.test",
        token="secret",
        event_ids=["A"],
        now=_clock(1),
        raw_base_directory=tmp_path / "raw",
        metadata_base_directory=tmp_path / "metadata",
    )

    assert result.status == "failed"
    assert result.event_results[0].status == "response_invalid"
    assert result.event_results[0].error_type == error_type
    assert existing_raw_path.read_bytes() == b"existing snapshot"
    assert existing_metadata_path.read_text() == "existing metadata"


def test_collect_event_odds_continues_after_snapshot_storage_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_save = collector.save_event_odds_snapshot

    def save_snapshot(**kwargs: object) -> tuple[Path, Path]:
        metadata = kwargs["metadata"]
        assert isinstance(metadata, OddsSnapshotMetadata)
        if metadata.query.event_id == "A":
            raise OSError("disk full")
        return original_save(**kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(
        collector, "get_event_odds", lambda **_kwargs: _valid_response()
    )
    monkeypatch.setattr(collector, "save_event_odds_snapshot", save_snapshot)

    result = collect_event_odds(
        base_url="https://example.test",
        token="secret",
        event_ids=["A", "B"],
        now=_clock(2),
        raw_base_directory=tmp_path / "raw",
        metadata_base_directory=tmp_path / "metadata",
    )

    assert result.status == "partial"
    assert [item.status for item in result.event_results] == [
        "storage_failed",
        "captured",
    ]
