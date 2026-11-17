from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

AUTO_WATCH_CONFIG_PATH = Path("config/auto_watch.yaml")

AutoWatchCollectionMode = Literal[
    "inplay",  # time_status=1
    "ended",  # time_status=3
    "waiting_to_start",  # time_status=0, 2
    "temporarily_stopped",  # time_status=7, 10
    "closing",  # time_status=4, 5, 6, 8, 9, 11, 12, 99
    "unknown",  # 설정에 없거나 해석할 수 없는 time_status
]
AutoWatchTimeLimitedStatusGroup = Literal[
    "waiting_to_start",  # time_status=0, 2
    "temporarily_stopped",  # time_status=7, 10
    "closing",  # time_status=4, 5, 6, 8, 9, 11, 12, 99
    "unknown",  # 설정에 없거나 해석할 수 없는 time_status
]


class InvalidAutoWatchConfigError(ValueError):
    """Auto-watch 상태 정책 설정이 올바르지 않을 때 발생합니다."""


class WaitingToStartStatusPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    statuses: list[int] = Field(min_length=1)
    max_minutes_after_scheduled_at: int = Field(gt=0)


class TemporarilyStoppedStatusPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    statuses: list[int] = Field(min_length=1)
    max_continuous_minutes: int = Field(gt=0)


class ClosingStatusPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    statuses: list[int] = Field(min_length=1)
    followup_minutes: int = Field(gt=0)


class UnknownStatusPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    max_continuous_minutes: int = Field(gt=0)


class AutoWatchStatusPolicies(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    waiting_to_start: WaitingToStartStatusPolicy
    temporarily_stopped: TemporarilyStoppedStatusPolicy
    closing: ClosingStatusPolicy
    unknown: UnknownStatusPolicy


class EndedStatusPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal[3]
    followup_minutes: int = Field(gt=0)


class AutoWatchRequestLimits(BaseModel):
    """로컬 요청량 경고에 사용할 종목별 시간당 한도입니다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    soccer_per_hour: int = Field(gt=0)
    baseball_per_hour: int = Field(gt=0)
    warning_percent: int = Field(ge=1, lt=100)
    danger_percent: int = Field(ge=1, lt=100)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> Self:
        if self.warning_percent >= self.danger_percent:
            raise ValueError("요청량 주의 기준은 위험 기준보다 작아야 합니다.")
        return self


class AutoWatchConfig(BaseModel):
    """Auto-watch의 time_status별 관찰·종료 정책입니다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status_policies: AutoWatchStatusPolicies
    ended: EndedStatusPolicy
    request_limits: AutoWatchRequestLimits

    @model_validator(mode="after")
    def validate_status_groups(self) -> Self:
        groups = {
            "waiting_to_start": self.status_policies.waiting_to_start.statuses,
            "temporarily_stopped": self.status_policies.temporarily_stopped.statuses,
            "closing": self.status_policies.closing.statuses,
        }
        seen_statuses: dict[int, str] = {}
        for group_name, statuses in groups.items():
            if len(statuses) != len(set(statuses)):
                raise ValueError(f"{group_name} 그룹에 중복 time_status가 있습니다.")
            for time_status in statuses:
                if time_status in (1, self.ended.status):
                    raise ValueError(
                        f"time_status={time_status}은 {group_name} 그룹에 넣을 수 "
                        "없습니다."
                    )
                previous_group = seen_statuses.get(time_status)
                if previous_group is not None:
                    raise ValueError(
                        f"time_status={time_status}이 {previous_group}, "
                        f"{group_name} 그룹에 중복 등록되었습니다."
                    )
                seen_statuses[time_status] = group_name
        return self

    def classify_time_status(self, time_status: int | None) -> AutoWatchCollectionMode:
        """정규화된 time_status를 설정된 처리 그룹으로 분류합니다."""

        if time_status == 1:
            return "inplay"
        if time_status == self.ended.status:
            return "ended"
        if time_status in self.status_policies.waiting_to_start.statuses:
            return "waiting_to_start"
        if time_status in self.status_policies.temporarily_stopped.statuses:
            return "temporarily_stopped"
        if time_status in self.status_policies.closing.statuses:
            return "closing"
        return "unknown"


def load_auto_watch_config(
    file_path: Path = AUTO_WATCH_CONFIG_PATH,
) -> AutoWatchConfig:
    """Auto-watch 상태 정책 YAML을 읽고 검증합니다."""

    config_text = file_path.read_text(encoding="utf-8")
    try:
        config_data = yaml.safe_load(config_text)
    except yaml.YAMLError as error:
        raise InvalidAutoWatchConfigError(
            f"Auto-watch 설정의 YAML 문법이 올바르지 않습니다: {file_path}"
        ) from error

    try:
        return AutoWatchConfig.model_validate(config_data)
    except ValidationError as error:
        raise InvalidAutoWatchConfigError(
            f"Auto-watch 설정이 올바르지 않습니다: {file_path}\n{error}"
        ) from error
