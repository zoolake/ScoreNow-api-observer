from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scorenow_api_observer.upcoming.candidates import (
    LoadedLeagueDiscovery,
    normalize_candidate_sport_code,
    parse_candidate_league_labels,
    resolve_latest_league_discoveries,
    select_upcoming_candidates,
)
from scorenow_api_observer.upcoming.models import (
    DiscoveredUpcomingEvent,
    LeagueUpcomingDiscovery,
    UpcomingDiscoveryFailure,
    UpcomingDiscoveryStatus,
    UpcomingDiscoveryTarget,
    UpcomingLeague,
    UpcomingParticipant,
)

KST = ZoneInfo("Asia/Seoul")


def _event(event_id: str, scheduled_at: datetime) -> DiscoveredUpcomingEvent:
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


def _discovery(
    *,
    completed_at: datetime,
    status: UpcomingDiscoveryStatus = "completed",
    target_date: date = date(2026, 10, 18),
    sport_id: str = "16",
    sport_code: str = "baseball",
    league_id: str = "225",
    league_label: str = "mlb",
    events: list[DiscoveredUpcomingEvent] | None = None,
) -> LeagueUpcomingDiscovery:
    target = UpcomingDiscoveryTarget(
        sport_id=sport_id,
        sport_code=sport_code,
        league_id=league_id,
        league_label=league_label,
    )
    failure = None
    capture_metadata_file_path = "metadata.json"
    if status == "failed":
        failure = UpcomingDiscoveryFailure(
            sport_id=sport_id,
            league_id=league_id,
            league_label=league_label,
            error_type="HttpStatusError",
            error_message="API가 HTTP 502 오류를 반환했습니다.",
        )
        capture_metadata_file_path = None

    return LeagueUpcomingDiscovery(
        discovery_run_id=completed_at.strftime("%Y-%m-%dT%H-%M-%S_KST"),
        status=status,
        completed_at=completed_at,
        target_date=target_date,
        target=target,
        capture_metadata_file_path=capture_metadata_file_path,
        events=events or [],
        failure=failure,
    )


def _write_discovery(path: Path, discovery: LeagueUpcomingDiscovery) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(discovery.model_dump_json(), encoding="utf-8")
    return path


def test_resolve_latest_league_discoveries_falls_back_after_latest_failure(
    tmp_path: Path,
) -> None:
    earlier = _write_discovery(
        tmp_path / "earlier.json",
        _discovery(completed_at=datetime(2026, 10, 18, 1, tzinfo=UTC)),
    )
    latest = _write_discovery(
        tmp_path / "latest.json",
        _discovery(
            completed_at=datetime(2026, 10, 18, 2, tzinfo=UTC),
            status="failed",
        ),
    )

    result = resolve_latest_league_discoveries([latest, earlier])

    assert [item.file_path for item in result.selected] == [earlier]
    assert len(result.fallbacks) == 1
    assert result.fallbacks[0].latest_failed.file_path == latest
    assert result.fallbacks[0].selected.file_path == earlier
    assert result.unavailable == []


def test_resolve_latest_league_discoveries_uses_partial_as_usable(
    tmp_path: Path,
) -> None:
    earlier = _write_discovery(
        tmp_path / "earlier.json",
        _discovery(completed_at=datetime(2026, 10, 18, 1, tzinfo=UTC)),
    )
    latest = _write_discovery(
        tmp_path / "latest.json",
        _discovery(
            completed_at=datetime(2026, 10, 18, 2, tzinfo=UTC),
            status="partial",
        ),
    )

    result = resolve_latest_league_discoveries([earlier, latest])

    assert [item.file_path for item in result.selected] == [latest]
    assert result.fallbacks == []


def test_resolve_latest_league_discoveries_keeps_target_dates_separate(
    tmp_path: Path,
) -> None:
    first_date = _write_discovery(
        tmp_path / "first.json",
        _discovery(
            completed_at=datetime(2026, 10, 18, 1, tzinfo=UTC),
            target_date=date(2026, 10, 17),
        ),
    )
    second_date = _write_discovery(
        tmp_path / "second.json",
        _discovery(
            completed_at=datetime(2026, 10, 18, 2, tzinfo=UTC),
            target_date=date(2026, 10, 18),
        ),
    )

    result = resolve_latest_league_discoveries([second_date, first_date])

    assert [item.file_path for item in result.selected] == [
        first_date,
        second_date,
    ]


def test_resolve_latest_league_discoveries_continues_after_invalid_file(
    tmp_path: Path,
) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("not-json", encoding="utf-8")
    failed_path = _write_discovery(
        tmp_path / "failed.json",
        _discovery(
            completed_at=datetime(2026, 10, 18, 2, tzinfo=UTC),
            status="failed",
        ),
    )

    result = resolve_latest_league_discoveries([invalid_path, failed_path])

    assert result.selected == []
    assert len(result.unavailable) == 1
    assert result.unavailable[0].latest_attempt.file_path == failed_path
    assert len(result.load_failures) == 1
    assert result.load_failures[0].file_path == invalid_path


def test_select_upcoming_candidates_uses_inclusive_time_window() -> None:
    now = datetime(2026, 10, 18, 1, tzinfo=UTC)
    discovery = _discovery(
        completed_at=now - timedelta(minutes=1),
        events=[
            _event("PAST", now - timedelta(seconds=1)),
            _event("NOW", now),
            _event("END", now + timedelta(minutes=10)),
            _event("LATER", now + timedelta(minutes=10, seconds=1)),
        ],
    )

    result = select_upcoming_candidates(
        [LoadedLeagueDiscovery(Path("discovery.json"), discovery)],
        now=now,
        within_minutes=10,
    )

    assert [candidate.event.event_id for candidate in result.candidates] == [
        "NOW",
        "END",
    ]


def test_select_upcoming_candidates_filters_and_deduplicates_by_event_id() -> None:
    now = datetime(2026, 10, 18, 1, tzinfo=UTC)
    earlier = _discovery(
        completed_at=now - timedelta(minutes=2),
        events=[_event("A", now + timedelta(minutes=5))],
    )
    latest = _discovery(
        completed_at=now - timedelta(minutes=1),
        target_date=date(2026, 10, 19),
        events=[_event("A", now + timedelta(minutes=4))],
    )
    football = _discovery(
        completed_at=now,
        sport_id="1",
        sport_code="football",
        league_id="94",
        league_label="premier-league",
        events=[_event("B", now + timedelta(minutes=3))],
    )

    result = select_upcoming_candidates(
        [
            LoadedLeagueDiscovery(Path("earlier.json"), earlier),
            LoadedLeagueDiscovery(Path("latest.json"), latest),
            LoadedLeagueDiscovery(Path("football.json"), football),
        ],
        now=now,
        within_minutes=10,
        sport_code="baseball",
        league_labels=frozenset({"mlb"}),
    )

    assert [candidate.event.event_id for candidate in result.candidates] == ["A"]
    assert result.candidates[0].discovery_file_path == Path("latest.json")
    assert result.duplicate_event_ids == ["A"]


def test_candidate_filters_trim_and_deduplicate_values() -> None:
    assert normalize_candidate_sport_code(" baseball ") == "baseball"
    assert parse_candidate_league_labels(" mlb,kbo,mlb ") == frozenset({"mlb", "kbo"})
    assert normalize_candidate_sport_code(None) is None
    assert parse_candidate_league_labels(None) is None
