import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from scorenow_api_observer.event_view_response import analyze_event_view_response
from scorenow_api_observer.models import CaptureMetadata, StructureChangeRecord

RAW_DATA_DIRECTORY = Path("data/raw/event-view")
METADATA_DIRECTORY = Path("data/metadata/event-view")
STRUCTURE_CHANGE_DIRECTORY = Path("data/changes/event-view")


def save_raw_response(
    event_id: str,
    response_body: bytes,
    captured_at: datetime,
    base_directory: Path = RAW_DATA_DIRECTORY,
) -> Path:
    """API 응답 원문을 호출 날짜별 디렉터리에 저장합니다."""

    date_directory = captured_at.strftime("%Y-%m-%d")
    timestamp = captured_at.strftime("%Y%m%dT%H%M%S%fZ")
    safe_event_id = _to_safe_file_name(event_id)

    output_directory = base_directory / date_directory
    output_directory.mkdir(
        parents=True,  # 상위폴더가 없으면 같이 생성
        exist_ok=True,  # 이미 존재해도 오류 발생 X
    )

    output_path = output_directory / f"{timestamp}_event-{safe_event_id}.json"
    output_path.write_bytes(response_body)

    return output_path


def save_capture_metadata(
    metadata: CaptureMetadata, base_directory: Path = METADATA_DIRECTORY
) -> Path:
    """API 호출 기록을 원문과 동일한 파일명으로 저장합니다."""

    date_directory = metadata.captured_at.strftime("%Y-%m-%d")

    output_directory = base_directory / date_directory
    output_directory.mkdir(parents=True, exist_ok=True)

    raw_file_name = Path(metadata.raw_file_path).name
    output_path = output_directory / raw_file_name

    metadata_json = metadata.model_dump_json(indent=2)
    output_path.write_text(metadata_json + "\n", encoding="utf-8")

    return output_path


def save_structure_change_record(
    record: StructureChangeRecord,
    base_directory: Path = STRUCTURE_CHANGE_DIRECTORY,
) -> Path:
    """응답 구조 변경 정보를 저장합니다."""

    date_directory = record.current_captured_at.strftime("%Y-%m-%d")

    output_directory = base_directory / date_directory
    output_directory.mkdir(parents=True, exist_ok=True)

    raw_file_name = Path(record.current_raw_file_path).name
    output_path = output_directory / raw_file_name

    record_json = record.model_dump_json(indent=2)

    try:
        with output_path.open("x", encoding="utf-8") as f:
            f.write(record_json + "\n")
    except FileExistsError:
        pass

    return output_path


def load_json_file(file_path: Path) -> Any:
    """저장된 원문 JSON 파일을 읽습니다."""

    file_text = file_path.read_text(encoding="utf-8")
    return json.loads(file_text)


def load_capture_metadata(metadata_path: Path) -> CaptureMetadata:
    metadata_text = metadata_path.read_text(encoding="utf-8")
    metadata_json = json.loads(metadata_text)

    if "schema_version" not in metadata_json:
        requested_event_ids: list[str] = metadata_json["event_ids"]

        raw_file_path = metadata_json["raw_file_path"]
        raw_file = load_json_file(Path(raw_file_path))

        event_view_response_analysis = analyze_event_view_response(
            requested_event_ids=requested_event_ids, response_json=raw_file
        )

        return CaptureMetadata(
            captured_at=metadata_json["captured_at"],
            provider=metadata_json["provider"],
            endpoint=metadata_json["endpoint"],
            http_method=metadata_json["http_method"],
            requested_event_ids=requested_event_ids,
            returned_event_ids=event_view_response_analysis.returned_event_ids,
            response_issues=event_view_response_analysis.issues,
            http_status_code=metadata_json["http_status_code"],
            elapsed_ms=metadata_json["elapsed_ms"],
            response_size_bytes=metadata_json["response_size_bytes"],
            content_type=metadata_json["content_type"],
            raw_file_path=raw_file_path,
        )

    return CaptureMetadata.model_validate(metadata_json)


def _to_safe_file_name(value: str) -> str:
    """문자열을 파일명에 안전하게 사용할 수 있도록 변환합니다."""

    safe_value = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        value,
    )

    safe_value = safe_value.strip("._")
    return safe_value or "unknown"
