from typing import Any


def extract_json_structure(data: Any) -> dict[str, set[str]]:
    """JSON 전체에서 경로별 자료형을 수집합니다."""

    structure: dict[str, set[str]] = {}

    _walk_structure(value=data, path="$", structure=structure)

    return structure


def _walk_structure(value: Any, path: str, structure: dict[str, set[str]]) -> None:
    """JSON 내부를 재귀적으로 순회합니다."""

    type_name = get_json_type_name(value)

    structure.setdefault(path, set()).add(type_name)

    if isinstance(value, dict):
        for key, child_value in value.items():
            _walk_structure(child_value, f"{path}.{key}", structure)

    elif isinstance(value, list):
        for child_value in value:
            _walk_structure(child_value, f"{path}[]", structure)


def get_json_type_name(value: Any) -> str:
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
