from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from scorenow_api_observer.upcoming.models import (
    DiscoveredUpcomingEvent,
    LeagueUpcomingDiscovery,
    UpcomingDiscoveryStatus,
)
from scorenow_api_observer.upcoming.storage import (
    load_league_upcoming_discovery,
)

DiscoveryGroupKey = tuple[date, str, str]


class InvalidUpcomingCandidateFilterError(ValueError):
    """후보 조회 필터 값이 올바르지 않을 때 발생합니다."""


@dataclass(frozen=True)
class LoadedLeagueDiscovery:
    """파일 경로와 함께 정상적으로 읽은 리그 Discovery입니다."""

    file_path: Path
    discovery: LeagueUpcomingDiscovery


@dataclass(frozen=True)
class LeagueDiscoveryLoadFailure:
    """읽거나 검증하지 못한 리그 Discovery 파일입니다."""

    file_path: Path
    error_type: str
    error_message: str


@dataclass(frozen=True)
class LeagueDiscoveryFallback:
    """최신 실패 대신 이전의 사용 가능한 Discovery를 선택한 내역입니다."""

    latest_failed: LoadedLeagueDiscovery
    selected: LoadedLeagueDiscovery


@dataclass(frozen=True)
class UnavailableLeagueDiscovery:
    """저장 이력에 사용 가능한 결과가 없는 리그·조회 날짜입니다."""

    latest_attempt: LoadedLeagueDiscovery


@dataclass(frozen=True)
class LatestLeagueDiscoveries:
    """리그·조회 날짜별 최신 사용 가능 결과와 읽기 경고를 모은 값입니다."""

    selected: list[LoadedLeagueDiscovery]
    fallbacks: list[LeagueDiscoveryFallback]
    unavailable: list[UnavailableLeagueDiscovery]
    load_failures: list[LeagueDiscoveryLoadFailure]


@dataclass(frozen=True)
class UpcomingCandidate:
    """watch 후보로 선택된 이벤트와 출처 Discovery 정보입니다."""

    event: DiscoveredUpcomingEvent
    league_label: str
    discovery_status: UpcomingDiscoveryStatus
    discovery_completed_at: datetime
    discovery_file_path: Path


@dataclass(frozen=True)
class UpcomingCandidateSelection:
    """시간 범위에 포함된 고유 이벤트 후보와 중복 ID 내역입니다."""

    candidates: list[UpcomingCandidate]
    duplicate_event_ids: list[str]


def resolve_latest_league_discoveries(
    file_paths: Iterable[Path],
) -> LatestLeagueDiscoveries:
    """리그·조회 날짜별 최신 사용 가능 Discovery를 부분 실패 방식으로 찾습니다."""

    attempts_by_group: dict[DiscoveryGroupKey, list[LoadedLeagueDiscovery]] = (
        defaultdict(list)
    )
    load_failures: list[LeagueDiscoveryLoadFailure] = []

    for file_path in sorted(file_paths):
        try:
            discovery = load_league_upcoming_discovery(file_path)
            _validate_discovery_datetimes(discovery)
        except (OSError, UnicodeError, ValueError, ValidationError) as error:
            load_failures.append(
                LeagueDiscoveryLoadFailure(
                    file_path=file_path,
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
            )
            continue

        loaded_discovery = LoadedLeagueDiscovery(
            file_path=file_path,
            discovery=discovery,
        )
        attempts_by_group[_discovery_group_key(discovery)].append(loaded_discovery)

    selected: list[LoadedLeagueDiscovery] = []
    fallbacks: list[LeagueDiscoveryFallback] = []
    unavailable: list[UnavailableLeagueDiscovery] = []

    for attempts in attempts_by_group.values():
        ordered_attempts = sorted(attempts, key=_loaded_discovery_sort_key)
        latest_attempt = ordered_attempts[-1]
        usable_attempts = [
            attempt
            for attempt in ordered_attempts
            if attempt.discovery.status in ("completed", "partial")
        ]

        if not usable_attempts:
            unavailable.append(
                UnavailableLeagueDiscovery(latest_attempt=latest_attempt)
            )
            continue

        selected_attempt = usable_attempts[-1]
        selected.append(selected_attempt)
        if selected_attempt is not latest_attempt:
            fallbacks.append(
                LeagueDiscoveryFallback(
                    latest_failed=latest_attempt,
                    selected=selected_attempt,
                )
            )

    return LatestLeagueDiscoveries(
        selected=sorted(selected, key=_selected_discovery_display_key),
        fallbacks=sorted(
            fallbacks,
            key=lambda fallback: _selected_discovery_display_key(fallback.selected),
        ),
        unavailable=sorted(
            unavailable,
            key=lambda item: _selected_discovery_display_key(item.latest_attempt),
        ),
        load_failures=load_failures,
    )


def select_upcoming_candidates(
    discoveries: Iterable[LoadedLeagueDiscovery],
    *,
    now: datetime,
    within_minutes: int,
    sport_code: str | None = None,
    league_labels: frozenset[str] | None = None,
) -> UpcomingCandidateSelection:
    """현재부터 N분 이내 시작하는 이벤트를 필터링하고 ID 중복을 제거합니다."""

    if within_minutes < 1:
        raise ValueError("후보 조회 시간 범위는 1분 이상이어야 합니다.")

    normalized_now = _as_utc(now, field_name="후보 조회 기준 시각")
    window_end = normalized_now + timedelta(minutes=within_minutes)
    candidates_by_event_id: dict[str, UpcomingCandidate] = {}
    duplicate_event_ids: set[str] = set()

    for loaded_discovery in discoveries:
        discovery = loaded_discovery.discovery
        target = discovery.target
        if sport_code is not None and target.sport_code != sport_code:
            continue
        if league_labels is not None and target.league_label not in league_labels:
            continue

        for event in discovery.events:
            scheduled_at_utc = _as_utc(
                event.scheduled_at_utc,
                field_name=f"이벤트 {event.event_id!r} 시작 시각",
            )
            if not normalized_now <= scheduled_at_utc <= window_end:
                continue

            candidate = UpcomingCandidate(
                event=event,
                league_label=target.league_label,
                discovery_status=discovery.status,
                discovery_completed_at=discovery.completed_at,
                discovery_file_path=loaded_discovery.file_path,
            )
            previous_candidate = candidates_by_event_id.get(event.event_id)
            if previous_candidate is not None:
                duplicate_event_ids.add(event.event_id)
                if _candidate_source_sort_key(candidate) <= _candidate_source_sort_key(
                    previous_candidate
                ):
                    continue
            candidates_by_event_id[event.event_id] = candidate

    return UpcomingCandidateSelection(
        candidates=sorted(
            candidates_by_event_id.values(),
            key=lambda candidate: (
                _as_utc(
                    candidate.event.scheduled_at_utc,
                    field_name=f"이벤트 {candidate.event.event_id!r} 시작 시각",
                ),
                candidate.event.event_id,
            ),
        ),
        duplicate_event_ids=sorted(duplicate_event_ids),
    )


def parse_candidate_league_labels(value: str | None) -> frozenset[str] | None:
    """선택적인 쉼표 구분 리그 label 필터를 정규화합니다."""

    if value is None:
        return None

    labels = [label.strip() for label in value.split(",")]
    if not labels or any(not label for label in labels):
        raise InvalidUpcomingCandidateFilterError(
            "리그 label은 빈 값 없이 쉼표로 구분해야 합니다."
        )
    return frozenset(labels)


def normalize_candidate_sport_code(value: str | None) -> str | None:
    """선택적인 종목 코드 필터의 앞뒤 공백을 제거합니다."""

    if value is None:
        return None

    sport_code = value.strip()
    if not sport_code:
        raise InvalidUpcomingCandidateFilterError(
            "종목 코드에는 빈 값을 사용할 수 없습니다."
        )
    return sport_code


def _discovery_group_key(discovery: LeagueUpcomingDiscovery) -> DiscoveryGroupKey:
    target = discovery.target
    return (discovery.target_date, target.sport_id, target.league_id)


def _loaded_discovery_sort_key(
    loaded_discovery: LoadedLeagueDiscovery,
) -> tuple[datetime, str, str]:
    discovery = loaded_discovery.discovery
    return (
        _as_utc(discovery.completed_at, field_name="Discovery 완료 시각"),
        discovery.discovery_run_id,
        str(loaded_discovery.file_path),
    )


def _selected_discovery_display_key(
    loaded_discovery: LoadedLeagueDiscovery,
) -> tuple[date, str, str, str]:
    discovery = loaded_discovery.discovery
    target = discovery.target
    return (
        discovery.target_date,
        target.sport_code,
        target.league_label,
        target.league_id,
    )


def _candidate_source_sort_key(
    candidate: UpcomingCandidate,
) -> tuple[datetime, str]:
    return (
        _as_utc(
            candidate.discovery_completed_at,
            field_name="Discovery 완료 시각",
        ),
        str(candidate.discovery_file_path),
    )


def _validate_discovery_datetimes(discovery: LeagueUpcomingDiscovery) -> None:
    _as_utc(discovery.completed_at, field_name="Discovery 완료 시각")
    for event in discovery.events:
        _as_utc(
            event.scheduled_at_utc,
            field_name=f"이벤트 {event.event_id!r} UTC 시작 시각",
        )
        _as_utc(
            event.scheduled_at_kst,
            field_name=f"이벤트 {event.event_id!r} KST 시작 시각",
        )


def _as_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name}에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)
