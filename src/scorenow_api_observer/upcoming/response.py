from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from scorenow_api_observer.upcoming.models import (
    UpcomingLeague,
    UpcomingParticipant,
    UpcomingResponseIssue,
)

KST = ZoneInfo("Asia/Seoul")


class InvalidUpcomingResponseShapeError(ValueError):
    """Upcoming 응답의 최상위 구조를 분석할 수 없을 때 발생합니다."""


@dataclass(frozen=True)
class ObservableUpcomingEvent:
    """Discovery에 포함할 수 있는 예정 경기와 Capture 원문 위치입니다."""

    event_id: str
    sport_id: str
    sport_code: str
    time_status: str | None
    scheduled_at_utc: datetime
    scheduled_at_kst: datetime
    league: UpcomingLeague
    home: UpcomingParticipant
    away: UpcomingParticipant
    result_index: int


@dataclass(frozen=True)
class UpcomingResponseAnalysis:
    """Upcoming 응답에서 추출한 이벤트와 이상 현상입니다."""

    returned_event_ids: list[str]
    observable_events: list[ObservableUpcomingEvent]
    issues: list[UpcomingResponseIssue]


def analyze_upcoming_response(
    *,
    response_json: Any,
    requested_sport_id: str,
    requested_league_id: str,
    sport_code: str,
) -> UpcomingResponseAnalysis:
    """Upcoming 응답을 분석하고 Discovery에 안전하게 포함할 경기를 찾습니다."""

    _validate_response_json(response_json)
    event_results: list[Any] = response_json["results"]
    issues: list[UpcomingResponseIssue] = []
    returned_event_ids: list[str] = []
    result_indices_by_event_id: dict[str, list[int]] = {}

    for result_index, event_result in enumerate(event_results):
        if not isinstance(event_result, dict):
            issues.append(
                UpcomingResponseIssue(
                    code="invalid_event_shape",
                    event_id=None,
                    result_indices=[result_index],
                    expected_value="object",
                    actual_value=type(event_result).__name__,
                )
            )
            continue

        event_id = _read_required_string(event_result.get("id"))
        if event_id is None:
            issues.append(
                UpcomingResponseIssue(
                    code="missing_event_id",
                    event_id=None,
                    result_indices=[result_index],
                )
            )
            continue

        returned_event_ids.append(event_id)
        result_indices_by_event_id.setdefault(event_id, []).append(result_index)

    duplicate_event_ids = {
        event_id
        for event_id, result_indices in result_indices_by_event_id.items()
        if len(result_indices) > 1
    }
    for event_id in sorted(duplicate_event_ids):
        issues.append(
            UpcomingResponseIssue(
                code="duplicate_event_id",
                event_id=event_id,
                result_indices=result_indices_by_event_id[event_id],
            )
        )

    observable_events: list[ObservableUpcomingEvent] = []
    for result_index, event_result in enumerate(event_results):
        if not isinstance(event_result, dict):
            continue

        event_id = _read_required_string(event_result.get("id"))
        if event_id is None or event_id in duplicate_event_ids:
            continue

        event_issues: list[UpcomingResponseIssue] = []
        actual_sport_id = _read_required_string(event_result.get("sport_id"))
        if actual_sport_id != requested_sport_id:
            event_issues.append(
                UpcomingResponseIssue(
                    code="unexpected_sport_id",
                    event_id=event_id,
                    result_indices=[result_index],
                    expected_value=requested_sport_id,
                    actual_value=actual_sport_id,
                )
            )

        raw_league = event_result.get("league")
        league_json: dict[str, Any] = raw_league if isinstance(raw_league, dict) else {}
        actual_league_id = _read_required_string(league_json.get("id"))
        if actual_league_id != requested_league_id:
            event_issues.append(
                UpcomingResponseIssue(
                    code="unexpected_league_id",
                    event_id=event_id,
                    result_indices=[result_index],
                    expected_value=requested_league_id,
                    actual_value=actual_league_id,
                )
            )

        scheduled_at_utc = _parse_unix_timestamp(event_result.get("time"))
        if scheduled_at_utc is None:
            event_issues.append(
                UpcomingResponseIssue(
                    code="invalid_scheduled_time",
                    event_id=event_id,
                    result_indices=[result_index],
                    actual_value=_issue_value(event_result.get("time")),
                )
            )

        issues.extend(event_issues)
        if event_issues or scheduled_at_utc is None or actual_league_id is None:
            continue

        observable_events.append(
            ObservableUpcomingEvent(
                event_id=event_id,
                sport_id=requested_sport_id,
                sport_code=sport_code,
                time_status=_read_optional_scalar(event_result.get("time_status")),
                scheduled_at_utc=scheduled_at_utc,
                scheduled_at_kst=scheduled_at_utc.astimezone(KST),
                league=UpcomingLeague(
                    id=actual_league_id,
                    name=_read_optional_string(league_json.get("name")),
                    country_code=_read_optional_string(
                        league_json.get("cc", league_json.get("country_code"))
                    ),
                ),
                home=_read_participant(event_result.get("home")),
                away=_read_participant(event_result.get("away")),
                result_index=result_index,
            )
        )

    total_result_count = _read_nonnegative_integer(
        response_json.get("pager", {}).get("total")
        if isinstance(response_json.get("pager"), dict)
        else None
    )
    if total_result_count is not None and total_result_count > len(event_results):
        issues.append(
            UpcomingResponseIssue(
                code="pagination_required",
                event_id=None,
                result_indices=[],
                expected_value=len(event_results),
                actual_value=total_result_count,
            )
        )

    return UpcomingResponseAnalysis(
        returned_event_ids=returned_event_ids,
        observable_events=observable_events,
        issues=issues,
    )


def _validate_response_json(response_json: Any) -> None:
    if not isinstance(response_json, dict):
        raise InvalidUpcomingResponseShapeError(
            "Upcoming 응답의 최상위 값은 JSON 객체여야 합니다."
        )

    if "results" not in response_json:
        raise InvalidUpcomingResponseShapeError(
            "Upcoming 응답에 results 필드가 없습니다."
        )

    if not isinstance(response_json["results"], list):
        raise InvalidUpcomingResponseShapeError(
            "Upcoming 응답의 results 필드는 배열이어야 합니다."
        )


def _read_required_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value


def _read_optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _read_optional_scalar(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _read_participant(value: Any) -> UpcomingParticipant:
    if not isinstance(value, dict):
        return UpcomingParticipant(id=None, name=None)
    return UpcomingParticipant(
        id=_read_optional_string(value.get("id")),
        name=_read_optional_string(value.get("name")),
    )


def _parse_unix_timestamp(value: Any) -> datetime | None:
    timestamp = _read_nonnegative_integer(value)
    if timestamp is None:
        return None

    try:
        return datetime.fromtimestamp(timestamp, UTC)
    except OverflowError, OSError, ValueError:
        return None


def _read_nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _issue_value(value: Any) -> str | int | None:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (str, int)):
        return value
    if value is None:
        return None
    return type(value).__name__
