from typing import Any

from scorenow_api_observer.models import EventObservation


class InvalidEventObservationReferenceError(ValueError):
    """EventObservation이 원문의 이벤트를 올바르게 가리키지 않을 때 발생합니다."""


def extract_observed_event(
    *,
    observation: EventObservation,
    response_json: Any,
) -> dict[str, Any]:
    """Observation이 가리키는 이벤트 객체를 원문 응답에서 추출합니다."""

    event_id = observation.event_id
    result_index = observation.result_index

    # dict 검증
    if not isinstance(response_json, dict):
        raise InvalidEventObservationReferenceError(
            "Event View 응답의 최상위 값은 JSON 객체여야 합니다."
        )

    # 응답에 results 가 없는 경우
    if "results" not in response_json:
        raise InvalidEventObservationReferenceError(
            "Event View 응답에 results 필드가 없습니다."
        )

    # results 가 list 인지
    if not isinstance(response_json["results"], list):
        raise InvalidEventObservationReferenceError(
            "Event View 응답의 results 필드는 배열이어야 합니다."
        )

    results: list[Any] = response_json["results"]

    # 인덱스가 넘어가는 경우
    if result_index >= len(results):
        raise InvalidEventObservationReferenceError(
            f"EventObservation의 result_index({result_index})가 results 범위"
            f"(길이: {len(results)})를 벗어났습니다."
        )

    # 이벤트 데이터가 dict 인지
    if not isinstance(results[result_index], dict):
        raise InvalidEventObservationReferenceError(
            f"Event View 응답의 results[{result_index}]는 JSON 객체여야 합니다."
        )

    event_result: dict[str, Any] = results[result_index]

    if "id" not in event_result:
        raise InvalidEventObservationReferenceError(
            f"Event View 응답의 results[{result_index}]에 id 필드가 없습니다."
        )

    actual_event_id = event_result["id"]
    if actual_event_id != event_id:
        raise InvalidEventObservationReferenceError(
            f"EventObservation의 event_id({event_id!r})와 "
            f"results[{result_index}].id({actual_event_id!r})가 일치하지 않습니다."
        )

    return event_result
