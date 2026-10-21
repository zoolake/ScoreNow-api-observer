from dataclasses import dataclass
from typing import Any


class InvalidEventOddsResponseShapeError(ValueError):
    """Event Odds 응답을 유효한 누적 배당률 Snapshot으로 해석할 수 없습니다."""


@dataclass(frozen=True)
class EventOddsResponseAnalysis:
    """유효한 Event Odds 응답에서 계산한 마켓별 레코드 현황입니다."""

    returned_market_keys: list[str]
    record_counts_by_market: dict[str, int]


def analyze_event_odds_response(response_json: Any) -> EventOddsResponseAnalysis:
    """Event Odds 응답 구조를 검증하고 마켓별 레코드 수를 계산합니다."""

    if not isinstance(response_json, dict):
        raise InvalidEventOddsResponseShapeError(
            "Event Odds 응답의 최상위 값은 JSON 객체여야 합니다."
        )

    success = response_json.get("success")
    if isinstance(success, bool) or not isinstance(success, int) or success != 1:
        raise InvalidEventOddsResponseShapeError(
            "Event Odds 응답의 success 필드는 정수 1이어야 합니다."
        )

    results = response_json.get("results")
    if not isinstance(results, dict):
        raise InvalidEventOddsResponseShapeError(
            "Event Odds 응답의 results 필드는 JSON 객체여야 합니다."
        )

    odds = results.get("odds")
    if not isinstance(odds, dict):
        raise InvalidEventOddsResponseShapeError(
            "Event Odds 응답의 results.odds 필드는 JSON 객체여야 합니다."
        )

    record_counts_by_market: dict[str, int] = {}
    for market_key, records in odds.items():
        if not isinstance(market_key, str) or not market_key:
            raise InvalidEventOddsResponseShapeError(
                "Event Odds 응답의 마켓 키는 비어 있지 않은 문자열이어야 합니다."
            )
        if not isinstance(records, list):
            raise InvalidEventOddsResponseShapeError(
                f"Event Odds 마켓 {market_key!r}의 값은 배열이어야 합니다."
            )
        if any(not isinstance(record, dict) for record in records):
            raise InvalidEventOddsResponseShapeError(
                f"Event Odds 마켓 {market_key!r}의 레코드는 JSON 객체여야 합니다."
            )
        record_counts_by_market[market_key] = len(records)

    returned_market_keys = sorted(record_counts_by_market)
    return EventOddsResponseAnalysis(
        returned_market_keys=returned_market_keys,
        record_counts_by_market={
            market_key: record_counts_by_market[market_key]
            for market_key in returned_market_keys
        },
    )
