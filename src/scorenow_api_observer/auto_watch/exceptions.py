import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, field_validator

from scorenow_api_observer.auto_watch.models import AutoWatchActiveEvent

AUTO_WATCH_EXCEPTION_DIRECTORY = Path("data/exceptions/auto-watch")
KST = ZoneInfo("Asia/Seoul")


class AutoWatchExceptionRecord(BaseModel):
    """정상 종료가 아닌 상태에서 수집 상한에 도달한 이벤트 기록입니다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    event_id: str
    sport_code: str
    league_id: str
    league_label: str
    scheduled_at_utc: datetime
    scheduled_at_kst: datetime
    observation_started_at: datetime
    stopped_at: datetime
    stop_time_status: int | None
    last_capture_metadata_path: str | None

    @field_validator(
        "scheduled_at_utc",
        "observation_started_at",
        "stopped_at",
    )
    @classmethod
    def normalize_utc_datetime(cls, value: datetime) -> datetime:
        return _as_utc(value)

    @field_validator("scheduled_at_kst")
    @classmethod
    def normalize_kst_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("KST 예정 시각에는 시간대 정보가 필요합니다.")
        return value.astimezone(KST)


def build_auto_watch_exception_record(
    *,
    event: AutoWatchActiveEvent,
    stopped_at: datetime,
) -> AutoWatchExceptionRecord:
    """활성 이벤트의 고정된 중단 결정으로 예외 기록을 만듭니다."""

    return AutoWatchExceptionRecord(
        event_id=event.event_id,
        sport_code=event.sport_code,
        league_id=event.league_id,
        league_label=event.league_label,
        scheduled_at_utc=event.scheduled_at_utc,
        scheduled_at_kst=event.scheduled_at_utc.astimezone(KST),
        observation_started_at=event.added_at,
        stopped_at=stopped_at,
        stop_time_status=event.last_time_status,
        last_capture_metadata_path=event.last_capture_metadata_path,
    )


def build_auto_watch_exception_path(
    record: AutoWatchExceptionRecord,
    *,
    base_directory: Path = AUTO_WATCH_EXCEPTION_DIRECTORY,
) -> Path:
    """상태값, UTC 중단 날짜와 시각을 포함한 예외 기록 경로를 만듭니다."""

    stopped_at_utc = _as_utc(record.stopped_at)
    status_directory = (
        f"time-status-{record.stop_time_status}"
        if record.stop_time_status is not None
        else "time-status-unknown"
    )
    timestamp = stopped_at_utc.strftime("%Y%m%dT%H%M%S%fZ")
    safe_event_id = _to_safe_file_name(record.event_id)
    return (
        base_directory
        / status_directory
        / stopped_at_utc.strftime("%Y-%m-%d")
        / f"{timestamp}_{safe_event_id}.json"
    )


def save_auto_watch_exception_record(
    record: AutoWatchExceptionRecord,
    *,
    base_directory: Path = AUTO_WATCH_EXCEPTION_DIRECTORY,
) -> Path:
    """예외 기록을 재시도해도 같은 경로에 원자적으로 저장합니다."""

    output_path = build_auto_watch_exception_path(
        record,
        base_directory=base_directory,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            record.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Auto-watch 예외 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)


def _to_safe_file_name(value: str) -> str:
    safe_value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if not safe_value:
        raise ValueError(f"이벤트 ID를 안전한 파일명으로 변환할 수 없습니다: {value!r}")
    return safe_value
