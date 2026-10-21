import pytest

from scorenow_api_observer.event_odds.request import (
    InvalidOddsEventIdsError,
    parse_odds_event_ids,
)


def test_parse_odds_event_ids_normalizes_deduplicates_and_sorts() -> None:
    assert parse_odds_event_ids(" C, A, B, A ") == ["A", "B", "C"]


@pytest.mark.parametrize("value", ["", " ", "A,,B", ",A", "A,"])
def test_parse_odds_event_ids_rejects_empty_values(value: str) -> None:
    with pytest.raises(InvalidOddsEventIdsError, match="비어 있는 이벤트 ID"):
        parse_odds_event_ids(value)
