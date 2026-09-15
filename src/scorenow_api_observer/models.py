from datetime import datetime

from pydantic import BaseModel, Field


class CaptureMetadata(BaseModel):
    """API 호출 한 번에 대한 부가 정보입니다."""

    captured_at: datetime
    provider: str
    endpoint: str
    http_method: str
    event_ids: list[str]

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
