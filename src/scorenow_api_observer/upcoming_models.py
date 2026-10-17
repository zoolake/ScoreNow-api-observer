from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

UpcomingResponseIssueCode = Literal[
    "invalid_event_shape",
    "missing_event_id",
    "duplicate_event_id",
    "unexpected_sport_id",
    "unexpected_league_id",
    "invalid_scheduled_time",
    "pagination_required",
]


class UpcomingResponseIssue(BaseModel):
    """Upcoming 응답을 조회 조건과 대조하며 발견한 이상 현상입니다."""

    code: UpcomingResponseIssueCode
    event_id: str | None
    result_indices: list[int]
    expected_value: str | int | None = None
    actual_value: str | int | None = None


class UpcomingRequestQuery(BaseModel):
    """토큰을 제외하고 저장하는 Upcoming API 조회 조건입니다."""

    sport_id: str
    league_id: str
    day: str


class UpcomingCaptureMetadata(BaseModel):
    """Upcoming API 호출 한 번의 응답과 분석 결과를 설명하는 메타데이터입니다."""

    schema_version: Literal[1] = 1
    discovery_run_id: str
    captured_at: datetime
    provider: str
    endpoint: str
    http_method: str
    query: UpcomingRequestQuery
    response_analysis_status: Literal[
        "completed", "invalid_json", "invalid_response_shape"
    ]
    returned_event_ids: list[str]
    response_issues: list[UpcomingResponseIssue]
    http_status_code: int = Field(ge=100, le=599)
    elapsed_ms: float = Field(ge=0)
    response_size_bytes: int = Field(ge=0)
    content_type: str | None
    raw_file_path: str


class UpcomingDiscoveryTarget(BaseModel):
    """Discovery 실행에서 조회하도록 설정된 하나의 종목·리그 조합입니다."""

    sport_id: str
    sport_code: str
    league_id: str
    league_label: str


class UpcomingLeague(BaseModel):
    """Upcoming 응답에서 추출한 리그 식별 정보입니다."""

    id: str
    name: str | None
    country_code: str | None


class UpcomingParticipant(BaseModel):
    """Upcoming 응답에서 추출한 홈 또는 원정 참가자 정보입니다."""

    id: str | None
    name: str | None


class DiscoveredUpcomingEvent(BaseModel):
    """watch 대상을 선택할 때 사용하는 예정 경기의 요약과 원문 참조입니다."""

    event_id: str
    sport_id: str
    sport_code: str
    time_status: str | None
    scheduled_at_utc: datetime
    scheduled_at_kst: datetime
    league: UpcomingLeague
    home: UpcomingParticipant
    away: UpcomingParticipant
    source_capture_metadata_file_path: str
    result_index: int = Field(ge=0)


class UpcomingDiscoveryFailure(BaseModel):
    """Discovery 실행 중 특정 조회 대상을 처리하지 못한 내역입니다."""

    sport_id: str
    league_id: str
    league_label: str
    error_type: str
    error_message: str


class UpcomingDiscovery(BaseModel):
    """여러 Upcoming 호출의 결과를 한 번에 탐색하기 위한 통합 기록입니다."""

    schema_version: Literal[1] = 1
    discovery_run_id: str
    status: Literal["completed", "partial", "failed"]
    started_at: datetime
    completed_at: datetime
    target_date: date
    requested_targets: list[UpcomingDiscoveryTarget]
    capture_metadata_file_paths: list[str]
    events: list[DiscoveredUpcomingEvent]
    failures: list[UpcomingDiscoveryFailure]
