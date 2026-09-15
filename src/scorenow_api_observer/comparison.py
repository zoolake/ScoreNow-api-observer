import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from scorenow_api_observer.models import (
    CaptureMetadata,
    StructureChangeRecord,
    TypeChangeRecord,
)
from scorenow_api_observer.storage import METADATA_DIRECTORY


@dataclass(frozen=True)
class TypeChange:
    """동일한 JSON 경로에서 발견된 자료형 변화입니다."""

    path: str
    previous_types: set[str]
    current_types: set[str]


@dataclass(frozen=True)
class StructureComparison:
    """두 JSON 구조를 비교한 결과입니다."""

    added_paths: list[str]
    removed_paths: list[str]
    type_changes: list[TypeChange]

    @property
    def has_changes(self) -> bool:
        return bool(self.added_paths or self.removed_paths or self.type_changes)


@dataclass(frozen=True)
class CaptureComparison:
    """특정 경기에 대한 응답 구조 비교 결과입니다."""

    event_id: str
    previous_capture: CaptureMetadata
    current_capture: CaptureMetadata
    structure_comparison: StructureComparison


def find_latest_captures(
    event_id: str,
    limit: int = 2,
    base_directory: Path = METADATA_DIRECTORY,
) -> list[CaptureMetadata]:
    """특정 경기의 최근 호출 기록을 찾습니다."""

    captures: list[CaptureMetadata] = []

    for metadata_path in base_directory.rglob("*.json"):
        metadata_text = metadata_path.read_text(encoding="utf-8")
        metadata = CaptureMetadata.model_validate_json(metadata_text)

        if event_id in metadata.event_ids:
            captures.append(metadata)

    captures.sort(key=lambda capture: capture.captured_at)

    return captures[-limit:]


def find_previous_capture(
    event_id: str,
    current_capture: CaptureMetadata,
    base_directory: Path = METADATA_DIRECTORY,
) -> CaptureMetadata | None:
    """전달받은 메타데이터의 직전 메타데이터를 찾습니다."""

    candidates: list[CaptureMetadata] = []

    for metadata_path in base_directory.rglob("*.json"):
        metadata_text = metadata_path.read_text(encoding="utf-8")
        metadata = CaptureMetadata.model_validate_json(metadata_text)

        if (
            event_id in metadata.event_ids
            and metadata.captured_at < current_capture.captured_at
        ):
            candidates.append(metadata)

    if len(candidates) == 0:
        return None

    candidates.sort(key=lambda candidate: candidate.captured_at)

    return candidates[-1]


def load_json_file(file_path: Path) -> Any:
    """저장된 원문 JSON 파일을 읽습니다."""

    file_text = file_path.read_text(encoding="utf-8")
    return json.loads(file_text)


def compare_json_structures(
    previous_data: Any,
    current_data: Any,
) -> StructureComparison:
    """두 JSON에서 발견되는 경로와 자료형을 비교합니다."""

    previous_structure = _extract_structure(previous_data)
    current_structure = _extract_structure(current_data)

    previous_paths = set(previous_structure)
    current_paths = set(current_structure)

    added_paths = sorted(current_paths - previous_paths)
    removed_paths = sorted(previous_paths - current_paths)

    common_paths = previous_paths & current_paths
    type_changes = []
    for path in sorted(common_paths):
        previous_types = previous_structure[path]
        current_types = current_structure[path]

        if previous_types != current_types:
            type_changes.append(
                TypeChange(
                    path=path,
                    previous_types=previous_types,
                    current_types=current_types,
                )
            )

    return StructureComparison(
        added_paths=added_paths,
        removed_paths=removed_paths,
        type_changes=type_changes,
    )


def compare_with_previous_capture(
    event_id: str,
    current_capture: CaptureMetadata,
) -> CaptureComparison | None:
    """현재 응답과 동일 경기의 직전 응답을 비교합니다."""

    previous_capture = find_previous_capture(event_id, current_capture)

    if previous_capture is None:
        return None

    previous_file_path = Path(previous_capture.raw_file_path)
    current_file_path = Path(current_capture.raw_file_path)

    previous_data = load_json_file(previous_file_path)
    current_data = load_json_file(current_file_path)

    structure_comparison = compare_json_structures(previous_data, current_data)

    return CaptureComparison(
        event_id=event_id,
        previous_capture=previous_capture,
        current_capture=current_capture,
        structure_comparison=structure_comparison,
    )


def convert_to_structure_change_record(
    capture_comparison: CaptureComparison,
    detected_at: datetime,
) -> StructureChangeRecord | None:
    """변경 정보를 기록하기 위한 형태로 변환한다"""

    structure_comparison = capture_comparison.structure_comparison
    if not structure_comparison.has_changes:
        return None

    previous_capture = capture_comparison.previous_capture
    current_capture = capture_comparison.current_capture

    added_paths = sorted(structure_comparison.added_paths)
    removed_paths = sorted(structure_comparison.removed_paths)
    type_changes = [
        TypeChangeRecord(
            path=type_change.path,
            previous_types=sorted(type_change.previous_types),
            current_types=sorted(type_change.current_types),
        )
        for type_change in structure_comparison.type_changes
    ]

    type_changes.sort(key=lambda type_change_record: type_change_record.path)

    return StructureChangeRecord(
        detected_at=detected_at,
        event_id=capture_comparison.event_id,
        previous_captured_at=previous_capture.captured_at,
        current_captured_at=current_capture.captured_at,
        previous_raw_file_path=previous_capture.raw_file_path,
        current_raw_file_path=current_capture.raw_file_path,
        added_paths=added_paths,
        removed_paths=removed_paths,
        type_changes=type_changes,
    )


def _extract_structure(data: Any) -> dict[str, set[str]]:
    """JSON 전체에서 경로별 자료형을 수집합니다."""

    structure: dict[str, set[str]] = {}

    _walk_structure(value=data, path="$", structure=structure)

    return structure


def _walk_structure(value: Any, path: str, structure: dict[str, set[str]]) -> None:
    """JSON 내부를 재귀적으로 순회합니다."""

    type_name = _get_type_name(value)

    structure.setdefault(path, set()).add(type_name)

    if isinstance(value, dict):
        for key, child_value in value.items():
            _walk_structure(child_value, f"{path}.{key}", structure)

    elif isinstance(value, list):
        for child_value in value:
            _walk_structure(child_value, f"{path}[]", structure)


def _get_type_name(value: Any) -> str:
    """Python 값을 읽기 쉬운 자료형 이름으로 변환합니다."""

    if value is None:
        return "null"

    if isinstance(value, bool):
        return "boolean"

    if isinstance(value, dict):
        return "object"

    if isinstance(value, list):
        return "array"

    if isinstance(value, str):
        return "string"

    if isinstance(value, int):
        return "integer"

    if isinstance(value, float):
        return "number"

    return type(value).__name__
