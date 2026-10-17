import re
from pathlib import Path

import yaml

SPORT_CONFIG_PATH = Path("config/betsapi_sports.yaml")
SAFE_SPORT_CODE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class InvalidSportConfigError(ValueError):
    """종목 매핑 설정의 구조나 값이 올바르지 않을 때 발생합니다."""


def load_sport_codes_by_id(file_path: Path = SPORT_CONFIG_PATH) -> dict[str, str]:
    """BETS sport_id와 내부 종목 코드의 매핑을 읽고 검증합니다."""

    config_text = file_path.read_text(encoding="utf-8")

    try:
        config_data = yaml.safe_load(config_text)
    except yaml.YAMLError as error:
        raise InvalidSportConfigError(
            f"종목 매핑 설정의 YAML 문법이 올바르지 않습니다: {file_path}"
        ) from error

    if not isinstance(config_data, dict):
        raise InvalidSportConfigError(
            f"종목 매핑 설정의 최상위 값은 YAML 매핑이어야 합니다: {file_path}"
        )

    raw_sport_codes_by_id = config_data.get("sport_ids")

    if raw_sport_codes_by_id is None:
        raise InvalidSportConfigError(
            f"종목 매핑 설정에 'sport_ids' 필드가 없습니다: {file_path}"
        )

    if not isinstance(raw_sport_codes_by_id, dict):
        raise InvalidSportConfigError(
            f"종목 매핑 설정의 'sport_ids' 필드는 YAML 매핑이어야 합니다: {file_path}"
        )

    if not raw_sport_codes_by_id:
        raise InvalidSportConfigError(
            f"종목 매핑 설정의 'sport_ids' 필드는 비어 있을 수 없습니다: {file_path}"
        )

    sport_codes_by_id: dict[str, str] = {}
    sport_ids_by_code: dict[str, str] = {}
    for sport_id, sport_code in raw_sport_codes_by_id.items():
        if not isinstance(sport_id, str):
            raise InvalidSportConfigError(
                f"'sport_ids'의 모든 ID는 문자열이어야 합니다: {sport_id!r}"
            )

        normalized_sport_id = sport_id.strip()
        if not normalized_sport_id:
            raise InvalidSportConfigError(
                "'sport_ids'에 비어 있는 sport_id가 있습니다."
            )

        if not isinstance(sport_code, str):
            raise InvalidSportConfigError(
                f"sport_id {normalized_sport_id!r}의 종목 코드는 문자열이어야 "
                f"합니다: {sport_code!r}"
            )

        normalized_sport_code = sport_code.strip()
        if not normalized_sport_code:
            raise InvalidSportConfigError(
                f"sport_id {normalized_sport_id!r}의 종목 코드가 비어 있습니다."
            )

        if SAFE_SPORT_CODE_PATTERN.fullmatch(normalized_sport_code) is None:
            raise InvalidSportConfigError(
                f"sport_id {normalized_sport_id!r}의 종목 코드는 영문 소문자, 숫자, "
                f"하이픈만 사용할 수 있습니다: {normalized_sport_code!r}"
            )

        if normalized_sport_id in sport_codes_by_id:
            raise InvalidSportConfigError(
                f"공백 제거 후 중복되는 sport_id가 있습니다: {normalized_sport_id!r}"
            )

        if normalized_sport_code in sport_ids_by_code:
            raise InvalidSportConfigError(
                f"공백 제거 후 중복되는 종목 코드가 있습니다: {normalized_sport_code!r}"
            )

        sport_codes_by_id[normalized_sport_id] = normalized_sport_code
        sport_ids_by_code[normalized_sport_code] = normalized_sport_id

    return sport_codes_by_id
