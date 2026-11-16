from datetime import UTC, datetime
from pathlib import Path

import pytest

from scorenow_api_observer.event_view.request_log import (
    EventViewApiRequestRecord,
    RequestedEvent,
    classify_request_category,
    finish_event_view_api_request,
    start_event_view_api_request,
)


@pytest.mark.parametrize(
    ("sport_codes", "expected"),
    [
        (["football"], "football_only"),
        (["baseball", "baseball"], "baseball_only"),
        (["football", "baseball"], "mixed"),
        ([None], "unknown"),
        (["football", None], "unknown"),
    ],
)
def test_classify_request_category(sport_codes, expected: str) -> None:
    requested_events = [
        RequestedEvent(event_id=str(index), sport_code=sport_code)
        for index, sport_code in enumerate(sport_codes)
    ]

    assert classify_request_category(requested_events) == expected


def test_api_request_record_is_started_before_call_and_completed_in_same_file(
    tmp_path: Path,
) -> None:
    requested_at = datetime(2026, 11, 13, 1, tzinfo=UTC)
    handle = start_event_view_api_request(
        requested_events=[
            RequestedEvent(event_id="F", sport_code="football"),
            RequestedEvent(event_id="B", sport_code="baseball"),
        ],
        requested_at=requested_at,
        base_directory=tmp_path,
    )

    started = EventViewApiRequestRecord.model_validate_json(
        handle.file_path.read_text(encoding="utf-8")
    )
    assert started.outcome == "started"
    assert started.request_category == "mixed"
    assert not hasattr(started, "football_event_id_count")
    assert not hasattr(started, "baseball_event_id_count")

    completed = finish_event_view_api_request(
        handle=handle,
        completed_at=requested_at,
        outcome="completed",
        http_status_code=200,
    )

    assert completed.outcome == "completed"
    assert completed.http_status_code == 200
    assert list(tmp_path.rglob("*.json")) == [handle.file_path]
    assert (
        EventViewApiRequestRecord.model_validate_json(
            handle.file_path.read_text(encoding="utf-8")
        )
        == completed
    )
