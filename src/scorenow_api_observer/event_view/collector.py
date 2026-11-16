from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scorenow_api_observer.bets_api_client import EVENT_VIEW_ENDPOINT, get_event_view
from scorenow_api_observer.event_view.models import CaptureMetadata, EventObservation
from scorenow_api_observer.event_view.request_log import (
    EVENT_VIEW_REQUEST_LOG_DIRECTORY,
    EventViewApiRequestRecord,
    RequestedEvent,
    finish_event_view_api_request,
    start_event_view_api_request,
)
from scorenow_api_observer.event_view.response import (
    InvalidEventViewResponseShapeError,
    analyze_event_view_response,
)
from scorenow_api_observer.event_view.storage import (
    save_capture_metadata,
    save_event_observation,
    save_raw_response,
)


@dataclass(frozen=True)
class EventObservationSaveFailure:
    """EventObservation 저장에 실패한 이벤트와 원인입니다."""

    event_id: str
    error_message: str


class EventViewRequestLogStartError(OSError):
    """호출 기록을 시작하지 못해 Event View API 호출을 생략했음을 나타냅니다."""


@dataclass(frozen=True)
class CaptureResult:
    """한 번의 API 호출에서 생성된 Capture와 Observation 처리 결과입니다.

    event_observations에는 저장 성공 여부와 관계없이 생성된 Observation이 포함되며,
    저장 실패 내역은 observation_save_failures에 별도로 기록됩니다.
    """

    response: httpx.Response
    raw_file_path: Path
    metadata_file_path: Path
    metadata: CaptureMetadata
    observation_save_failures: list[EventObservationSaveFailure]
    event_observations: list[EventObservation]
    api_request_record: EventViewApiRequestRecord | None = None


def capture_event_view(
    *,
    base_url: str,
    token: str,
    requested_event_ids: list[str],
    sport_codes_by_event_id: dict[str, str] | None = None,
    request_log_base_directory: Path = EVENT_VIEW_REQUEST_LOG_DIRECTORY,
) -> CaptureResult:
    """Event View API 를 한 번 호출하고 응답과 메타데이터를 저장합니다."""

    requested_at = datetime.now(UTC)
    requested_events = [
        RequestedEvent(
            event_id=event_id,
            sport_code=(
                sport_codes_by_event_id.get(event_id)
                if sport_codes_by_event_id is not None
                else None
            ),
        )
        for event_id in requested_event_ids
    ]
    try:
        request_handle = start_event_view_api_request(
            requested_events=requested_events,
            requested_at=requested_at,
            base_directory=request_log_base_directory,
        )
    except OSError as error:
        raise EventViewRequestLogStartError(str(error)) from error

    try:
        response = get_event_view(
            base_url=base_url,
            token=token,
            requested_event_ids=requested_event_ids,
        )
    except httpx.RequestError as error:
        finish_event_view_api_request(
            handle=request_handle,
            completed_at=datetime.now(UTC),
            outcome="request_error",
            error_type=type(error).__name__,
        )
        raise

    api_request_record = finish_event_view_api_request(
        handle=request_handle,
        completed_at=datetime.now(UTC),
        outcome="completed",
        http_status_code=response.status_code,
    )

    captured_at = datetime.now(UTC)

    # 응답 원본 저장
    raw_file_path = save_raw_response(
        response_body=response.content,
        captured_at=captured_at,
    )

    # 응답 분석
    try:
        response_json = response.json()
    except ValueError:
        response_analysis_status = "invalid_json"
        observable_events = []
        returned_event_ids = []
        response_issues = []
    else:
        try:
            analysis = analyze_event_view_response(
                requested_event_ids=requested_event_ids,
                response_json=response_json,
            )
        except InvalidEventViewResponseShapeError:
            response_analysis_status = "invalid_response_shape"
            observable_events = []
            returned_event_ids = []
            response_issues = []
        else:
            observable_events = analysis.observable_events
            response_analysis_status = "completed"
            returned_event_ids = analysis.returned_event_ids
            response_issues = analysis.issues

    metadata = CaptureMetadata(
        captured_at=captured_at,
        response_analysis_status=response_analysis_status,
        provider="betsapi",
        endpoint=EVENT_VIEW_ENDPOINT,
        http_method="GET",
        requested_event_ids=requested_event_ids,
        returned_event_ids=returned_event_ids,
        response_issues=response_issues,
        http_status_code=response.status_code,
        elapsed_ms=round(response.elapsed.total_seconds() * 1000, 2),
        response_size_bytes=len(response.content),
        content_type=response.headers.get("content-type"),
        raw_file_path=str(raw_file_path),
    )

    metadata_file_path = save_capture_metadata(metadata)

    event_observations = []
    observation_save_failures: list[EventObservationSaveFailure] = []
    for observable_event in observable_events:
        event_observation = EventObservation(
            event_id=observable_event.event_id,
            capture_metadata_file_path=str(metadata_file_path),
            result_index=observable_event.result_index,
        )
        event_observations.append(event_observation)
        try:
            save_event_observation(event_observation)
        except OSError as error:
            observation_save_failures.append(
                EventObservationSaveFailure(
                    event_id=observable_event.event_id,
                    error_message=str(error),
                )
            )

    return CaptureResult(
        response=response,
        raw_file_path=raw_file_path,
        metadata_file_path=metadata_file_path,
        metadata=metadata,
        observation_save_failures=observation_save_failures,
        event_observations=event_observations,
        api_request_record=api_request_record,
    )
