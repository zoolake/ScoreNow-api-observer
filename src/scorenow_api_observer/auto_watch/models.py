from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from scorenow_api_observer.auto_watch.config import AutoWatchTimeLimitedStatusGroup


class AutoWatchActiveEvent(BaseModel):
    """재시작 후에도 이어서 수집할 활성 이벤트입니다."""

    event_id: str = Field(min_length=1)
    sport_code: str = Field(min_length=1)
    league_id: str = Field(min_length=1)
    league_label: str = Field(min_length=1)
    scheduled_at_utc: datetime
    added_at: datetime
    finished_detected_at: datetime | None = None
    last_time_status: int | None = None
    status_policy_group: AutoWatchTimeLimitedStatusGroup | None = None
    status_policy_started_at: datetime | None = None
    last_capture_metadata_path: str | None = None
    stop_decided_at: datetime | None = None

    @field_validator("status_policy_group", mode="before")
    @classmethod
    def migrate_legacy_status_policy_group(cls, value: object) -> object:
        legacy_values = {
            "prestart": "waiting_to_start",
            "resumable": "temporarily_stopped",
        }
        return legacy_values.get(value, value) if isinstance(value, str) else value

    @field_validator(
        "scheduled_at_utc",
        "added_at",
        "finished_detected_at",
        "status_policy_started_at",
        "stop_decided_at",
    )
    @classmethod
    def validate_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("자동 수집 상태 시각에는 시간대 정보가 필요합니다.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_status_policy_state(self) -> Self:
        if (self.status_policy_group is None) != (
            self.status_policy_started_at is None
        ):
            raise ValueError(
                "상태 정책 그룹과 최초 감지 시각은 함께 저장되어야 합니다."
            )
        if (
            self.finished_detected_at is not None
            and self.status_policy_group is not None
        ):
            raise ValueError(
                "종료 감지와 종료 외 상태 정책은 동시에 활성화할 수 없습니다."
            )
        return self


class AutoWatchState(BaseModel):
    """auto-watch의 재시작 복구에 사용하는 활성 이벤트 목록입니다."""

    schema_version: Literal[1, 2, 3] = 3
    updated_at: datetime
    active_events: list[AutoWatchActiveEvent]

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("자동 수집 상태 갱신 시각에는 시간대 정보가 필요합니다.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_unique_event_ids(self) -> Self:
        event_ids = [event.event_id for event in self.active_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("자동 수집 상태에 중복 이벤트 ID가 있습니다.")
        return self
