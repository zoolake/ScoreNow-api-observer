from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

EVENT_VIEW_REQUEST_LOG_DIRECTORY = Path("data/metrics/event-view-api-requests")

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
    """집계값 대신 보존하는 요청 이벤트의 원본 분류 정보입니다."""

    event_id: str = Field(min_length=1)
    sport_code: str | None = None


class EventViewApiRequestRecord(BaseModel):
    """Event View HTTP 요청 한 건의 시작과 결과 기록입니다."""

    schema_version: Literal[1] = 1
    request_id: str = Field(min_length=1)
    requested_at: datetime
    completed_at: datetime | None = None
    provider: Literal["betsapi"] = "betsapi"
    endpoint: Literal["/v1/event/view"] = "/v1/event/view"
    http_method: Literal["GET"] = "GET"
    request_category: RequestCategory
    requested_events: list[RequestedEvent] = Field(min_length=1)
    outcome: RequestOutcome = "started"
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    error_type: str | None = None

    @field_validator("requested_at", "completed_at")
    @classmethod
    def validate_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("API 요청 기록 시각에는 시간대 정보가 필요합니다.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_outcome_details(self) -> Self:
        event_ids = [event.event_id for event in self.requested_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("API 요청 기록에 중복 이벤트 ID가 있습니다.")

        if self.outcome == "started":
            if self.completed_at is not None:
                raise ValueError("started 요청에는 완료 시각을 기록할 수 없습니다.")
            if self.http_status_code is not None or self.error_type is not None:
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
class EventViewApiRequestHandle:
    """요청 시작 기록과 나중에 같은 파일을 갱신할 경로입니다."""

    record: EventViewApiRequestRecord
    file_path: Path


def classify_request_category(
    requested_events: list[RequestedEvent],
) -> RequestCategory:
    """요청에 포함된 종목 조합을 호출 횟수 집계 범주로 분류합니다."""

    sport_codes = {event.sport_code for event in requested_events}
    if sport_codes == {"football"}:
        return "football_only"
    if sport_codes == {"baseball"}:
        return "baseball_only"
    if sport_codes == {"football", "baseball"}:
        return "mixed"
    return "unknown"


def start_event_view_api_request(
    *,
    requested_events: list[RequestedEvent],
    requested_at: datetime,
    base_directory: Path = EVENT_VIEW_REQUEST_LOG_DIRECTORY,
) -> EventViewApiRequestHandle:
    """실제 HTTP 호출 전에 Event View 요청 시작 기록을 저장합니다."""

    normalized_requested_at = _as_utc(requested_at)
    request_id = uuid4().hex
    record = EventViewApiRequestRecord(
        request_id=request_id,
        requested_at=normalized_requested_at,
        request_category=classify_request_category(requested_events),
        requested_events=requested_events,
    )
    output_directory = base_directory / normalized_requested_at.date().isoformat()
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"{request_id}.json"
    with output_path.open("x", encoding="utf-8") as output_file:
        output_file.write(record.model_dump_json(indent=2) + "\n")
    return EventViewApiRequestHandle(record=record, file_path=output_path)


def finish_event_view_api_request(
    *,
    handle: EventViewApiRequestHandle,
    completed_at: datetime,
    outcome: Literal["completed", "request_error"],
    http_status_code: int | None = None,
    error_type: str | None = None,
) -> EventViewApiRequestRecord:
    """요청 시작 파일을 결과가 포함된 최종 기록으로 원자적으로 교체합니다."""

    record_data = handle.record.model_dump(mode="python")
    record_data.update(
        completed_at=_as_utc(completed_at),
        outcome=outcome,
        http_status_code=http_status_code,
        error_type=error_type,
    )
    completed_record = EventViewApiRequestRecord.model_validate(record_data)
    _replace_record_file(completed_record, handle.file_path)
    return completed_record


def _replace_record_file(record: EventViewApiRequestRecord, file_path: Path) -> None:
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
