from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from scorenow_api_observer import cli
from scorenow_api_observer.auto_watch import state as state_storage
from scorenow_api_observer.auto_watch.config import load_auto_watch_config
from scorenow_api_observer.auto_watch.models import (
    AutoWatchActiveEvent,
    AutoWatchState,
)
from scorenow_api_observer.settings import Settings
from scorenow_api_observer.upcoming.targets import UpcomingTarget


class _FakeSecret:
    def get_secret_value(self) -> str:
        return "test-token"


class _FakeSettings:
    bets_api_base_url = "https://example.test"
    bets_api_token = _FakeSecret()


def _active_event(
    *,
    event_id: str,
    sport_code: str,
    now: datetime,
) -> AutoWatchActiveEvent:
    return AutoWatchActiveEvent(
        event_id=event_id,
        sport_code=sport_code,
        league_id="94" if sport_code == "football" else "349",
        league_label="premier-league" if sport_code == "football" else "kbo",
        scheduled_at_utc=now + timedelta(minutes=5),
        added_at=now,
    )


def _capture_result(status_code: int, now: datetime):
    response = httpx.Response(
        status_code,
        json={"success": 1, "results": []},
        request=httpx.Request("GET", "https://example.test/v1/event/view"),
    )
    response.elapsed = timedelta(milliseconds=1)
    return SimpleNamespace(
        response=response,
        raw_file_path=Path("raw.json"),
        metadata_file_path=Path("metadata.json"),
        metadata=SimpleNamespace(
            response_analysis_status="completed",
            captured_at=now,
        ),
        observation_save_failures=[],
        event_observations=[],
    )


def _patch_storage(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(
        cli,
        "save_auto_watch_state",
        lambda state: state_storage.save_auto_watch_state(state, state_path),
    )


def test_auto_watch_start_summary_is_grouped_and_readable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli._print_auto_watch_start_summary(
        enabled_target_count=33,
        active_event_count=1,
        within_minutes=10,
        interval_seconds=300,
        candidate_check_interval_seconds=300,
        max_cycles=None,
    )

    output = capsys.readouterr().out
    assert "🤖 Auto-watch를 시작합니다." in output
    assert "[실행 설정]" in output
    assert "  • 수집 대상 리그: 33개" in output
    assert "  • Event View 수집 간격: 300초" in output
    assert "  • 실행 횟수 제한: 제한 없음" in output
    assert "[저장 파일]" in output
    assert "저장된 Discovery만 확인합니다" in output


def test_auto_watch_candidate_summary_uses_multiple_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli._print_auto_watch_candidate_summary(
        target_dates=(date(2026, 11, 16),),
        discovery_file_count=43,
        selected_discovery_count=43,
        candidate_count=0,
        added_event_count=0,
        within_minutes=10,
    )

    assert capsys.readouterr().out == (
        "\n"
        "🔎 후보 확인 완료 — 대상 UTC 날짜: 2026-11-16\n"
        "  • 확인한 Discovery 파일: 43개\n"
        "  • 실제 사용한 최신 Discovery: 43개\n"
        "  • 10분 안에 시작할 경기: 0개\n"
        "  • 새로 추가한 경기: 0개\n"
    )


def test_auto_watch_refresh_scans_only_dates_touched_by_candidate_window(
    monkeypatch,
) -> None:
    now = datetime(2026, 11, 13, 23, 55, tzinfo=UTC)
    state = AutoWatchState(updated_at=now, active_events=[])
    received_target_dates: tuple[date, ...] | None = None
    received_target_keys: tuple[tuple[str, str, str], ...] | None = None

    def find_paths(*, target_dates, target_keys):
        nonlocal received_target_dates, received_target_keys
        received_target_dates = target_dates
        received_target_keys = tuple(target_keys)
        return []

    monkeypatch.setattr(
        cli,
        "load_upcoming_targets",
        lambda: [
            UpcomingTarget("16", "baseball", "349", "kbo", True),
            UpcomingTarget("1", "football", "6388", "uefa-super-cup", False),
        ],
    )
    monkeypatch.setattr(cli, "find_league_upcoming_discovery_paths", find_paths)

    added_event_ids = cli._refresh_auto_watch_candidates(
        state=state,
        now=now,
        within_minutes=10,
    )

    assert added_event_ids == []
    assert received_target_dates == (
        now.date(),
        (now + timedelta(days=1)).date(),
    )
    assert received_target_keys == (("baseball", "349", "kbo"),)


def test_auto_watch_detects_new_events_while_running_and_counts_mixed_request(
    monkeypatch,
    tmp_path: Path,
) -> None:
    current_time = datetime(2026, 11, 13, 1, tzinfo=UTC)
    state = AutoWatchState(updated_at=current_time, active_events=[])
    refresh_count = 0
    captured_batches: list[list[str]] = []

    def refresh_candidates(*, state, now, within_minutes):
        nonlocal refresh_count
        refresh_count += 1
        if refresh_count == 1:
            state.active_events.append(
                _active_event(event_id="B", sport_code="baseball", now=now)
            )
            state.updated_at = now
            return ["B"]
        state.active_events.append(
            _active_event(event_id="F", sport_code="football", now=now)
        )
        state.updated_at = now
        return ["F"]

    def capture_event_view(**kwargs):
        captured_batches.append(kwargs["requested_event_ids"])
        return _capture_result(200, current_time)

    def advance_time(seconds: float) -> None:
        nonlocal current_time
        current_time += timedelta(seconds=seconds)

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_refresh_auto_watch_candidates", refresh_candidates)
    monkeypatch.setattr(cli, "capture_event_view", capture_event_view)
    monkeypatch.setattr(cli, "_utc_now", lambda: current_time)
    monkeypatch.setattr(cli.time, "sleep", advance_time)

    completed = cli._run_auto_watch(
        settings=cast(Settings, _FakeSettings()),
        state=state,
        within_minutes=10,
        interval_seconds=1,
        candidate_check_interval_seconds=1,
        max_cycles=2,
        auto_watch_config=load_auto_watch_config(),
    )

    assert completed
    assert captured_batches == [["B"], ["B", "F"]]
    assert [event.event_id for event in state.active_events] == ["B", "F"]


def test_auto_watch_stops_without_retrying_rate_limit_response(
    monkeypatch,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 13, 1, tzinfo=UTC)
    state = AutoWatchState(
        updated_at=now,
        active_events=[_active_event(event_id="B", sport_code="baseball", now=now)],
    )
    capture_count = 0

    def capture_event_view(**_kwargs):
        nonlocal capture_count
        capture_count += 1
        return _capture_result(429, now)

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_refresh_auto_watch_candidates", lambda **_kwargs: [])
    monkeypatch.setattr(cli, "capture_event_view", capture_event_view)
    monkeypatch.setattr(cli, "_utc_now", lambda: now)
    monkeypatch.setattr(
        cli.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(AssertionError("재시도하면 안 됩니다.")),
    )

    completed = cli._run_auto_watch(
        settings=cast(Settings, _FakeSettings()),
        state=state,
        within_minutes=10,
        interval_seconds=1,
        candidate_check_interval_seconds=300,
        max_cycles=None,
        auto_watch_config=load_auto_watch_config(),
    )

    assert not completed
    assert capture_count == 1


def test_due_non_finished_event_saves_exception_before_removal(
    monkeypatch,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 17, 1, tzinfo=UTC)
    event = _active_event(event_id="B", sport_code="baseball", now=now)
    event.last_time_status = 10
    event.status_policy_group = "temporarily_stopped"
    event.status_policy_started_at = now - timedelta(hours=2)
    event.last_capture_metadata_path = "metadata.json"
    state = AutoWatchState(updated_at=now, active_events=[event])
    saved_records = []

    _patch_storage(monkeypatch, tmp_path)

    def save_exception(record):
        saved_records.append(record)
        return tmp_path / "exception.json"

    monkeypatch.setattr(cli, "save_auto_watch_exception_record", save_exception)

    stopped_ids, exception_count, succeeded = cli._process_due_auto_watch_events(
        state=state,
        now=now,
        auto_watch_config=load_auto_watch_config(),
    )

    assert succeeded
    assert stopped_ids == ["B"]
    assert exception_count == 1
    assert len(saved_records) == 1
    assert saved_records[0].stop_time_status == 10
    assert saved_records[0].scheduled_at_kst.utcoffset() == timedelta(hours=9)
    assert state.active_events == []


def test_exception_save_failure_keeps_event_with_fixed_stop_time(
    monkeypatch,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 17, 1, tzinfo=UTC)
    event = _active_event(event_id="B", sport_code="baseball", now=now)
    event.last_time_status = 4
    event.status_policy_group = "closing"
    event.status_policy_started_at = now - timedelta(minutes=15)
    state = AutoWatchState(updated_at=now, active_events=[event])

    _patch_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli,
        "save_auto_watch_exception_record",
        lambda _record: (_ for _ in ()).throw(OSError("disk unavailable")),
    )

    stopped_ids, exception_count, succeeded = cli._process_due_auto_watch_events(
        state=state,
        now=now,
        auto_watch_config=load_auto_watch_config(),
    )

    assert succeeded
    assert stopped_ids == []
    assert exception_count == 0
    assert len(state.active_events) == 1
    assert state.active_events[0].stop_decided_at == now

    loaded = state_storage.load_auto_watch_state(tmp_path / "state.json")
    assert loaded is not None
    assert loaded.active_events[0].stop_decided_at == now
