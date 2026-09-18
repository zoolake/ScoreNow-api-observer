from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from scorenow_api_observer import collector
from scorenow_api_observer.event_view_response import EventViewResponseIssue
from scorenow_api_observer.models import CaptureMetadata, EventObservation


def _response(*, content: bytes, content_type: str) -> httpx.Response:
    response = httpx.Response(
        200,
        content=content,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://example.test/v1/event/view"),
    )
    response.elapsed = timedelta(milliseconds=12.34)
    return response


def _capture_with_response(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    response: httpx.Response,
    observation_save_errors: dict[str, OSError] | None = None,
) -> tuple[
    collector.CaptureResult,
    list[CaptureMetadata],
    list[EventObservation],
]:
    raw_path = tmp_path / "raw.json"
    metadata_path = tmp_path / "metadata.json"
    saved_metadata: list[CaptureMetadata] = []
    saved_observations: list[EventObservation] = []

    monkeypatch.setattr(collector, "get_event_view", lambda **_kwargs: response)
    monkeypatch.setattr(
        collector,
        "save_raw_response",
        lambda **_kwargs: raw_path,
    )

    def save_metadata(metadata: CaptureMetadata) -> Path:
        saved_metadata.append(metadata)
        return metadata_path

    monkeypatch.setattr(collector, "save_capture_metadata", save_metadata)

    def save_observation(observation: EventObservation) -> Path:
        if observation_save_errors is not None:
            error = observation_save_errors.get(observation.event_id)
            if error is not None:
                raise error
        saved_observations.append(observation)
        return tmp_path / f"{observation.event_id}.json"

    monkeypatch.setattr(collector, "save_event_observation", save_observation)

    result = collector.capture_event_view(
        base_url="https://example.test",
        token="test-token",
        event_id="A",
    )

    return result, saved_metadata, saved_observations


def test_capture_event_view_analyzes_json_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response = _response(
        content=b'{"success":1,"results":[{"id":"A"},{"id":"C"}]}',
        content_type="application/json",
    )

    result, saved_metadata, saved_observations = _capture_with_response(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        response=response,
    )

    assert result.metadata.response_analysis_status == "completed"
    assert result.metadata.requested_event_ids == ["A"]
    assert result.metadata.returned_event_ids == ["A", "C"]
    assert result.metadata.response_issues == [
        EventViewResponseIssue("unexpected_event_id", "C", [1])
    ]
    assert saved_metadata == [result.metadata]
    assert saved_observations == [
        EventObservation(
            event_id="A",
            capture_metadata_file_path=str(tmp_path / "metadata.json"),
            result_index=0,
        ),
        EventObservation(
            event_id="C",
            capture_metadata_file_path=str(tmp_path / "metadata.json"),
            result_index=1,
        ),
    ]


def test_capture_event_view_saves_metadata_when_response_is_not_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response = _response(content=b"not-json", content_type="text/plain")

    result, saved_metadata, saved_observations = _capture_with_response(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        response=response,
    )

    assert result.metadata.response_analysis_status == "invalid_json"
    assert result.metadata.requested_event_ids == ["A"]
    assert result.metadata.returned_event_ids == []
    assert result.metadata.response_issues == []
    assert saved_metadata == [result.metadata]
    assert saved_observations == []


def test_capture_event_view_continues_after_observation_save_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response = _response(
        content=b'{"success":1,"results":[{"id":"A"},{"id":"C"}]}',
        content_type="application/json",
    )

    result, saved_metadata, saved_observations = _capture_with_response(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        response=response,
        observation_save_errors={"A": OSError("disk full")},
    )

    assert saved_metadata == [result.metadata]
    assert saved_observations == [
        EventObservation(
            event_id="C",
            capture_metadata_file_path=str(tmp_path / "metadata.json"),
            result_index=1,
        )
    ]
    assert result.observation_save_failures == [
        collector.EventObservationSaveFailure(
            event_id="A",
            error_message="disk full",
        )
    ]


def test_capture_event_view_saves_metadata_when_response_shape_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response = _response(
        content=b'{"success":1}',
        content_type="application/json",
    )

    result, saved_metadata, saved_observations = _capture_with_response(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        response=response,
    )

    assert result.metadata.response_analysis_status == "invalid_response_shape"
    assert result.metadata.requested_event_ids == ["A"]
    assert result.metadata.returned_event_ids == []
    assert result.metadata.response_issues == []
    assert saved_metadata == [result.metadata]
    assert saved_observations == []
