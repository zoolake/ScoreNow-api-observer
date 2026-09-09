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
