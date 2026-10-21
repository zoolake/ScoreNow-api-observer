from dataclasses import dataclass
from pathlib import Path

import yaml

from scorenow_api_observer.reporting.field_path import validate_field_path
from scorenow_api_observer.sport_config import (
    SPORT_CONFIG_PATH,
    load_sport_codes_by_id,
)

TIMELINE_FIELDS_CONFIG_PATH = Path("config/event_view_timeline_fields.yaml")


class InvalidTimelineFieldsConfigError(ValueError):
    """Event View 타임라인 필드 설정이 올바르지 않을 때 발생합니다."""


@dataclass(frozen=True)
class TimelineFieldsConfig:
    """검증을 마친 종목별 Event View 타임라인 필드 경로입니다."""

    paths_by_sport_code: dict[str, tuple[str, ...]]


def load_timeline_fields_config(
    file_path: Path = TIMELINE_FIELDS_CONFIG_PATH,
    sport_config_path: Path = SPORT_CONFIG_PATH,
) -> TimelineFieldsConfig:
    """종목별 타임라인 필드 경로를 YAML 설정에서 읽고 검증합니다."""

    config_text = file_path.read_text(encoding="utf-8")
    try:
        config_data = yaml.safe_load(config_text)
    except yaml.YAMLError as error:
        raise InvalidTimelineFieldsConfigError(
            f"타임라인 필드 설정의 YAML 문법이 올바르지 않습니다: {file_path}"
        ) from error

    if not isinstance(config_data, dict):
        raise InvalidTimelineFieldsConfigError(
            f"타임라인 필드 설정의 최상위 값은 YAML 매핑이어야 합니다: {file_path}"
        )
    if set(config_data) != {"sports"}:
        raise InvalidTimelineFieldsConfigError(
            f"타임라인 필드 설정의 최상위에는 'sports' 필드만 있어야 합니다: "
            f"{file_path}"
        )

    raw_sports = config_data["sports"]
    if not isinstance(raw_sports, dict) or not raw_sports:
        raise InvalidTimelineFieldsConfigError(
            "타임라인 필드 설정의 'sports' 필드는 비어 있지 않은 YAML 매핑이어야 "
            f"합니다: {file_path}"
        )

    registered_sport_codes = set(load_sport_codes_by_id(sport_config_path).values())
    paths_by_sport_code: dict[str, tuple[str, ...]] = {}
    for sport_code, raw_paths in raw_sports.items():
        if not isinstance(sport_code, str) or not sport_code.strip():
            raise InvalidTimelineFieldsConfigError(
                "타임라인 필드 설정의 종목 코드는 비어 있지 않은 문자열이어야 "
                f"합니다: {sport_code!r}"
            )

        normalized_sport_code = sport_code.strip()
        if normalized_sport_code not in registered_sport_codes:
            raise InvalidTimelineFieldsConfigError(
                "종목 매핑 설정에 등록되지 않은 종목 코드가 있습니다: "
                f"{normalized_sport_code!r}"
            )
        if normalized_sport_code in paths_by_sport_code:
            raise InvalidTimelineFieldsConfigError(
                f"공백 제거 후 중복되는 종목 코드가 있습니다: {normalized_sport_code!r}"
            )
        if not isinstance(raw_paths, list) or not raw_paths:
            raise InvalidTimelineFieldsConfigError(
                f"종목 {normalized_sport_code!r}의 타임라인 필드는 비어 있지 않은 "
                "목록이어야 합니다."
            )

        normalized_paths: list[str] = []
        path_keys: list[tuple[str, ...]] = []
        for raw_path in raw_paths:
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise InvalidTimelineFieldsConfigError(
                    f"종목 {normalized_sport_code!r}의 타임라인 필드 경로는 비어 "
                    f"있지 않은 문자열이어야 합니다: {raw_path!r}"
                )

            normalized_path = raw_path.strip()
            if normalized_path == "$":
                raise InvalidTimelineFieldsConfigError(
                    "이벤트 JSON 루트는 타임라인 필드로 등록할 수 없습니다: '$'"
                )
            try:
                normalized_path_keys = validate_field_path(normalized_path)
            except ValueError as error:
                raise InvalidTimelineFieldsConfigError(
                    f"종목 {normalized_sport_code!r}의 타임라인 필드 경로가 "
                    f"올바르지 않습니다: {normalized_path!r} ({error})"
                ) from error

            if normalized_path in normalized_paths:
                raise InvalidTimelineFieldsConfigError(
                    f"종목 {normalized_sport_code!r}에 중복되는 타임라인 필드 "
                    f"경로가 있습니다: {normalized_path!r}"
                )
            for existing_path, existing_keys in zip(
                normalized_paths,
                path_keys,
                strict=True,
            ):
                if _one_path_contains_the_other(existing_keys, normalized_path_keys):
                    raise InvalidTimelineFieldsConfigError(
                        f"종목 {normalized_sport_code!r}에 서로 겹치는 타임라인 필드 "
                        f"경로가 있습니다: {existing_path!r}, {normalized_path!r}"
                    )

            normalized_paths.append(normalized_path)
            path_keys.append(normalized_path_keys)

        paths_by_sport_code[normalized_sport_code] = tuple(normalized_paths)

    return TimelineFieldsConfig(paths_by_sport_code=paths_by_sport_code)


def _one_path_contains_the_other(
    first: tuple[str, ...],
    second: tuple[str, ...],
) -> bool:
    shorter_length = min(len(first), len(second))
    return first[:shorter_length] == second[:shorter_length]
