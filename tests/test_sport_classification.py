from typing import Any

import pytest

from scorenow_api_observer.sport_classification import classify_event_sport

SPORT_CODE_BY_ID = {
    "1": "football",
    "16": "baseball",
    "18": "basketball",
}


@pytest.mark.parametrize(
    ("sport_id", "expected_sport_code"),
    [
        ("1", "football"),
        ("16", "baseball"),
        ("18", "basketball"),
    ],
)
def test_classify_event_sport_returns_mapped_sport_code(
    sport_id: str,
    expected_sport_code: str,
) -> None:
    result = classify_event_sport(
        event={"sport_id": sport_id},
        sport_code_by_id=SPORT_CODE_BY_ID,
    )

    assert result == expected_sport_code


def test_classify_event_sport_returns_none_when_sport_id_is_missing() -> None:
    result = classify_event_sport(
        event={"id": "A"},
        sport_code_by_id=SPORT_CODE_BY_ID,
    )

    assert result is None


@pytest.mark.parametrize(
    "sport_id",
    [
        None,
        16,
        True,
        [],
        {},
    ],
)
def test_classify_event_sport_returns_none_for_invalid_sport_id(
    sport_id: Any,
) -> None:
    result = classify_event_sport(
        event={"sport_id": sport_id},
        sport_code_by_id=SPORT_CODE_BY_ID,
    )

    assert result is None


@pytest.mark.parametrize("sport_id", ["", "999"])
def test_classify_event_sport_returns_none_for_unknown_sport_id(
    sport_id: str,
) -> None:
    result = classify_event_sport(
        event={"sport_id": sport_id},
        sport_code_by_id=SPORT_CODE_BY_ID,
    )

    assert result is None
