import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from scorenow_api_observer.upcoming import discovery as upcoming_discovery
from scorenow_api_observer.upcoming.models import (
    LeagueUpcomingDiscovery,
    UpcomingDiscoveryRun,
)
from scorenow_api_observer.upcoming.targets import UpcomingTarget


def _target(
    league_id: str,
    league_label: str,
) -> UpcomingTarget:
    return UpcomingTarget("16", "baseball", league_id, league_label)


def _event(
    event_id: str,
    *,
    league_id: str,
    timestamp: int,
) -> dict[str, object]:
    return {
        "id": event_id,
        "sport_id": "16",
        "time": str(timestamp),
        "time_status": "0",
        "league": {"id": league_id, "name": league_id, "cc": "us"},
        "home": {"id": f"{event_id}-home", "name": "Home"},
        "away": {"id": f"{event_id}-away", "name": "Away"},
    }


def _response(
    status_code: int,
    body: dict[str, object] | bytes,
) -> httpx.Response:
    if isinstance(body, bytes):
        content = body
    else:
        content = json.dumps(body).encode()
    response = httpx.Response(
        status_code,
        content=content,
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "https://example.test/v3/events/upcoming"),
    )
    response.elapsed = timedelta(milliseconds=12.34)
    return response


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def test_discover_upcoming_events_saves_run_and_each_league(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    targets = [_target("225", "mlb"), _target("349", "kbo")]
    responses = iter(
        [
            _response(
                200,
                {
                    "results": [_event("LATE", league_id="225", timestamp=200)],
                    "pager": {"total": 1},
                },
            ),
            _response(
                200,
                {
                    "results": [_event("EARLY", league_id="349", timestamp=100)],
                    "pager": {"total": 1},
                },
            ),
        ]
    )
    requested_targets: list[tuple[str, str]] = []

    def get_upcoming_events(**kwargs: object) -> httpx.Response:
        requested_targets.append((str(kwargs["sport_id"]), str(kwargs["league_id"])))
        return next(responses)

    monkeypatch.setattr(upcoming_discovery, "get_upcoming_events", get_upcoming_events)
    start = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

    result = upcoming_discovery.discover_upcoming_events(
        base_url="https://example.test",
        token="secret",
        target_date=date(2026, 10, 16),
        targets=targets,
        now=_clock(
            start,
            start + timedelta(seconds=1),
            start + timedelta(seconds=2),
            start + timedelta(seconds=3),
        ),
        raw_base_directory=tmp_path / "raw",
        metadata_base_directory=tmp_path / "metadata",
        discovery_base_directory=tmp_path / "discoveries",
    )

    assert requested_targets == [("16", "225"), ("16", "349")]
    assert result.run.status == "completed"
    assert [item.target.league_label for item in result.league_discoveries] == [
        "mlb",
        "kbo",
    ]
    assert [
        event.event_id for item in result.league_discoveries for event in item.events
    ] == ["LATE", "EARLY"]
    assert len(result.captures) == 2
    assert len(result.run.league_discovery_file_paths) == 2
    assert result.run_file_path.exists()
    assert (
        UpcomingDiscoveryRun.model_validate_json(result.run_file_path.read_text())
        == result.run
    )
    for discovery, file_path in zip(
        result.league_discoveries,
        result.league_discovery_file_paths,
        strict=True,
    ):
        assert (
            LeagueUpcomingDiscovery.model_validate_json(file_path.read_text())
            == discovery
        )
    assert all(
        "secret" not in path.read_text(encoding="utf-8")
        for path in (tmp_path / "metadata").rglob("*.json")
    )


def test_discover_upcoming_events_saves_failed_league_and_partial_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    targets = [_target("225", "mlb"), _target("349", "kbo")]
    call_count = 0

    def get_upcoming_events(**_kwargs: object) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _response(200, {"results": [], "pager": {"total": 0}})
        request = httpx.Request(
            "GET",
            "https://example.test/v3/events/upcoming?token=secret",
        )
        raise httpx.ConnectError("connection failed with secret URL", request=request)

    monkeypatch.setattr(upcoming_discovery, "get_upcoming_events", get_upcoming_events)
    start = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

    result = upcoming_discovery.discover_upcoming_events(
        base_url="https://example.test",
        token="secret",
        target_date=date(2026, 10, 16),
        targets=targets,
        now=_clock(
            start,
            start + timedelta(seconds=1),
            start + timedelta(seconds=2),
            start + timedelta(seconds=3),
        ),
        raw_base_directory=tmp_path / "raw",
        metadata_base_directory=tmp_path / "metadata",
        discovery_base_directory=tmp_path / "discoveries",
    )

    assert result.run.status == "partial"
    assert len(result.captures) == 1
    assert [item.status for item in result.league_discoveries] == [
        "completed",
        "failed",
    ]
    failure = result.league_discoveries[1].failure
    assert failure is not None
    assert failure.league_label == "kbo"
    assert failure.error_type == "ConnectError"
    assert failure.error_message == "API 서버에 연결하지 못했습니다."
    assert "secret" not in result.run_file_path.read_text(encoding="utf-8")


def test_discover_upcoming_events_marks_response_issue_as_partial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        upcoming_discovery,
        "get_upcoming_events",
        lambda **_kwargs: _response(
            200,
            {"results": [], "pager": {"total": 3}},
        ),
    )
    start = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

    result = upcoming_discovery.discover_upcoming_events(
        base_url="https://example.test",
        token="secret",
        target_date=date(2026, 10, 16),
        targets=[_target("225", "mlb")],
        now=_clock(start, start + timedelta(seconds=1), start + timedelta(seconds=2)),
        raw_base_directory=tmp_path / "raw",
        metadata_base_directory=tmp_path / "metadata",
        discovery_base_directory=tmp_path / "discoveries",
    )

    assert result.run.status == "partial"
    assert result.league_discoveries[0].status == "partial"
    assert result.league_discoveries[0].failure is None
    assert [issue.code for issue in result.captures[0].metadata.response_issues] == [
        "pagination_required"
    ]


def test_discover_upcoming_events_saves_skipped_leagues_after_fatal_http_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    call_count = 0

    def get_upcoming_events(**_kwargs: object) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _response(401, {"success": 0, "error": "invalid token"})

    monkeypatch.setattr(upcoming_discovery, "get_upcoming_events", get_upcoming_events)
    start = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

    result = upcoming_discovery.discover_upcoming_events(
        base_url="https://example.test",
        token="secret",
        target_date=date(2026, 10, 16),
        targets=[_target("225", "mlb"), _target("349", "kbo")],
        now=_clock(start, start + timedelta(seconds=1), start + timedelta(seconds=2)),
        raw_base_directory=tmp_path / "raw",
        metadata_base_directory=tmp_path / "metadata",
        discovery_base_directory=tmp_path / "discoveries",
    )

    assert call_count == 1
    assert result.run.status == "failed"
    assert [
        item.failure.error_type
        for item in result.league_discoveries
        if item.failure is not None
    ] == ["HttpStatusError", "SkippedTargetError"]
    assert len(result.league_discovery_file_paths) == 2
    assert all(path.exists() for path in result.league_discovery_file_paths)


def test_discover_upcoming_events_is_failed_when_every_request_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail(**_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(upcoming_discovery, "get_upcoming_events", fail)
    start = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

    result = upcoming_discovery.discover_upcoming_events(
        base_url="https://example.test",
        token="secret",
        target_date=date(2026, 10, 16),
        targets=[_target("225", "mlb"), _target("349", "kbo")],
        now=_clock(
            start,
            start + timedelta(seconds=1),
            start + timedelta(seconds=2),
            start + timedelta(seconds=3),
        ),
        raw_base_directory=tmp_path / "raw",
        metadata_base_directory=tmp_path / "metadata",
        discovery_base_directory=tmp_path / "discoveries",
    )

    assert result.run.status == "failed"
    assert [item.status for item in result.league_discoveries] == [
        "failed",
        "failed",
    ]
    assert result.run_file_path.exists()
