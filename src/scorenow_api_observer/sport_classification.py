from typing import Any


def classify_event_sport(
    *,
    event: dict[str, Any],
    sport_code_by_id: dict[str, str],
) -> str | None:
    """이벤트의 BETS sport_id를 내부 종목 코드로 분류합니다.

    분류할 수 없으면 None을 반환합니다.
    """

    sport_id = event.get("sport_id")
    if sport_id is None:
        return None

    if not isinstance(sport_id, str):
        return None

    sport_code = sport_code_by_id.get(sport_id)
    if sport_code is None:
        return None

    return sport_code
