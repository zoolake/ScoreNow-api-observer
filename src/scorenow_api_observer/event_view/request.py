MAX_EVENT_IDS_PER_REQUEST = 10


class InvalidRequestedEventIdsError(ValueError):
    """Event View API 요청 이벤트 ID 구성이 올바르지 않을 때 발생합니다."""


def parse_requested_event_ids(value: str) -> list[str]:
    """쉼표로 구분된 이벤트 ID를 검증하고 중복 제거 및 정렬하여 반환합니다."""

    event_id_parts = value.split(",")
    event_id_set = set()

    for event_id in event_id_parts:
        stripped_event_id = event_id.strip()

        if not stripped_event_id:
            raise InvalidRequestedEventIdsError("비어 있는 이벤트 ID가 존재합니다.")

        event_id_set.add(stripped_event_id)

    if len(event_id_set) > MAX_EVENT_IDS_PER_REQUEST:
        raise InvalidRequestedEventIdsError(
            f"최대 요청 가능한 ID는 {MAX_EVENT_IDS_PER_REQUEST}개입니다."
        )

    return sorted(event_id_set)


def build_event_view_request_batches(event_ids: list[str]) -> list[list[str]]:
    """이벤트 ID 순서를 유지하며 Event View 요청 최대 크기로 나눕니다."""

    return [
        list(event_ids[start_index : start_index + MAX_EVENT_IDS_PER_REQUEST])
        for start_index in range(0, len(event_ids), MAX_EVENT_IDS_PER_REQUEST)
    ]
