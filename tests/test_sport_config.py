from pathlib import Path

import pytest
import yaml

from scorenow_api_observer.sport_config import (
    InvalidSportConfigError,
    load_sport_codes_by_id,
)


def _write_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "sports.yaml"
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_load_sport_codes_by_id_reads_default_config() -> None:
    result = load_sport_codes_by_id()

    assert result == {
        "1": "football",
        "16": "baseball",
        "18": "basketball",
    }


def test_load_sport_codes_by_id_normalizes_surrounding_whitespace(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        'sport_ids:\n  " 16 ": " baseball "\n',
    )

    result = load_sport_codes_by_id(config_path)

    assert result == {"16": "baseball"}


def test_load_sport_codes_by_id_propagates_missing_file_error(
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.yaml"

    with pytest.raises(FileNotFoundError):
        load_sport_codes_by_id(missing_path)


def test_load_sport_codes_by_id_wraps_yaml_syntax_error(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, 'sport_ids:\n  "1": [\n')

    with pytest.raises(InvalidSportConfigError, match="YAML 문법") as exception_info:
        load_sport_codes_by_id(config_path)

    assert isinstance(exception_info.value.__cause__, yaml.YAMLError)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("[]\n", "최상위 값"),
        ("other: {}\n", "'sport_ids' 필드가 없습니다"),
        ("sport_ids: []\n", "'sport_ids' 필드는 YAML 매핑"),
        ("sport_ids: {}\n", "'sport_ids' 필드는 비어 있을 수 없습니다"),
    ],
)
def test_load_sport_codes_by_id_rejects_invalid_structure(
    tmp_path: Path,
    content: str,
    expected_message: str,
) -> None:
    config_path = _write_config(tmp_path, content)

    with pytest.raises(InvalidSportConfigError, match=expected_message):
        load_sport_codes_by_id(config_path)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("sport_ids:\n  1: football\n", "모든 ID는 문자열"),
        ('sport_ids:\n  "   ": football\n', "비어 있는 sport_id"),
        ('sport_ids:\n  "1": 1\n', "종목 코드는 문자열"),
        ('sport_ids:\n  "1": "   "\n', "종목 코드가 비어 있습니다"),
        ('sport_ids:\n  "1": "Foot Ball"\n', "영문 소문자"),
        (
            'sport_ids:\n  "1": football\n  " 1 ": baseball\n',
            "공백 제거 후 중복되는 sport_id",
        ),
        (
            'sport_ids:\n  "1": football\n  "16": " football "\n',
            "중복되는 종목 코드",
        ),
    ],
)
def test_load_sport_codes_by_id_rejects_invalid_mapping_entry(
    tmp_path: Path,
    content: str,
    expected_message: str,
) -> None:
    config_path = _write_config(tmp_path, content)

    with pytest.raises(InvalidSportConfigError, match=expected_message):
        load_sport_codes_by_id(config_path)
