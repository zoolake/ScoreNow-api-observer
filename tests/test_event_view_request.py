import pytest

from scorenow_api_observer.event_view.request import (
    MAX_EVENT_IDS_PER_REQUEST,
    InvalidRequestedEventIdsError,
    parse_requested_event_ids,
)


def test_parse_requested_event_ids_normalizes_event_ids() -> None:
    result = parse_requested_event_ids(" C, A, B, A ")

    assert result == ["A", "B", "C"]


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "A,,B",
        ",A",
        "A,",
    ],
)
def test_parse_requested_event_ids_rejects_empty_event_id(value: str) -> None:
    with pytest.raises(InvalidRequestedEventIdsError):
        parse_requested_event_ids(value)


def test_parse_requested_event_ids_accepts_maximum_unique_event_ids() -> None:
    event_ids = [f"event-{index}" for index in range(MAX_EVENT_IDS_PER_REQUEST)]

    result = parse_requested_event_ids(",".join([*event_ids, event_ids[0]]))

    assert result == sorted(event_ids)


def test_parse_requested_event_ids_rejects_too_many_unique_event_ids() -> None:
    event_ids = [f"event-{index}" for index in range(MAX_EVENT_IDS_PER_REQUEST + 1)]

    with pytest.raises(InvalidRequestedEventIdsError):
        parse_requested_event_ids(",".join(event_ids))
