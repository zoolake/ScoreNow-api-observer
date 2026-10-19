from dataclasses import dataclass
from typing import Any, cast

type JsonScalar = str | int | float | bool | None


class InvalidFieldPathError(ValueError):
    """필드 분석에 사용할 수 없는 JSON 경로입니다."""


class UnsupportedArrayFieldPathError(InvalidFieldPathError):
    """현재 분석 범위에서 지원하지 않는 배열 경로입니다."""


class UnsupportedArrayFieldValueError(ValueError):
    """분석 대상 경로 또는 그 하위에서 배열 값이 발견되었습니다."""


@dataclass(frozen=True)
class ResolvedJsonField:
    """JSON 객체에서 요청한 경로를 조회한 결과입니다."""

    present: bool
    value: object


def validate_field_path(path: str) -> tuple[str, ...]:
    """`$.field.child` 형식의 객체 경로를 검증하고 키 목록으로 변환합니다."""

    if not path or path.isspace():
        raise InvalidFieldPathError("필드 경로가 비어 있습니다.")
    if "[" in path or "]" in path:
        raise UnsupportedArrayFieldPathError(
            "배열을 포함한 필드 경로는 지원하지 않습니다."
        )
    if path == "$":
        return ()
    if not path.startswith("$."):
        raise InvalidFieldPathError(
            "필드 경로는 '$' 또는 '$.field.child' 형식이어야 합니다."
        )

    keys = tuple(path[2:].split("."))
    if any(not key for key in keys):
        raise InvalidFieldPathError(f"빈 객체 키가 포함된 필드 경로입니다: {path!r}")
    return keys


def resolve_json_field(
    *,
    data: dict[str, Any],
    path_keys: tuple[str, ...],
) -> ResolvedJsonField:
    """JSON 객체에서 키 경로를 따라 값을 조회하고 존재 여부를 반환합니다."""

    current: object = data
    for key in path_keys:
        if isinstance(current, list):
            raise UnsupportedArrayFieldValueError(
                "요청 경로를 탐색하는 중 배열이 발견되었습니다."
            )
        if not isinstance(current, dict) or key not in current:
            return ResolvedJsonField(present=False, value=None)
        current = current[key]
    return ResolvedJsonField(present=True, value=current)


def flatten_json_object_scalars(
    *,
    value: dict[str, Any],
    path: str,
) -> dict[str, JsonScalar]:
    """중첩 객체를 재귀 순회하여 단일 값 리프 경로와 값을 반환합니다."""

    flattened_values: dict[str, JsonScalar] = {}
    _flatten_json_object_scalars(
        value=value,
        path=path,
        flattened_values=flattened_values,
    )
    return flattened_values


def _flatten_json_object_scalars(
    *,
    value: dict[str, Any],
    path: str,
    flattened_values: dict[str, JsonScalar],
) -> None:
    for key in sorted(value, key=_object_key_sort_key):
        child_value = value[key]
        child_path = f"{path}.{key}" if path != "$" else f"$.{key}"

        if isinstance(child_value, list):
            raise UnsupportedArrayFieldValueError(
                f"{child_path}에서 배열이 발견되었습니다."
            )
        if isinstance(child_value, dict):
            _flatten_json_object_scalars(
                value=child_value,
                path=child_path,
                flattened_values=flattened_values,
            )
        else:
            flattened_values[child_path] = cast(JsonScalar, child_value)


def _object_key_sort_key(key: str) -> tuple[int, int | str]:
    if key.isdecimal():
        return (0, int(key))
    return (1, key)
