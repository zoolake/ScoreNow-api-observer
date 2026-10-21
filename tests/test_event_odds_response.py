import pytest

from scorenow_api_observer.event_odds.response import (
    InvalidEventOddsResponseShapeError,
    analyze_event_odds_response,
)


def test_analyze_event_odds_response_summarizes_sorted_market_keys() -> None:
    response_json = {
        "success": 1,
        "results": {
            "stats": {"matching_dir": {}, "odds_update": {}},
            "odds": {
                "16_3": [{"id": "3"}],
                "16_1": [{"id": "1"}, {"id": "2"}],
                "16_2": [],
            },
        },
    }

    result = analyze_event_odds_response(response_json)

    assert result.returned_market_keys == ["16_1", "16_2", "16_3"]
    assert result.record_counts_by_market == {
        "16_1": 2,
        "16_2": 0,
        "16_3": 1,
    }


def test_analyze_event_odds_response_accepts_empty_odds_object() -> None:
    result = analyze_event_odds_response({"success": 1, "results": {"odds": {}}})

    assert result.returned_market_keys == []
    assert result.record_counts_by_market == {}


@pytest.mark.parametrize(
    ("response_json", "message"),
    [
        ([], "최상위 값"),
        ({"success": 0, "results": {"odds": {}}}, "success"),
        ({"success": True, "results": {"odds": {}}}, "success"),
        ({"success": 1, "results": []}, "results 필드"),
        ({"success": 1, "results": {}}, "results.odds"),
        (
            {"success": 1, "results": {"odds": {"16_1": {}}}},
            "값은 배열",
        ),
        (
            {"success": 1, "results": {"odds": {"16_1": ["invalid"]}}},
            "레코드는 JSON 객체",
        ),
    ],
)
def test_analyze_event_odds_response_rejects_invalid_shapes(
    response_json: object,
    message: str,
) -> None:
    with pytest.raises(InvalidEventOddsResponseShapeError, match=message):
        analyze_event_odds_response(response_json)
