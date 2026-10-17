from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scorenow_api_observer.upcoming_models import (
    UpcomingCaptureMetadata,
    UpcomingDiscovery,
)

UPCOMING_RAW_DATA_DIRECTORY = Path("data/raw/events-upcoming")
UPCOMING_METADATA_DIRECTORY = Path("data/metadata/events-upcoming")
UPCOMING_DISCOVERY_DIRECTORY = Path("data/discoveries/events-upcoming")
KST = ZoneInfo("Asia/Seoul")


def save_upcoming_raw_response(
    *,
    response_body: bytes,
    captured_at: datetime,
    league_label: str,
    base_directory: Path = UPCOMING_RAW_DATA_DIRECTORY,
) -> Path:
    """Upcoming 응답 원문을 KST 호출 날짜와 리그 label 기준으로 저장합니다."""

    kst_captured_at = _as_kst(captured_at)
    output_directory = base_directory / kst_captured_at.strftime("%Y-%m-%d")
    output_directory.mkdir(parents=True, exist_ok=True)

    output_path = output_directory / _capture_file_name(
        league_label=league_label,
        kst_captured_at=kst_captured_at,
    )
    with output_path.open("xb") as output_file:
        output_file.write(response_body)

    return output_path


def save_upcoming_capture_metadata(
    metadata: UpcomingCaptureMetadata,
    *,
    base_directory: Path = UPCOMING_METADATA_DIRECTORY,
) -> Path:
    """Upcoming CaptureMetadata를 원문과 동일한 KST 날짜·파일명으로 저장합니다."""

    kst_captured_at = _as_kst(metadata.captured_at)
    output_directory = base_directory / kst_captured_at.strftime("%Y-%m-%d")
    output_directory.mkdir(parents=True, exist_ok=True)

    output_path = output_directory / Path(metadata.raw_file_path).name
    metadata_json = metadata.model_dump_json(indent=2)
    with output_path.open("x", encoding="utf-8") as output_file:
        output_file.write(metadata_json + "\n")

    return output_path


def save_upcoming_discovery(
    discovery: UpcomingDiscovery,
    *,
    base_directory: Path = UPCOMING_DISCOVERY_DIRECTORY,
) -> Path:
    """통합 Discovery를 UTC target_date별 디렉터리에 중복 없이 저장합니다."""

    output_directory = base_directory / discovery.target_date.isoformat()
    output_directory.mkdir(parents=True, exist_ok=True)

    output_path = output_directory / f"{discovery.discovery_run_id}_discovery.json"
    discovery_json = discovery.model_dump_json(indent=2)
    with output_path.open("x", encoding="utf-8") as output_file:
        output_file.write(discovery_json + "\n")

    return output_path


def _capture_file_name(*, league_label: str, kst_captured_at: datetime) -> str:
    timestamp = kst_captured_at.strftime("%Y-%m-%dT%H-%M-%S")
    return f"{league_label}_{timestamp}_KST_capture.json"


def _as_kst(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("저장 시각에는 시간대 정보가 필요합니다.")
    return value.astimezone(KST)
