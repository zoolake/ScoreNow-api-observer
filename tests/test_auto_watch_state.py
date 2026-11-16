from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scorenow_api_observer.auto_watch.models import AutoWatchState
from scorenow_api_observer.auto_watch.state import (
    add_auto_watch_candidates,
    build_event_watch_states,
    load_auto_watch_state,
    new_auto_watch_state,
    remove_completed_auto_watch_events,
    save_auto_watch_state,
    sync_event_watch_states,
)
from scorenow_api_observer.upcoming.candidates import UpcomingCandidate
from scorenow_api_observer.upcoming.models import (
    DiscoveredUpcomingEvent,
    UpcomingLeague,
    UpcomingParticipant,
)

KST = ZoneInfo("Asia/Seoul")


def _candidate(*, event_id: str, scheduled_at: datetime) -> UpcomingCandidate:
    return UpcomingCandidate(
        event=DiscoveredUpcomingEvent(
            event_id=event_id,
            sport_id="16",
            sport_code="baseball",
            time_status="0",
            scheduled_at_utc=scheduled_at,
            scheduled_at_kst=scheduled_at.astimezone(KST),
            league=UpcomingLeague(id="349", name="KBO", country_code="kr"),
            home=UpcomingParticipant(id="H", name="Home"),
            away=UpcomingParticipant(id="A", name="Away"),
            source_capture_metadata_file_path="metadata.json",
            result_index=0,
        ),
        league_label="kbo",
        discovery_status="completed",
        discovery_completed_at=scheduled_at - timedelta(minutes=1),
        discovery_file_path=Path("discovery.json"),
    )


def test_auto_watch_state_persists_candidates_and_finish_detection(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 13, 1, tzinfo=UTC)
    state = new_auto_watch_state(now=now)

    added_event_ids = add_auto_watch_candidates(
        state=state,
        candidates=[
            _candidate(event_id="B", scheduled_at=now + timedelta(minutes=5)),
            _candidate(event_id="A", scheduled_at=now + timedelta(minutes=3)),
            _candidate(event_id="A", scheduled_at=now + timedelta(minutes=3)),
        ],
        now=now,
    )

    assert added_event_ids == ["B", "A"]
    assert [event.event_id for event in state.active_events] == ["A", "B"]

    watch_states = {
        watch_state.event_id: watch_state
        for watch_state in build_event_watch_states(state)
    }
    watch_states["A"].finished_detected_at = now + timedelta(minutes=10)
    assert sync_event_watch_states(
        state=state,
        watch_states=watch_states,
        now=now + timedelta(minutes=10),
    )

    state_path = tmp_path / "state.json"
    save_auto_watch_state(state, state_path)
    loaded = load_auto_watch_state(state_path)

    assert loaded is not None
    assert loaded.active_events[0].event_id == "A"
    assert loaded.active_events[0].finished_detected_at == now + timedelta(minutes=10)

    completed_event_ids = remove_completed_auto_watch_events(
        state=loaded,
        now=now + timedelta(minutes=25),
    )

    assert completed_event_ids == ["A"]
    assert [event.event_id for event in loaded.active_events] == ["B"]


def test_load_auto_watch_state_returns_none_when_file_does_not_exist(
    tmp_path: Path,
) -> None:
    assert load_auto_watch_state(tmp_path / "missing.json") is None


def test_load_auto_watch_state_upgrades_legacy_schema(tmp_path: Path) -> None:
    now = datetime(2026, 11, 13, 1, tzinfo=UTC)
    state_path = tmp_path / "state.json"
    save_auto_watch_state(
        AutoWatchState(schema_version=1, updated_at=now, active_events=[]),
        state_path,
    )

    loaded = load_auto_watch_state(state_path)

    assert loaded is not None
    assert loaded.schema_version == 3


def test_load_auto_watch_state_migrates_legacy_policy_group(tmp_path: Path) -> None:
    now = datetime(2026, 11, 13, 1, tzinfo=UTC)
    state_path = tmp_path / "state.json"
    state_path.write_text(
        f"""
{{
  "schema_version": 2,
  "updated_at": "{now.isoformat()}",
  "active_events": [
    {{
      "event_id": "A",
      "sport_code": "baseball",
      "league_id": "349",
      "league_label": "kbo",
      "scheduled_at_utc": "{now.isoformat()}",
      "added_at": "{now.isoformat()}",
      "last_time_status": 7,
      "status_policy_group": "resumable",
      "status_policy_started_at": "{now.isoformat()}"
    }}
  ]
}}
""".lstrip(),
        encoding="utf-8",
    )

    loaded = load_auto_watch_state(state_path)

    assert loaded is not None
    assert loaded.schema_version == 3
    assert loaded.active_events[0].status_policy_group == "temporarily_stopped"
