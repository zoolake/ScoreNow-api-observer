from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

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


UpcomingDiscoveryStatus = Literal["completed", "partial", "failed"]


class LeagueUpcomingDiscovery(BaseModel):
    """한 리그에 대한 한 번의 Upcoming 조회 결과입니다."""

    schema_version: Literal[1] = 1
    discovery_run_id: str
    status: UpcomingDiscoveryStatus
    completed_at: datetime
    target_date: date
    target: UpcomingDiscoveryTarget
    capture_metadata_file_path: str | None
    events: list[DiscoveredUpcomingEvent]
    failure: UpcomingDiscoveryFailure | None

    @model_validator(mode="after")
    def validate_status_details(self) -> Self:
        if self.status == "failed" and self.failure is None:
            raise ValueError("failed 리그 Discovery에는 실패 내역이 필요합니다.")
        if self.status == "failed" and self.events:
            raise ValueError("failed 리그 Discovery에는 이벤트를 둘 수 없습니다.")
        if self.status != "failed" and self.failure is not None:
            raise ValueError(
                "completed 또는 partial 리그 Discovery에는 실패 내역을 둘 수 없습니다."
            )
        if self.status != "failed" and self.capture_metadata_file_path is None:
            raise ValueError(
                "completed 또는 partial 리그 Discovery에는 CaptureMetadata 경로가 "
                "필요합니다."
            )
        return self


class UpcomingDiscoveryRun(BaseModel):
    """한 번의 discover-upcoming 명령 실행과 리그별 결과 파일의 목록입니다."""

    schema_version: Literal[1] = 1
    discovery_run_id: str
    status: UpcomingDiscoveryStatus
    started_at: datetime
    completed_at: datetime
    target_date: date
    requested_targets: list[UpcomingDiscoveryTarget]
    league_discovery_file_paths: list[str]

    @model_validator(mode="after")
    def validate_target_file_count(self) -> Self:
        if len(self.requested_targets) != len(self.league_discovery_file_paths):
            raise ValueError(
                "요청 대상 수와 리그 Discovery 파일 경로 수가 일치해야 합니다."
            )
        return self
