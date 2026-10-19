from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from scorenow_api_observer.reporting.analysis import (
    ObservedEvent,
    ObservedEventResolutionFailure,
)
from scorenow_api_observer.reporting.field_path import (
    JsonScalar,
    UnsupportedArrayFieldValueError,
    flatten_json_object_scalars,
    resolve_json_field,
    validate_field_path,
)

type FieldValueChangeKind = Literal[
    "initial",
    "appeared",
    "changed",
    "disappeared",
]
type FieldPresenceChangeKind = Literal[
    "initial",
    "appeared",
    "disappeared",
]


@dataclass(frozen=True)
class FieldValueChange:
    """단일 값 필드에서 관측한 최초 상태 또는 상태 변화입니다.

    Attributes:
        captured_at: 변화가 관측된 Capture의 UTC 수집 시각입니다.
        raw_file_path: 변화의 근거가 되는 원문 Capture 파일 경로입니다.
        kind: 최초 상태, 등장, 값 변경 또는 사라짐을 구분합니다.
        previous_present: 직전 분석 Observation에 필드가 존재했는지 나타냅니다.
        previous_value: 직전 필드 값입니다. previous_present가 False이면 사용하지
            않습니다.
        current_present: 현재 분석 Observation에 필드가 존재하는지 나타냅니다.
        current_value: 현재 필드 값입니다. current_present가 False이면 사용하지
            않습니다.
    """

    captured_at: datetime
    raw_file_path: Path
    kind: FieldValueChangeKind
    previous_present: bool
    previous_value: JsonScalar
    current_present: bool
    current_value: JsonScalar


@dataclass(frozen=True)
class FieldPresenceChange:
    """중첩 객체의 최초 존재 상태 또는 등장·사라짐 기록입니다."""

    captured_at: datetime
    raw_file_path: Path
    kind: FieldPresenceChangeKind
    present: bool


@dataclass(frozen=True)
class FieldValueTimeline:
    """하나의 단일 값 JSON 경로에서 관측된 시간순 변화입니다."""

    path: str
    changes: list[FieldValueChange]


@dataclass(frozen=True)
class EventFieldInspection:
    """이벤트 하나에서 요청한 JSON 경로를 분석한 결과입니다.

    Attributes:
        event_id: 외부 API 이벤트 ID입니다.
        input_observation_count: 종목·이벤트 필터를 통과한 Observation 수입니다.
        analyzed_observation_count: 배열 등 지원하지 않는 값을 제외하고 실제 변화
            분석에 사용한 Observation 수입니다.
        object_presence_changes: 요청 경로가 중첩 객체이면 객체 자체의 존재 변화를
            기록합니다. 단일 값 경로이면 빈 목록입니다.
        value_timelines: 요청한 단일 값 경로 또는 중첩 객체를 펼쳐 얻은 하위 단일 값
            경로별 변화입니다.
    """

    event_id: str
    input_observation_count: int
    analyzed_observation_count: int
    object_presence_changes: list[FieldPresenceChange]
    value_timelines: list[FieldValueTimeline]


@dataclass(frozen=True)
class FieldInspectionFailure:
    """Observation 하나를 필드 변화 분석에서 제외한 기록입니다."""

    event_id: str
    captured_at: datetime
    raw_file_path: Path
    error_message: str


@dataclass(frozen=True)
class FieldInspectionAnalysis:
    """저장된 Event View Observation의 필드 변화 분석 결과입니다.

    Attributes:
        sport_code: 분석 대상으로 선택한 내부 종목 코드입니다.
        requested_path: 분석을 요청한 JSON 객체 경로입니다.
        event_id_filter: 사용자가 선택한 이벤트 ID입니다. 전체 이벤트를 분석하면
            None입니다.
        input_observation_count: 종목·이벤트 필터를 통과한 전체 Observation 수입니다.
        analyzed_observation_count: 배열 등 지원하지 않는 값을 제외하고 경로 존재
            여부를 확인한 Observation 수입니다. 경로가 없었던 Observation도 포함합니다.
        input_event_count: 종목·이벤트 필터를 통과한 고유 이벤트 수입니다.
        events: 요청 경로가 한 번 이상 관측되어 변화 보고서에 포함된 이벤트입니다.
        resolution_failures: 원문 참조를 해석하지 못한 EventObservation 기록입니다.
        field_failures: 값의 형태 때문에 필드 분석에서 제외한 Observation 기록입니다.
    """

    sport_code: str
    requested_path: str
    event_id_filter: str | None
    input_observation_count: int
    analyzed_observation_count: int
    input_event_count: int
    events: list[EventFieldInspection]
    resolution_failures: list[ObservedEventResolutionFailure]
    field_failures: list[FieldInspectionFailure]

    @property
    def observed_event_count(self) -> int:
        """요청 경로가 한 번 이상 관측된 고유 이벤트 수입니다."""

        return len(self.events)

    @property
    def unobserved_event_count(self) -> int:
        """요청 경로가 한 번도 관측되지 않아 보고서에서 생략된 이벤트 수입니다."""

        return self.input_event_count - self.observed_event_count


@dataclass(frozen=True)
class _ResolvedFieldValue:
    observed_event: ObservedEvent
    present: bool
    value: JsonScalar | dict[str, Any]
    flattened_values: dict[str, JsonScalar]


def analyze_field_inspection(
    *,
    observed_events: list[ObservedEvent],
    resolution_failures: list[ObservedEventResolutionFailure],
    sport_code: str,
    path: str,
    event_id: str | None = None,
) -> FieldInspectionAnalysis:
    """선택한 종목·이벤트의 JSON 필드가 시간에 따라 변한 과정을 분석합니다.

    단일 값 경로는 그대로 타임라인을 만들고, 중첩 객체 경로는 모든 Observation에서
    관측한 하위 단일 값 경로의 합집합을 구해 경로별 타임라인으로 펼칩니다. 배열이
    발견된 Observation은 실패 기록으로 남기고 나머지 분석을 계속합니다.
    """

    path_keys = validate_field_path(path)
    selected_events = [
        observed_event
        for observed_event in observed_events
        if observed_event.sport_code == sport_code
        and (event_id is None or observed_event.event_id == event_id)
    ]
    selected_events.sort(key=_observed_event_sort_key)

    events_by_id: dict[str, list[ObservedEvent]] = {}
    for observed_event in selected_events:
        events_by_id.setdefault(observed_event.event_id, []).append(observed_event)

    event_inspections: list[EventFieldInspection] = []
    field_failures: list[FieldInspectionFailure] = []
    analyzed_observation_count = 0
    for current_event_id in sorted(events_by_id):
        event_inspection, event_failures, requested_path_observed = (
            _analyze_event_field(
                observed_events=events_by_id[current_event_id],
                path=path,
                path_keys=path_keys,
            )
        )
        analyzed_observation_count += event_inspection.analyzed_observation_count
        if requested_path_observed:
            event_inspections.append(event_inspection)
        field_failures.extend(event_failures)

    return FieldInspectionAnalysis(
        sport_code=sport_code,
        requested_path=path,
        event_id_filter=event_id,
        input_observation_count=len(selected_events),
        analyzed_observation_count=analyzed_observation_count,
        input_event_count=len(events_by_id),
        events=event_inspections,
        resolution_failures=resolution_failures,
        field_failures=field_failures,
    )


def _analyze_event_field(
    *,
    observed_events: list[ObservedEvent],
    path: str,
    path_keys: tuple[str, ...],
) -> tuple[EventFieldInspection, list[FieldInspectionFailure], bool]:
    """이벤트 하나의 Observation을 요청 경로 기준으로 분석합니다."""

    resolved_values: list[_ResolvedFieldValue] = []
    failures: list[FieldInspectionFailure] = []

    for observed_event in observed_events:
        try:
            resolved_value = _resolve_and_flatten_field_value(
                observed_event=observed_event,
                path=path,
                path_keys=path_keys,
            )
        except UnsupportedArrayFieldValueError as error:
            failures.append(
                FieldInspectionFailure(
                    event_id=observed_event.event_id,
                    captured_at=observed_event.captured_at,
                    raw_file_path=observed_event.raw_file_path,
                    error_message=str(error),
                )
            )
        else:
            resolved_values.append(resolved_value)

    object_mode = any(
        resolved.present and isinstance(resolved.value, dict)
        for resolved in resolved_values
    )
    requested_path_observed = any(resolved.present for resolved in resolved_values)
    if object_mode:
        resolved_values, incompatible_failures = _exclude_non_object_values(
            resolved_values=resolved_values,
            path=path,
        )
        failures.extend(incompatible_failures)
        presence_changes = _build_object_presence_changes(resolved_values)
        value_timelines = _build_object_value_timelines(resolved_values)
    else:
        presence_changes = []
        value_timelines = (
            [
                FieldValueTimeline(
                    path=path,
                    changes=_build_value_changes(
                        [
                            (
                                resolved.observed_event,
                                resolved.present,
                                cast(JsonScalar, resolved.value)
                                if resolved.present
                                else None,
                            )
                            for resolved in resolved_values
                        ]
                    ),
                )
            ]
            if resolved_values
            else []
        )

    return (
        EventFieldInspection(
            event_id=observed_events[0].event_id,
            input_observation_count=len(observed_events),
            analyzed_observation_count=len(resolved_values),
            object_presence_changes=presence_changes,
            value_timelines=value_timelines,
        ),
        failures,
        requested_path_observed,
    )


def _resolve_and_flatten_field_value(
    *,
    observed_event: ObservedEvent,
    path: str,
    path_keys: tuple[str, ...],
) -> _ResolvedFieldValue:
    resolved_field = resolve_json_field(
        data=observed_event.event_data,
        path_keys=path_keys,
    )
    if not resolved_field.present:
        return _ResolvedFieldValue(
            observed_event=observed_event,
            present=False,
            value=None,
            flattened_values={},
        )
    value = resolved_field.value
    if isinstance(value, list):
        raise UnsupportedArrayFieldValueError(
            f"{path}에서 배열이 발견되어 해당 Observation을 제외했습니다."
        )
    if not isinstance(value, dict):
        scalar_value = cast(JsonScalar, value)
        return _ResolvedFieldValue(
            observed_event=observed_event,
            present=True,
            value=scalar_value,
            flattened_values={path: scalar_value},
        )

    flattened_values = flatten_json_object_scalars(
        value=value,
        path=path,
    )
    return _ResolvedFieldValue(
        observed_event=observed_event,
        present=True,
        value=value,
        flattened_values=flattened_values,
    )


def _exclude_non_object_values(
    *,
    resolved_values: list[_ResolvedFieldValue],
    path: str,
) -> tuple[list[_ResolvedFieldValue], list[FieldInspectionFailure]]:
    compatible_values: list[_ResolvedFieldValue] = []
    failures: list[FieldInspectionFailure] = []

    for resolved in resolved_values:
        if not resolved.present or isinstance(resolved.value, dict):
            compatible_values.append(resolved)
            continue

        observed_event = resolved.observed_event
        failures.append(
            FieldInspectionFailure(
                event_id=observed_event.event_id,
                captured_at=observed_event.captured_at,
                raw_file_path=observed_event.raw_file_path,
                error_message=(
                    f"{path}가 다른 Observation에서는 객체이지만 이 Observation에서는 "
                    f"{type(resolved.value).__name__}이므로 제외했습니다."
                ),
            )
        )

    return compatible_values, failures


def _build_object_presence_changes(
    resolved_values: list[_ResolvedFieldValue],
) -> list[FieldPresenceChange]:
    changes: list[FieldPresenceChange] = []
    previous_present: bool | None = None

    for index, resolved in enumerate(resolved_values):
        present = resolved.present
        if index > 0 and present == previous_present:
            continue

        if index == 0:
            kind: FieldPresenceChangeKind = "initial"
        elif present:
            kind = "appeared"
        else:
            kind = "disappeared"

        changes.append(
            FieldPresenceChange(
                captured_at=resolved.observed_event.captured_at,
                raw_file_path=resolved.observed_event.raw_file_path,
                kind=kind,
                present=present,
            )
        )
        previous_present = present

    return changes


def _build_object_value_timelines(
    resolved_values: list[_ResolvedFieldValue],
) -> list[FieldValueTimeline]:
    leaf_paths = {
        path for resolved in resolved_values for path in resolved.flattened_values
    }
    timelines: list[FieldValueTimeline] = []

    for leaf_path in sorted(leaf_paths, key=_field_path_sort_key):
        snapshots: list[tuple[ObservedEvent, bool, JsonScalar]] = []
        for resolved in resolved_values:
            present = leaf_path in resolved.flattened_values
            snapshots.append(
                (
                    resolved.observed_event,
                    present,
                    resolved.flattened_values.get(leaf_path),
                )
            )
        timelines.append(
            FieldValueTimeline(
                path=leaf_path,
                changes=_build_value_changes(snapshots),
            )
        )

    return timelines


def _build_value_changes(
    snapshots: Sequence[tuple[ObservedEvent, bool, JsonScalar]],
) -> list[FieldValueChange]:
    changes: list[FieldValueChange] = []
    previous_present = False
    previous_value: JsonScalar = None

    for index, (observed_event, current_present, current_value) in enumerate(snapshots):
        if index > 0 and _field_values_are_equal(
            previous_present=previous_present,
            previous_value=previous_value,
            current_present=current_present,
            current_value=current_value,
        ):
            continue

        if index == 0:
            kind: FieldValueChangeKind = "initial"
        elif not previous_present and current_present:
            kind = "appeared"
        elif previous_present and not current_present:
            kind = "disappeared"
        else:
            kind = "changed"

        changes.append(
            FieldValueChange(
                captured_at=observed_event.captured_at,
                raw_file_path=observed_event.raw_file_path,
                kind=kind,
                previous_present=previous_present,
                previous_value=previous_value,
                current_present=current_present,
                current_value=current_value,
            )
        )
        previous_present = current_present
        previous_value = current_value

    return changes


def _field_values_are_equal(
    *,
    previous_present: bool,
    previous_value: JsonScalar,
    current_present: bool,
    current_value: JsonScalar,
) -> bool:
    if previous_present != current_present:
        return False
    if not current_present:
        return True
    return (
        type(previous_value) is type(current_value) and previous_value == current_value
    )


def _observed_event_sort_key(observed_event: ObservedEvent) -> tuple[object, ...]:
    return (
        observed_event.event_id,
        observed_event.captured_at,
        str(observed_event.raw_file_path),
        observed_event.result_index,
    )


def _object_key_sort_key(key: str) -> tuple[int, int | str]:
    if key.isdecimal():
        return (0, int(key))
    return (1, key)


def _field_path_sort_key(path: str) -> tuple[tuple[int, int | str], ...]:
    path_without_root = path.removeprefix("$.")
    return tuple(_object_key_sort_key(key) for key in path_without_root.split("."))
