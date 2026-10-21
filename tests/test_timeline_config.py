from pathlib import Path

import pytest
import yaml

from scorenow_api_observer.reporting.timeline_config import (
    InvalidTimelineFieldsConfigError,
    TimelineFieldsConfig,
    load_timeline_fields_config,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _sport_config(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "sports.yaml",
        'sport_ids:\n  "1": football\n  "16": baseball\n',
    )


def test_load_timeline_fields_config_reads_default_config() -> None:
    result = load_timeline_fields_config()

    assert set(result.paths_by_sport_code) == {"football", "baseball"}
    assert all(result.paths_by_sport_code.values())


def test_load_timeline_fields_config_normalizes_whitespace(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "timeline-fields.yaml",
        'sports:\n  " baseball ":\n    - " $.time_status "\n',
    )

    result = load_timeline_fields_config(config_path, _sport_config(tmp_path))

    assert result == TimelineFieldsConfig(
        paths_by_sport_code={"baseball": ("$.time_status",)}
    )


def test_load_timeline_fields_config_wraps_yaml_error(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "timeline-fields.yaml", "sports: [\n")

    with pytest.raises(InvalidTimelineFieldsConfigError, match="YAML 문법") as info:
        load_timeline_fields_config(config_path, _sport_config(tmp_path))

    assert isinstance(info.value.__cause__, yaml.YAMLError)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("[]\n", "최상위 값"),
        ("other: {}\n", "'sports' 필드만"),
        ("sports: []\n", "비어 있지 않은 YAML 매핑"),
        ("sports:\n  baseball: []\n", "비어 있지 않은 목록"),
        ("sports:\n  baseball:\n    - '$'\n", "루트"),
        ("sports:\n  baseball:\n    - '$.scores[]'\n", "배열"),
        (
            "sports:\n  baseball:\n    - '$.scores'\n    - ' $.scores '\n",
            "중복되는 타임라인 필드",
        ),
        (
            "sports:\n  baseball:\n    - '$.scores'\n    - '$.scores.10'\n",
            "서로 겹치는 타임라인 필드",
        ),
    ],
)
def test_load_timeline_fields_config_rejects_invalid_structure_or_path(
    tmp_path: Path,
    content: str,
    expected_message: str,
) -> None:
    config_path = _write(tmp_path / "timeline-fields.yaml", content)

    with pytest.raises(InvalidTimelineFieldsConfigError, match=expected_message):
        load_timeline_fields_config(config_path, _sport_config(tmp_path))


def test_load_timeline_fields_config_rejects_unregistered_sport(
    tmp_path: Path,
) -> None:
    config_path = _write(
        tmp_path / "timeline-fields.yaml",
        "sports:\n  basketball:\n    - '$.time_status'\n",
    )

    with pytest.raises(InvalidTimelineFieldsConfigError, match="등록되지 않은"):
        load_timeline_fields_config(config_path, _sport_config(tmp_path))
