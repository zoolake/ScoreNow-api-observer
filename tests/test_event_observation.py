from typing import Any

import pytest

from scorenow_api_observer.event_observation import (
    InvalidEventObservationReferenceError,
    extract_observed_event,
)
from scorenow_api_observer.models import EventObservation


def _observation(*, event_id: str = "A", result_index: int = 0) -> EventObservation:
    return EventObservation(
        event_id=event_id,
        capture_metadata_file_path="data/metadata/capture.json",
        result_index=result_index,
    )


def test_extract_observed_event_returns_referenced_event() -> None:
    event = {"id": "A", "sport_id": "3"}

    result = extract_observed_event(
        observation=_observation(result_index=1),
        response_json={"results": [{"id": "B"}, event]},
    )

    assert result == event


@pytest.mark.parametrize(
    ("observation", "response_json"),
    [
        (_observation(), []),
        (_observation(), {}),
        (_observation(), {"results": None}),
        (_observation(result_index=1), {"results": [{"id": "A"}]}),
        (_observation(), {"results": ["not-an-object"]}),
        (_observation(), {"results": [{"sport_id": "3"}]}),
        (_observation(event_id="A"), {"results": [{"id": "B"}]}),
    ],
)
def test_extract_observed_event_rejects_invalid_reference(
    observation: EventObservation,
    response_json: Any,
) -> None:
    with pytest.raises(InvalidEventObservationReferenceError):
        extract_observed_event(
            observation=observation,
            response_json=response_json,
        )
