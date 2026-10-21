class InvalidOddsEventIdsError(ValueError):
    """Odds 수집 대상 이벤트 ID 입력이 올바르지 않을 때 발생합니다."""


def parse_odds_event_ids(value: str) -> list[str]:
    """쉼표로 구분된 이벤트 ID를 검증하고 중복 제거 및 정렬합니다."""

    event_ids = set()
    for event_id in value.split(","):
        normalized_event_id = event_id.strip()
        if not normalized_event_id:
            raise InvalidOddsEventIdsError("비어 있는 이벤트 ID가 존재합니다.")
        event_ids.add(normalized_event_id)

    return sorted(event_ids)
