import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scorenow_api_observer.models import CaptureMetadata
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


def find_latest_captures(
    event_id: str,
    limit: int = 2,
    base_directory: Path = METADATA_DIRECTORY,
) -> list[CaptureMetadata]:
    """특정 경기의 최근 호출 기록을 찾습니다."""

    captures: list[CaptureMetadata] = []

    for metadata_path in base_directory.rglob("*.json"):
        metadata_text = metadata_path.read_text(
            encoding="utf-8"
        )  # read_text vs read_content
        metadata = CaptureMetadata.model_validate_json(metadata_text)

        if event_id in metadata.event_ids:
            captures.append(metadata)

    captures.sort(key=lambda capture: capture.captured_at)

    return captures[-limit:]


def load_json_file(file_path: Path) -> Any:
    """저장된 원문 JSON 파일을 읽습니다."""

    file_text = file_path.read_text(encoding="utf-8")
    return json.loads(file_text)  # json.load() vs json.loads()


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
    for path in sorted(
        common_paths
    ):  # sorted 가 뭐고 common_paths 가 아닌 sorted(common_paths)를 쓰는 이유
        previous_types = previous_structure[path]
        current_types = current_structure[path]

        if previous_types != current_types:
            type_changes.append(
                TypeChange(
                    path=path, previous_types=previous_types, current_types=current_types
                )
            )

    return StructureComparison(
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
