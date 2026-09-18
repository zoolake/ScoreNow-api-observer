from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scorenow_api_observer.bets_api_client import EVENT_VIEW_ENDPOINT, get_event_view
from scorenow_api_observer.event_view_response import (
    InvalidEventViewResponseShapeError,
    analyze_event_view_response,
)
from scorenow_api_observer.models import CaptureMetadata, EventObservation
from scorenow_api_observer.storage import (
    save_capture_metadata,
    save_event_observation,
    save_raw_response,
)


@dataclass(frozen=True)
class EventObservationSaveFailure:
    event_id: str
    error_message: str


@dataclass(frozen=True)
class CaptureResult:
    """API 호출과 저장 결과입니다."""

    response: httpx.Response
    raw_file_path: Path
    metadata_file_path: Path
    metadata: CaptureMetadata
    observation_save_failures: list[EventObservationSaveFailure]


def capture_event_view(
    *,
    base_url: str,
    token: str,
    event_id: str,
) -> CaptureResult:
    """Event View API 를 한 번 호출하고 응답과 메타데이터를 저장합니다."""

    response = get_event_view(
        base_url=base_url,
        token=token,
        event_id=event_id,
    )

    captured_at = datetime.now(UTC)

    # 응답 원본 저장
    raw_file_path = save_raw_response(
        event_id=event_id,
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
                requested_event_ids=[event_id],
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
        requested_event_ids=[event_id],
        returned_event_ids=returned_event_ids,
        response_issues=response_issues,
        http_status_code=response.status_code,
        elapsed_ms=round(response.elapsed.total_seconds() * 1000, 2),
        response_size_bytes=len(response.content),
        content_type=response.headers.get("content-type"),
        raw_file_path=str(raw_file_path),
    )

    metadata_file_path = save_capture_metadata(metadata)

    observation_save_failures: list[EventObservationSaveFailure] = []
    for observable_event in observable_events:
        try:
            event_observation = EventObservation(
                event_id=observable_event.event_id,
                capture_metadata_file_path=str(metadata_file_path),
                result_index=observable_event.result_index,
            )

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
    )
