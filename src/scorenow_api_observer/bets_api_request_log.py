from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

BETS_API_REQUEST_LOG_DIRECTORY = Path("data/metrics/bets-api-requests")

BetsApiEndpoint = Literal[
    "/v1/event/view",
    "/v3/events/upcoming",
    "/v2/event/odds",
]
RequestCategory = Literal[
    "football_only",
    "baseball_only",
    "mixed",
    "unknown",
]
RequestOutcome = Literal[
    "started",
    "completed",
    "request_error",
]


class RequestedEvent(BaseModel):
    """요청에 포함된 이벤트 ID와 확인 가능한 종목 정보입니다."""

    event_id: str = Field(min_length=1)
    sport_code: str | None = None


class EventViewRequestDetails(BaseModel):
    """Event View 요청에서 토큰을 제외하고 보존할 입력값입니다."""

    kind: Literal["event_view"] = "event_view"
    requested_events: list[RequestedEvent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_event_ids(self) -> Self:
        event_ids = [event.event_id for event in self.requested_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("API 요청 기록에 중복 이벤트 ID가 있습니다.")
        return self


class UpcomingRequestDetails(BaseModel):
    """Upcoming 요청에서 토큰을 제외하고 보존할 입력값입니다."""

    kind: Literal["upcoming"] = "upcoming"
    sport_id: str = Field(min_length=1)
    sport_code: str = Field(min_length=1)
    league_id: str = Field(min_length=1)
    league_label: str = Field(min_length=1)
    target_date: date


class EventOddsRequestDetails(BaseModel):
    """Event Odds 요청에서 토큰을 제외하고 보존할 입력값입니다."""

    kind: Literal["event_odds"] = "event_odds"
    event_id: str = Field(min_length=1)
    sport_code: str | None = None
    odds_markets: list[int] = Field(min_length=1)

    @field_validator("odds_markets")
    @classmethod
    def validate_unique_odds_markets(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("API 요청 기록에 중복 배당 마켓이 있습니다.")
        return value


BetsApiRequestDetails = Annotated[
    EventViewRequestDetails | UpcomingRequestDetails | EventOddsRequestDetails,
    Field(discriminator="kind"),
]


class RateLimitSnapshot(BaseModel):
    """BETS 응답의 X-RateLimit 헤더를 해석한 시점별 한도 정보입니다."""

    limit: int | None = Field(default=None, ge=0)
    remaining: int | None = Field(default=None, ge=0)
    reset_at: datetime | None = None

    @field_validator("reset_at")
    @classmethod
    def validate_reset_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("요청 한도 초기화 시각에는 시간대 정보가 필요합니다.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_at_least_one_value(self) -> Self:
        if self.limit is None and self.remaining is None and self.reset_at is None:
            raise ValueError("요청 한도 정보에는 하나 이상의 값이 필요합니다.")
        return self


class BetsApiRequestRecord(BaseModel):
    """BETS API HTTP 요청 한 건의 시작과 결과 기록입니다."""

    schema_version: Literal[1] = 1
    request_id: str = Field(min_length=1)
    requested_at: datetime
    completed_at: datetime | None = None
    provider: Literal["betsapi"] = "betsapi"
    endpoint: BetsApiEndpoint
    http_method: Literal["GET"] = "GET"
    request_category: RequestCategory
    request: BetsApiRequestDetails
    outcome: RequestOutcome = "started"
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    error_type: str | None = None
    rate_limit: RateLimitSnapshot | None = None

    @field_validator("requested_at", "completed_at")
    @classmethod
    def validate_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("API 요청 기록 시각에는 시간대 정보가 필요합니다.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_request_and_result(self) -> Self:
        expected_endpoint = _endpoint_for_request(self.request)
        if self.endpoint != expected_endpoint:
            raise ValueError("endpoint와 요청 상세 종류가 일치하지 않습니다.")

        expected_category = _category_for_request(self.request)
        if self.request_category != expected_category:
            raise ValueError("요청 상세의 종목과 request_category가 일치하지 않습니다.")

        if self.outcome == "started":
            if self.completed_at is not None:
                raise ValueError("started 요청에는 완료 시각을 기록할 수 없습니다.")
            if (
                self.http_status_code is not None
                or self.error_type is not None
                or self.rate_limit is not None
            ):
                raise ValueError("started 요청에는 결과를 기록할 수 없습니다.")
            return self

        if self.completed_at is None:
            raise ValueError("완료된 요청 기록에는 완료 시각이 필요합니다.")
        if self.outcome == "completed" and self.http_status_code is None:
            raise ValueError("completed 요청에는 HTTP 상태 코드가 필요합니다.")
        if self.outcome == "request_error" and not self.error_type:
            raise ValueError("연결 실패 요청 기록에는 오류 유형이 필요합니다.")
        return self


@dataclass(frozen=True)
class BetsApiRequestHandle:
    """요청 시작 기록과 나중에 같은 파일을 갱신할 경로입니다."""

    record: BetsApiRequestRecord
    file_path: Path


def classify_request_category(
    requested_events: list[RequestedEvent],
) -> RequestCategory:
    """요청 이벤트의 종목 조합을 호출 횟수 집계 범주로 분류합니다."""

    return classify_sport_codes([event.sport_code for event in requested_events])


def classify_sport_codes(sport_codes: list[str | None]) -> RequestCategory:
    """요청에 포함된 종목 코드 조합을 호출 횟수 집계 범주로 분류합니다."""

    normalized_codes = set(sport_codes)
    if normalized_codes == {"football"}:
        return "football_only"
    if normalized_codes == {"baseball"}:
        return "baseball_only"
    if normalized_codes == {"football", "baseball"}:
        return "mixed"
    return "unknown"


def start_bets_api_request(
    *,
    request: BetsApiRequestDetails,
    requested_at: datetime,
    base_directory: Path = BETS_API_REQUEST_LOG_DIRECTORY,
) -> BetsApiRequestHandle:
    """실제 HTTP 호출 전에 토큰 없는 BETS API 요청 시작 기록을 저장합니다."""

    normalized_requested_at = _as_utc(requested_at)
    request_id = uuid4().hex
    record = BetsApiRequestRecord(
        request_id=request_id,
        requested_at=normalized_requested_at,
        endpoint=_endpoint_for_request(request),
        request_category=_category_for_request(request),
        request=request,
    )
    output_directory = base_directory / normalized_requested_at.date().isoformat()
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"{request_id}.json"
    with output_path.open("x", encoding="utf-8") as output_file:
        output_file.write(record.model_dump_json(indent=2) + "\n")
    return BetsApiRequestHandle(record=record, file_path=output_path)


def finish_bets_api_request(
    *,
    handle: BetsApiRequestHandle,
    completed_at: datetime,
    outcome: Literal["completed", "request_error"],
    http_status_code: int | None = None,
    error_type: str | None = None,
    rate_limit: RateLimitSnapshot | None = None,
) -> BetsApiRequestRecord:
    """요청 시작 파일을 결과가 포함된 최종 기록으로 원자적으로 교체합니다."""

    record_data = handle.record.model_dump(mode="python")
    record_data.update(
        completed_at=_as_utc(completed_at),
        outcome=outcome,
        http_status_code=http_status_code,
        error_type=error_type,
        rate_limit=rate_limit,
    )
    completed_record = BetsApiRequestRecord.model_validate(record_data)
    _replace_record_file(completed_record, handle.file_path)
    return completed_record


def parse_rate_limit_headers(headers: Mapping[str, str]) -> RateLimitSnapshot | None:
    """응답 헤더에 포함된 유효한 X-RateLimit 값을 가능한 범위에서 읽습니다."""

    normalized_headers = {key.lower(): value for key, value in headers.items()}
    limit = _parse_nonnegative_int(normalized_headers.get("x-ratelimit-limit"))
    remaining = _parse_nonnegative_int(normalized_headers.get("x-ratelimit-remaining"))
    reset_epoch = _parse_nonnegative_int(normalized_headers.get("x-ratelimit-reset"))
    reset_at = (
        datetime.fromtimestamp(reset_epoch, tz=UTC) if reset_epoch is not None else None
    )
    if limit is None and remaining is None and reset_at is None:
        return None
    return RateLimitSnapshot(
        limit=limit,
        remaining=remaining,
        reset_at=reset_at,
    )


def _endpoint_for_request(request: BetsApiRequestDetails) -> BetsApiEndpoint:
    if request.kind == "event_view":
        return "/v1/event/view"
    if request.kind == "upcoming":
        return "/v3/events/upcoming"
    return "/v2/event/odds"


def _category_for_request(request: BetsApiRequestDetails) -> RequestCategory:
    if request.kind == "event_view":
        return classify_request_category(request.requested_events)
    return classify_sport_codes([request.sport_code])


def _replace_record_file(record: BetsApiRequestRecord, file_path: Path) -> None:
    temporary_path = file_path.with_name(f".{file_path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            record.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(file_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("API 요청 기록 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)


def _parse_nonnegative_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed_value = int(value)
    except ValueError:
        return None
    return parsed_value if parsed_value >= 0 else None
