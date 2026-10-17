from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from scorenow_api_observer.event_view.response import EventViewResponseIssue


class CaptureMetadata(BaseModel):
    """API 호출 한 번에 대한 부가 정보입니다."""

    schema_version: Literal[1] = 1
    response_analysis_status: Literal[
        "completed", "invalid_json", "invalid_response_shape"
    ]

    captured_at: datetime
    provider: str
    endpoint: str
    http_method: str

    requested_event_ids: list[str]
    returned_event_ids: list[str]
    response_issues: list[EventViewResponseIssue]

    http_status_code: int = Field(
        ge=100,
        le=599,
    )

    elapsed_ms: float = Field(ge=0)
    response_size_bytes: int = Field(ge=0)

    content_type: str | None
    raw_file_path: str


class TypeChangeRecord(BaseModel):
    """JSON 경로 하나에서 감지된 자료형 변화의 저장 형식입니다."""

    path: str
    previous_types: list[str]
    current_types: list[str]


class StructureChangeRecord(BaseModel):
    """두 수집 응답 사이에서 감지된 JSON 구조 변화와 출처의 저장 형식입니다."""

    detected_at: datetime
    event_id: str
    previous_captured_at: datetime
    current_captured_at: datetime
    previous_raw_file_path: str
    current_raw_file_path: str
    added_paths: list[str]
    removed_paths: list[str]
    type_changes: list[TypeChangeRecord]


class EventObservation(BaseModel):
    """Capture 응답 안의 특정 이벤트를 찾기 위한 참조 정보입니다."""

    event_id: str
    capture_metadata_file_path: str
    result_index: int = Field(ge=0)
