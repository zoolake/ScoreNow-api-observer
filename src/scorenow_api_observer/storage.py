import re
from datetime import datetime
from pathlib import Path

from scorenow_api_observer.models import CaptureMetadata

RAW_DATA_DIRECTORY = Path("data/raw/event-view")
METADATA_DIRECTORY = Path("data/metadata/event-view")


def save_raw_response(
    event_id: str,
    response_body: bytes,
    captured_at: datetime,
) -> Path:
    """API 응답 원문을 호출 날짜별 디렉터리에 저장합니다."""

    date_directory = captured_at.strftime("%Y-%m-%d")
    timestamp = captured_at.strftime("%Y%m%dT%H%M%S%fZ")
    safe_event_id = _to_safe_file_name(event_id)

    output_directory = RAW_DATA_DIRECTORY / date_directory
    output_directory.mkdir(
        parents=True,  # 상위폴더가 없으면 같이 생성
        exist_ok=True,  # 이미 존재해도 오류 발생 X
    )

    output_path = output_directory / f"{timestamp}_event-{safe_event_id}.json"
    output_path.write_bytes(response_body)

    return output_path


def save_capture_metadata(metadata: CaptureMetadata) -> Path:
    """API 호출 기록을 원문과 동일한 파일명으로 저장합니다."""

    date_directory = metadata.captured_at.strftime("%Y-%m-%d")

    output_directory = METADATA_DIRECTORY / date_directory
    output_directory.mkdir(parents=True, exist_ok=True)

    raw_file_name = Path(metadata.raw_file_path).name
    output_path = output_directory / raw_file_name

    metadata_json = metadata.model_dump_json(indent=2)
    output_path.write_text(metadata_json + "\n", encoding="utf-8")

    return output_path


def _to_safe_file_name(value: str) -> str:
    """문자열을 파일명에 안전하게 사용할 수 있도록 변환합니다."""

    safe_value = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        value,
    )

    safe_value = safe_value.strip("._")
    return safe_value or "unknown"
