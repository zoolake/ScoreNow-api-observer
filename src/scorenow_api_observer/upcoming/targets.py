from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from scorenow_api_observer.sport_config import (
    SPORT_CONFIG_PATH,
    load_sport_codes_by_id,
)

UPCOMING_TARGETS_CONFIG_PATH = Path("config/betsapi_upcoming_targets.yaml")

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
SafeLabel = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]


class InvalidUpcomingTargetsConfigError(ValueError):
    """Upcoming 조회 대상 설정이 올바르지 않을 때 발생합니다."""


class InvalidUpcomingTargetSelectionError(ValueError):
    """CLI에서 선택한 리그 label이 올바르지 않을 때 발생합니다."""


class UpcomingLeagueTargetConfig(BaseModel):
    """설정 파일에 기록하는 리그별 Upcoming 조회 대상입니다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    league_id: NonEmptyString
    label: SafeLabel


class UpcomingSportTargetConfig(BaseModel):
    """하나의 종목과 그 종목에서 조회할 리그 목록입니다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    sport_id: NonEmptyString
    leagues: list[UpcomingLeagueTargetConfig] = Field(min_length=1)


class UpcomingTargetsConfig(BaseModel):
    """Upcoming 조회 대상 설정 파일의 최상위 모델입니다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    targets: list[UpcomingSportTargetConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_targets(self) -> Self:
        sport_ids: set[str] = set()
        target_pairs: set[tuple[str, str]] = set()
        labels: set[str] = set()

        for sport_target in self.targets:
            if sport_target.sport_id in sport_ids:
                raise ValueError(
                    f"중복되는 sport_id가 있습니다: {sport_target.sport_id!r}"
                )
            sport_ids.add(sport_target.sport_id)

            for league_target in sport_target.leagues:
                target_pair = (sport_target.sport_id, league_target.league_id)
                if target_pair in target_pairs:
                    raise ValueError(
                        "중복되는 sport_id와 league_id 조합이 있습니다: "
                        f"{target_pair!r}"
                    )
                target_pairs.add(target_pair)

                if league_target.label in labels:
                    raise ValueError(
                        f"중복되는 label이 있습니다: {league_target.label!r}"
                    )
                labels.add(league_target.label)

        return self


@dataclass(frozen=True)
class UpcomingTarget:
    """검증을 마쳐 한 번의 Upcoming API 호출에 사용할 조회 대상입니다."""

    sport_id: str
    sport_code: str
    league_id: str
    league_label: str


def load_upcoming_targets(
    file_path: Path = UPCOMING_TARGETS_CONFIG_PATH,
    sport_config_path: Path = SPORT_CONFIG_PATH,
) -> list[UpcomingTarget]:
    """Upcoming 조회 대상 설정을 읽고 호출 단위의 목록으로 펼칩니다."""

    config_text = file_path.read_text(encoding="utf-8")

    try:
        config_json = yaml.safe_load(config_text)
    except yaml.YAMLError as error:
        raise InvalidUpcomingTargetsConfigError(
            f"Upcoming 조회 대상 설정의 YAML 문법이 올바르지 않습니다: {file_path}"
        ) from error

    try:
        config = UpcomingTargetsConfig.model_validate(config_json)
    except ValidationError as error:
        raise InvalidUpcomingTargetsConfigError(
            f"Upcoming 조회 대상 설정이 올바르지 않습니다: {file_path}\n{error}"
        ) from error

    sport_codes_by_id = load_sport_codes_by_id(sport_config_path)

    unknown_sport_ids = sorted(
        {
            target.sport_id
            for target in config.targets
            if target.sport_id not in sport_codes_by_id
        }
    )
    if unknown_sport_ids:
        raise InvalidUpcomingTargetsConfigError(
            "종목 매핑 설정에 등록되지 않은 sport_id가 있습니다: "
            + ", ".join(repr(sport_id) for sport_id in unknown_sport_ids)
        )

    return [
        UpcomingTarget(
            sport_id=sport_target.sport_id,
            sport_code=sport_codes_by_id[sport_target.sport_id],
            league_id=league_target.league_id,
            league_label=league_target.label,
        )
        for sport_target in config.targets
        for league_target in sport_target.leagues
    ]


def select_upcoming_targets(
    targets: list[UpcomingTarget],
    league_labels: str | None,
) -> list[UpcomingTarget]:
    """쉼표로 구분한 label에 해당하는 대상을 설정 순서대로 선택합니다."""

    if league_labels is None:
        return list(targets)

    parsed_labels = [label.strip() for label in league_labels.split(",")]
    if not parsed_labels or any(not label for label in parsed_labels):
        raise InvalidUpcomingTargetSelectionError(
            "리그 label은 빈 값 없이 쉼표로 구분해야 합니다."
        )

    selected_labels = set(parsed_labels)
    known_labels = {target.league_label for target in targets}
    unknown_labels = sorted(selected_labels - known_labels)
    if unknown_labels:
        raise InvalidUpcomingTargetSelectionError(
            "설정에 등록되지 않은 리그 label이 있습니다: "
            + ", ".join(repr(label) for label in unknown_labels)
        )

    return [target for target in targets if target.league_label in selected_labels]
