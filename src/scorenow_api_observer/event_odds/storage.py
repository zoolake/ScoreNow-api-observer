import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from scorenow_api_observer.event_odds.models import OddsSnapshotMetadata

ODDS_RAW_DATA_DIRECTORY = Path("data/raw/event-odds")
ODDS_METADATA_DIRECTORY = Path("data/metadata/event-odds")


def save_event_odds_raw_response(
    *,
    response_body: bytes,
    event_id: str,
    captured_at: datetime,
    base_directory: Path = ODDS_RAW_DATA_DIRECTORY,
) -> Path:
    """이벤트의 Event Odds 원문을 UTC 날짜별 최신 파일로 교체합니다."""

    output_path = _build_daily_event_path(
        base_directory=base_directory,
        event_id=event_id,
        captured_at=captured_at,
    )
    _replace_file_bytes(output_path=output_path, content=response_body)
    return output_path


def build_event_odds_raw_response_path(
    *,
    event_id: str,
    captured_at: datetime,
    base_directory: Path = ODDS_RAW_DATA_DIRECTORY,
) -> Path:
    """이벤트의 UTC 날짜별 최신 Event Odds 원문 경로를 계산합니다."""

    return _build_daily_event_path(
        base_directory=base_directory,
        event_id=event_id,
        captured_at=captured_at,
    )


def save_event_odds_snapshot_metadata(
    metadata: OddsSnapshotMetadata,
    *,
    base_directory: Path = ODDS_METADATA_DIRECTORY,
) -> Path:
    """Event Odds SnapshotMetadata를 원문과 같은 UTC 날짜·이벤트명으로 교체합니다."""

    output_path = _build_daily_event_path(
        base_directory=base_directory,
        event_id=metadata.query.event_id,
        captured_at=metadata.captured_at,
    )
    content = (metadata.model_dump_json(indent=2) + "\n").encode()
    _replace_file_bytes(output_path=output_path, content=content)
    return output_path


def save_event_odds_snapshot(
    *,
    response_body: bytes,
    metadata: OddsSnapshotMetadata,
    raw_base_directory: Path = ODDS_RAW_DATA_DIRECTORY,
    metadata_base_directory: Path = ODDS_METADATA_DIRECTORY,
) -> tuple[Path, Path]:
    """원문과 메타데이터를 교체하고 후자 실패 시 이전 원문을 복구합니다."""

    raw_file_path = build_event_odds_raw_response_path(
        event_id=metadata.query.event_id,
        captured_at=metadata.captured_at,
        base_directory=raw_base_directory,
    )
    raw_file_existed = raw_file_path.is_file()
    previous_raw_response = raw_file_path.read_bytes() if raw_file_existed else None

    saved_raw_file_path = save_event_odds_raw_response(
        response_body=response_body,
        event_id=metadata.query.event_id,
        captured_at=metadata.captured_at,
        base_directory=raw_base_directory,
    )
    try:
        metadata_file_path = save_event_odds_snapshot_metadata(
            metadata,
            base_directory=metadata_base_directory,
        )
    except (OSError, ValueError) as storage_error:
        try:
            if previous_raw_response is None:
                saved_raw_file_path.unlink(missing_ok=True)
            else:
                _replace_file_bytes(
                    output_path=saved_raw_file_path,
                    content=previous_raw_response,
                )
        except OSError as rollback_error:
            raise OSError(
                "Event Odds 메타데이터 저장과 기존 원문 복구에 모두 실패했습니다: "
                f"metadata_error={storage_error}; rollback_error={rollback_error}"
            ) from rollback_error
        raise

    return saved_raw_file_path, metadata_file_path


def _build_daily_event_path(
    *,
    base_directory: Path,
    event_id: str,
    captured_at: datetime,
) -> Path:
    captured_at_utc = _as_utc(captured_at)
    safe_event_id = _to_safe_file_name(event_id)
    return (
        base_directory / captured_at_utc.strftime("%Y-%m-%d") / f"{safe_event_id}.json"
    )


def _replace_file_bytes(*, output_path: Path, content: bytes) -> None:
    """같은 디렉터리의 임시 파일을 완성한 뒤 대상 파일을 원자적으로 교체합니다."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(content)
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("저장 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(UTC)


def _to_safe_file_name(value: str) -> str:
    safe_value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if not safe_value:
        raise ValueError(f"이벤트 ID를 안전한 파일명으로 변환할 수 없습니다: {value!r}")
    return safe_value
