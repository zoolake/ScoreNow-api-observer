from dataclasses import dataclass
from typing import Any


class InvalidEventViewResponseShapeError(ValueError):
    """Event View 응답이 분석 가능한 JSON 구조가 아닐 때 발생합니다."""


@dataclass(frozen=True)
class ObservableEvent:
    """EventObservation을 생성할 수 있는 이벤트의 원문 위치입니다.

    Attributes:
        event_id: View API 응답에서 식별한 이벤트 ID입니다.
        result_index: View API 응답의 results 배열에서 이벤트가 위치한
            0부터 시작하는 인덱스입니다.
    """

    event_id: str
    result_index: int


@dataclass(frozen=True)
class EventViewResponseIssue:
    """Event View 응답을 요청 내용과 대조하며 발견한 이상 현상입니다.

    Attributes:
        code: 이슈 종류를 식별하는 기계 판독용 코드입니다.
        event_id: 이슈와 관련된 이벤트 ID입니다. 응답에서 ID를 식별할 수
            없으면 None입니다.
        result_indices: 이슈가 발생한 results 배열의 0부터 시작하는
            인덱스입니다. 요청한 이벤트가 반환되지 않은 경우에는 빈 목록입니다.
    """

    code: str
    event_id: str | None
    result_indices: list[int]


@dataclass(frozen=True)
class EventViewResponseAnalysis:
    """Event View 응답에서 이벤트 ID와 이상 현상을 분석한 결과입니다.

    Attributes:
        returned_event_ids: 응답에서 식별한 이벤트 ID입니다. 응답 순서와 중복을
            그대로 보존하며, 요청하지 않은 이벤트 ID도 포함합니다.
        observable_events: ID가 존재하고 응답 안에서 중복되지 않아
            EventObservation을 만들 수 있는 이벤트입니다. 요청하지 않은
            이벤트라도 이 조건을 만족하면 포함합니다.
        issues: 응답을 요청 내용과 대조하며 발견한 이상 현상입니다.
    """

    returned_event_ids: list[str]
    observable_events: list[ObservableEvent]
    issues: list[EventViewResponseIssue]


def analyze_event_view_response(
    *,
    requested_event_ids: list[str],
    response_json: Any,
) -> EventViewResponseAnalysis:
    """BETS View API 의 응답을 분석합니다."""

    returned_event_ids: list[str] = []
    issues: list[EventViewResponseIssue] = []

    result_indices_by_event_id: dict[str, list[int]] = {}

    _validate_response_json(response_json)

    event_results: list[Any] = response_json["results"]

    for result_index, event_result in enumerate(event_results):
        # 응답 내 각 이벤트가 객체인지 확인
        if not isinstance(event_result, dict):
            raise InvalidEventViewResponseShapeError(
                f"Event View 응답의 results[{result_index}] 는 객체여야 합니다."
            )

        event_id = event_result.get("id")

        # Event Id 가 없는 경우
        if event_id is None:
            issues.append(
                EventViewResponseIssue("missing_event_id", None, [result_index])
            )
            continue

        returned_event_ids.append(event_id)

        result_indices_by_event_id.setdefault(event_id, []).append(result_index)

    requested_event_id_set: set[str] = set(requested_event_ids)
    returned_event_id_set: set[str] = set(returned_event_ids)

    # 요청에는 있지만 응답에는 없는 경우
    missing_event_ids = requested_event_id_set - returned_event_id_set

    # 요청에는 없지만 응답에는 있는 경우
    unexpected_event_ids = returned_event_id_set - requested_event_id_set

    # 응답 Event Id 가 중복되는 경우
    duplicate_event_ids: set[str] = set()
    for event_id, result_index in result_indices_by_event_id.items():
        if len(result_index) > 1:
            duplicate_event_ids.add(event_id)

    # 분류결과 기반 issue 생성
    for missing_event_id in sorted(missing_event_ids):
        issues.append(
            EventViewResponseIssue("missing_requested_event", missing_event_id, [])
        )

    for unexpected_event_id in sorted(unexpected_event_ids):
        issues.append(
            EventViewResponseIssue(
                "unexpected_event_id",
                unexpected_event_id,
                result_indices_by_event_id[unexpected_event_id],
            )
        )

    for duplicate_event_id in sorted(duplicate_event_ids):
        issues.append(
            EventViewResponseIssue(
                "duplicate_event_id",
                duplicate_event_id,
                result_indices_by_event_id[duplicate_event_id],
            )
        )

    # observable_event_ids 계산
    observable_event_ids = returned_event_id_set - duplicate_event_ids

    observable_events: list[ObservableEvent] = []
    for observation_event_id in sorted(observable_event_ids):
        result_index = result_indices_by_event_id[observation_event_id]
        observable_events.append(
            ObservableEvent(
                event_id=observation_event_id,
                result_index=result_index[0],
            )
        )

    return EventViewResponseAnalysis(
        returned_event_ids=returned_event_ids,
        observable_events=observable_events,
        issues=issues,
    )


def _validate_response_json(response_json: Any) -> None:

    # dict 검증
    if not isinstance(response_json, dict):
        raise InvalidEventViewResponseShapeError(
            "Event View 응답의 최상위 값은 JSON 객체여야 합니다."
        )

    # results 존재 여부 검증
    if "results" not in response_json:
        raise InvalidEventViewResponseShapeError(
            "Event View 응답에 results 필드가 없습니다."
        )

    # results 배열 여부 검증
    if not isinstance(response_json["results"], list):
        raise InvalidEventViewResponseShapeError(
            "Event View 응답의 results 필드는 배열이어야 합니다."
        )
