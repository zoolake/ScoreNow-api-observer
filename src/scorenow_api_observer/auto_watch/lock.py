import errno
import fcntl
import os
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

AUTO_WATCH_LOCK_PATH = Path("data/state/auto-watch/auto-watch.lock")


class AutoWatchLockMetadata(BaseModel):
    """잠금을 보유한 Auto-watch 프로세스의 진단 정보입니다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    process_id: int = Field(gt=0)
    started_at: datetime
    host_name: str = Field(min_length=1)

    @field_validator("started_at")
    @classmethod
    def normalize_started_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Auto-watch 잠금 시작 시각에는 시간대 정보가 필요합니다.")
        return value.astimezone(UTC)


class AutoWatchAlreadyRunningError(RuntimeError):
    """다른 Auto-watch 프로세스가 이미 잠금을 보유하고 있습니다."""

    def __init__(
        self,
        *,
        file_path: Path,
        metadata: AutoWatchLockMetadata | None,
    ) -> None:
        super().__init__("Auto-watch가 이미 실행 중입니다.")
        self.file_path = file_path
        self.metadata = metadata


@dataclass
class AutoWatchProcessLock:
    """프로세스가 실행되는 동안 열어 두는 운영체제 파일 잠금입니다."""

    file_path: Path
    metadata: AutoWatchLockMetadata
    _file: IO[str] = field(repr=False)

    def release(self) -> None:
        """잠금을 해제하고 파일 설명자를 닫습니다."""

        if self._file.closed:
            return
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exception_details: object) -> None:
        self.release()


def acquire_auto_watch_process_lock(
    *,
    now: datetime,
    process_id: int | None = None,
    host_name: str | None = None,
    file_path: Path = AUTO_WATCH_LOCK_PATH,
) -> AutoWatchProcessLock:
    """기다리지 않고 Auto-watch 전용 파일 잠금을 획득합니다."""

    normalized_now = _as_utc(now)
    metadata = AutoWatchLockMetadata(
        process_id=process_id if process_id is not None else os.getpid(),
        started_at=normalized_now,
        host_name=host_name or socket.gethostname() or "unknown",
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = file_path.open("a+", encoding="utf-8")

    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno not in (errno.EACCES, errno.EAGAIN):
            lock_file.close()
            raise
        existing_metadata = _read_lock_metadata(lock_file)
        lock_file.close()
        raise AutoWatchAlreadyRunningError(
            file_path=file_path,
            metadata=existing_metadata,
        ) from error

    try:
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(metadata.model_dump_json(indent=2) + "\n")
        lock_file.flush()
        os.fsync(lock_file.fileno())
    except BaseException:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
        raise

    return AutoWatchProcessLock(
        file_path=file_path,
        metadata=metadata,
        _file=lock_file,
    )


def _read_lock_metadata(lock_file: IO[str]) -> AutoWatchLockMetadata | None:
    try:
        lock_file.seek(0)
        return AutoWatchLockMetadata.model_validate_json(lock_file.read())
    except OSError, UnicodeError, ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Auto-watch 잠금 시작 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)
