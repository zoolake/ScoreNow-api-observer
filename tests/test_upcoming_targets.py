from pathlib import Path

import pytest
import yaml

from scorenow_api_observer.upcoming.targets import (
    InvalidUpcomingTargetsConfigError,
    InvalidUpcomingTargetSelectionError,
    UpcomingTarget,
    load_upcoming_targets,
    select_upcoming_targets,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _sport_config(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "sports.yaml",
        'sport_ids:\n  "1": football\n  "16": baseball\n',
    )


def test_load_upcoming_targets_reads_default_config() -> None:
    targets = load_upcoming_targets()

    assert len(targets) == 42
    assert targets[0] == UpcomingTarget(
        sport_id="1",
        sport_code="football",
        league_id="8914",
        league_label="k-league-2",
    )
    assert targets[-1] == UpcomingTarget(
        sport_id="16",
        sport_code="baseball",
        league_id="38891",
        league_label="wbsc-premier-12",
    )


def test_load_upcoming_targets_normalizes_whitespace(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "targets.yaml",
        """
targets:
  - sport_id: " 16 "
    leagues:
      - league_id: " 225 "
        label: " mlb "
""",
    )

    result = load_upcoming_targets(config_path, _sport_config(tmp_path))

    assert result == [UpcomingTarget("16", "baseball", "225", "mlb")]


def test_load_upcoming_targets_wraps_yaml_error(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "targets.yaml", "targets: [\n")

    with pytest.raises(InvalidUpcomingTargetsConfigError, match="YAML 문법") as info:
        load_upcoming_targets(config_path, _sport_config(tmp_path))

    assert isinstance(info.value.__cause__, yaml.YAMLError)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("targets: []\n", "at least 1 item"),
        (
            """
targets:
  - sport_id: "16"
    leagues:
      - league_id: "225"
        label: "MLB"
""",
            "string_pattern_mismatch",
        ),
        (
            """
targets:
  - sport_id: "16"
    leagues:
      - league_id: "225"
        label: mlb
  - sport_id: "16"
    leagues:
      - league_id: "349"
        label: kbo
""",
            "중복되는 sport_id",
        ),
        (
            """
targets:
  - sport_id: "16"
    leagues:
      - league_id: "225"
        label: baseball
      - league_id: "349"
        label: baseball
""",
            "중복되는 label",
        ),
    ],
)
def test_load_upcoming_targets_rejects_invalid_config(
    tmp_path: Path,
    content: str,
    expected_message: str,
) -> None:
    config_path = _write(tmp_path / "targets.yaml", content)

    with pytest.raises(InvalidUpcomingTargetsConfigError, match=expected_message):
        load_upcoming_targets(config_path, _sport_config(tmp_path))


def test_load_upcoming_targets_rejects_unregistered_sport(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "targets.yaml",
        """
targets:
  - sport_id: "99"
    leagues:
      - league_id: "1"
        label: unknown
""",
    )

    with pytest.raises(InvalidUpcomingTargetsConfigError, match="등록되지 않은"):
        load_upcoming_targets(config_path, _sport_config(tmp_path))


def test_select_upcoming_targets_uses_config_order_and_deduplicates_labels() -> None:
    targets = [
        UpcomingTarget("16", "baseball", "225", "mlb"),
        UpcomingTarget("16", "baseball", "349", "kbo"),
    ]

    result = select_upcoming_targets(targets, " kbo,mlb,kbo ")

    assert result == targets


def test_select_upcoming_targets_returns_all_when_labels_are_omitted() -> None:
    targets = [UpcomingTarget("16", "baseball", "225", "mlb")]

    assert select_upcoming_targets(targets, None) == targets


@pytest.mark.parametrize("league_labels", ["", "mlb,", ",mlb"])
def test_select_upcoming_targets_rejects_empty_label(league_labels: str) -> None:
    targets = [UpcomingTarget("16", "baseball", "225", "mlb")]

    with pytest.raises(InvalidUpcomingTargetSelectionError, match="빈 값 없이"):
        select_upcoming_targets(targets, league_labels)


def test_select_upcoming_targets_rejects_unknown_label() -> None:
    targets = [UpcomingTarget("16", "baseball", "225", "mlb")]

    with pytest.raises(InvalidUpcomingTargetSelectionError, match="unknown"):
        select_upcoming_targets(targets, "unknown")
