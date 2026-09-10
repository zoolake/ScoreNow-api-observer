from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scorenow_api_observer.bets_api_client import EVENT_VIEW_ENDPOINT, get_event_view
from scorenow_api_observer.models import CaptureMetadata
from scorenow_api_observer.storage import save_capture_metadata, save_raw_response


@dataclass(frozen=True)
class CaptureResult:
    """API 호출과 저장 결과입니다."""

    response: httpx.Response
    raw_file_path: Path
    metadata_file_path: Path


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

    raw_file_path = save_raw_response(
        event_id=event_id,
        response_body=response.content,
        captured_at=captured_at,
    )

    metadata = CaptureMetadata(
        captured_at=captured_at,
        provider="betsapi",
        endpoint=EVENT_VIEW_ENDPOINT,
        http_method="GET",
        event_ids=[event_id],
        http_status_code=response.status_code,
        elapsed_ms=round(response.elapsed.total_seconds() * 1000, 2),
        response_size_bytes=len(response.content),
        content_type=response.headers.get("content-type"),
        raw_file_path=str(raw_file_path),
    )

    metadata_file_path = save_capture_metadata(metadata)

    return CaptureResult(
        response=response,
        raw_file_path=raw_file_path,
        metadata_file_path=metadata_file_path,
    )
