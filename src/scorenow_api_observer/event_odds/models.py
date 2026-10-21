from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OddsRequestQuery(BaseModel):
    """토큰을 제외하고 저장하는 Event Odds API 조회 조건입니다."""

    event_id: str
    odds_market: str


class OddsSnapshotMetadata(BaseModel):
    """이벤트별 일간 최신 Event Odds 원문을 설명하는 메타데이터입니다."""

    schema_version: Literal[1] = 1
    captured_at: datetime
    provider: str
    endpoint: str
    http_method: str
    query: OddsRequestQuery
    returned_market_keys: list[str]
    record_counts_by_market: dict[str, int]
    http_status_code: int = Field(ge=100, le=599)
    elapsed_ms: float = Field(ge=0)
    response_size_bytes: int = Field(ge=0)
    content_type: str | None
    raw_file_path: str
