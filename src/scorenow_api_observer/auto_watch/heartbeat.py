from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

AUTO_WATCH_HEARTBEAT_PATH = Path("data/state/auto-watch/heartbeat.json")

AutoWatchHeartbeatStatus = Literal["running", "stopped", "failed"]


class AutoWatchHeartbeat(BaseModel):
    """Auto-watch 프로세스의 시작·최근 처리·종료 상태입니다."""

    schema_version: Literal[1] = 1
    status: AutoWatchHeartbeatStatus = "running"
    process_id: int = Field(gt=0)
    process_started_at: datetime
    last_cycle_at: datetime
    interval_seconds: int = Field(gt=0)
    stopped_at: datetime | None = None
    failure_message: str | None = None

    @field_validator("process_started_at", "last_cycle_at", "stopped_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Auto-watch Heartbeat 시각에는 시간대 정보가 필요합니다.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_status_details(self) -> Self:
        if self.status == "running":
            if self.stopped_at is not None or self.failure_message is not None:
                raise ValueError(
                    "실행 중 Heartbeat에는 종료 정보를 기록할 수 없습니다."
                )
            return self
        if self.stopped_at is None:
            raise ValueError("종료된 Heartbeat에는 종료 시각이 필요합니다.")
        if self.status == "failed" and not self.failure_message:
            raise ValueError("실패한 Heartbeat에는 실패 내용이 필요합니다.")
        if self.status == "stopped" and self.failure_message is not None:
            raise ValueError("정상 중단 Heartbeat에는 실패 내용을 기록할 수 없습니다.")
        return self


def new_auto_watch_heartbeat(
    *,
    now: datetime,
    interval_seconds: int,
    process_id: int,
) -> AutoWatchHeartbeat:
    normalized_now = _as_utc(now)
    return AutoWatchHeartbeat(
        process_id=process_id,
        process_started_at=normalized_now,
        last_cycle_at=normalized_now,
        interval_seconds=interval_seconds,
    )


def touch_auto_watch_heartbeat(
    heartbeat: AutoWatchHeartbeat,
    *,
    now: datetime,
) -> None:
    """새 처리 주기의 시작 시각을 Heartbeat에 반영합니다."""

    heartbeat.last_cycle_at = _as_utc(now)


def finish_auto_watch_heartbeat(
    heartbeat: AutoWatchHeartbeat,
    *,
    now: datetime,
    failed: bool,
    failure_message: str | None = None,
) -> None:
    """Auto-watch의 정상 중단 또는 실패를 Heartbeat에 반영합니다."""

    normalized_now = _as_utc(now)
    heartbeat.status = "failed" if failed else "stopped"
    heartbeat.stopped_at = normalized_now
    heartbeat.failure_message = failure_message if failed else None


def load_auto_watch_heartbeat(
    file_path: Path = AUTO_WATCH_HEARTBEAT_PATH,
) -> AutoWatchHeartbeat | None:
    if not file_path.exists():
        return None
    return AutoWatchHeartbeat.model_validate_json(file_path.read_text(encoding="utf-8"))


def save_auto_watch_heartbeat(
    heartbeat: AutoWatchHeartbeat,
    file_path: Path = AUTO_WATCH_HEARTBEAT_PATH,
) -> Path:
    """Heartbeat를 같은 디렉터리 안에서 원자적으로 교체합니다."""

    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = file_path.with_name(f".{file_path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            heartbeat.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(file_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return file_path


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Auto-watch Heartbeat 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)
